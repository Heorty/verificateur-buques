"""Chargement unifié et indexation de la base de données Clun'ss (.xlsx / .csv)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import database
from .phonetics import PhoneticProfile, build_profile, compare_profiles


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BDD_DIR = BASE_DIR / "bdd"
DEFAULT_BDD_FILE = DEFAULT_BDD_DIR / "Liste_PGs_Clun_ssois.xlsx"

_JUNK_QUESTION_RE = re.compile(r"^\?+$")
_PROMS_CODE_RE = re.compile(r"^(?:Cl\s*)?(\d{2,3})(?:\s*\(\d+\))?$", re.IGNORECASE)
_YEAR_PREFIX_RE = re.compile(r"^\d{4}(?:-\d{4})?$")
_PURE_FAMS_RE = re.compile(
    r"^(?:i?\d+(?:\s*[-+&/]\s*\d+)*|\d+.*👑.*|\?+)$"
)
_CT_STATUS_SUFFIX_RE = re.compile(
    r"\s*\((?:mut[eé]|56-57|42|sortie)\)\s*$", re.IGNORECASE
)


@dataclass
class BddRecord:
    kind: str  # "pg" ou "ct"
    buque: str
    nom: str
    prenom: str
    fams: str
    proms: int | None
    annee: str
    source: str
    profile: PhoneticProfile


@dataclass
class BddIndex:
    pg_records: list[BddRecord] = field(default_factory=list)
    ct_records: list[BddRecord] = field(default_factory=list)
    pg_by_proms: dict[int, list[BddRecord]] = field(default_factory=dict)
    ct_by_visual: dict[str, list[BddRecord]] = field(default_factory=dict)
    ct_by_phonetic: dict[str, list[BddRecord]] = field(default_factory=dict)
    extra_batches: list[dict[str, Any]] = field(default_factory=list)
    default_file_loaded: bool = False
    default_file_name: str = "bdd/Liste_PGs_Clun_ssois.xlsx"

    def get_pgs_in_window(self, current_proms: int, rule1_years: int) -> list[BddRecord]:
        start_proms = current_proms - rule1_years
        out: list[BddRecord] = []
        for p in range(start_proms, current_proms):
            out.extend(self.pg_by_proms.get(p, []))
        return out

    def get_stats(self, current_proms: int, rule1_years: int) -> dict[str, Any]:
        start_proms = current_proms - rule1_years
        recent_counts = {}
        missing_proms = []
        total_recent = 0
        for p in range(start_proms, current_proms):
            cnt = len(self.pg_by_proms.get(p, []))
            recent_counts[str(p)] = cnt
            total_recent += cnt
            if cnt == 0:
                missing_proms.append(p)

        return {
            "total_pgs": len(self.pg_records),
            "total_cts": len(self.ct_records),
            "window_start": start_proms,
            "window_end": current_proms - 1,
            "total_recent_pgs": total_recent,
            "recent_proms_counts": recent_counts,
            "missing_recent_proms": missing_proms,
            "extra_batches": self.extra_batches,
            "default_file_loaded": self.default_file_loaded,
            "default_file_name": self.default_file_name,
        }

    def search(self, query: str, kind: str = "all", limit: int = 80) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        q_prof = build_profile(q)
        pool: list[BddRecord] = []
        if kind in ("all", "pg"):
            pool.extend(self.pg_records)
        if kind in ("all", "ct"):
            pool.extend(self.ct_records)

        q_lower = q.lower()
        hits: list[tuple[float, BddRecord]] = []
        for rec in pool:
            if q_lower in rec.buque.lower() or q_lower in rec.nom.lower():
                hits.append((1.0, rec))
                continue
            best, _, _ = compare_profiles(q_prof, rec.profile, min_threshold=0.75)
            if best >= 0.75:
                hits.append((best, rec))

        hits.sort(key=lambda x: (-x[0], -(x[1].proms or 0), x[1].buque.lower()))
        results = []
        for score, rec in hits[:limit]:
            results.append(
                {
                    "kind": rec.kind,
                    "buque": rec.buque,
                    "nom": rec.nom,
                    "prenom": rec.prenom,
                    "fams": rec.fams,
                    "proms": rec.proms,
                    "annee": rec.annee,
                    "source": rec.source,
                    "score": round(score * 100),
                    "phonetic": rec.profile.primary_phonetic,
                }
            )
        return results


def _is_valid_buque(val: str) -> bool:
    s = val.strip()
    if not s or _JUNK_QUESTION_RE.match(s):
        return False
    if s.upper() == "DEMISSIONNAIRE":
        return False
    if not re.search(r"[A-Za-zÀ-ÿ0-9πΠφΦΩωαΑτΤμµ∞€$]", s):
        return False
    return True


def _cell_to_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Vrai" if val else "Faux"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def _normalize_header(h: str) -> str:
    nfd = unicodedata.normalize("NFD", str(h or ""))
    ascii_s = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").lower()
    ascii_s = re.sub(r"['’`\-_/.,:;()]+", " ", ascii_s)
    return re.sub(r"\s+", " ", ascii_s).strip()


def parse_ct_bool(val: Any) -> bool:
    """Convertit une cellule CT (bool, 1/0, Vrai/Faux, Oui/Non, X...) en booléen."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    s = _normalize_header(str(val or ""))
    return s in {"vrai", "true", "oui", "yes", "1", "x", "ct", "o", "y"}


def _interpret_proms_or_year(raw_val: str) -> tuple[int | None, str]:
    s = raw_val.strip()
    if not s:
        return None, ""

    # Plage de type "2025-2026" ou "1969-1982"
    m_span = re.match(r"^(\d{4})\s*[-/]\s*(\d{4})$", s)
    if m_span:
        y1, y2 = int(m_span.group(1)), int(m_span.group(2))
        if y2 - y1 <= 1 and 1800 <= y1 <= 2150:
            return y1 - 1800, s
        return None, s

    # Numéro ou code Cl225 / 225 / 2025 / 43
    m_code = re.match(r"^(?:cl\s*)?(\d{2,4})$", s, re.IGNORECASE)
    if m_code:
        num = int(m_code.group(1))
        if num >= 1800:
            return num - 1800, str(num)
        if num >= 100:
            return num, str(1800 + num)
        return 100 + num, str(1900 + num)

    return None, s


def parse_proms_and_year(proms_raw: Any, year_raw: Any) -> tuple[int | None, str]:
    """Déduit (proms_int, annee_str) à partir d'une valeur Prom'ss et/ou Année d'entrée."""
    p_str = _cell_to_str(proms_raw)
    y_str = _cell_to_str(year_raw)

    p_from_p, y_from_p = _interpret_proms_or_year(p_str)
    p_from_y, y_from_y = _interpret_proms_or_year(y_str)

    proms = p_from_p if p_from_p is not None else p_from_y
    annee = y_str or y_from_y or y_from_p
    if not annee and proms is not None:
        annee = str(1800 + proms)
    return proms, annee


def _read_table_rows(file_bytes: bytes, filename: str) -> list[list[Any]]:
    ext = Path(filename or "").suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xltx"):
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
        return [r for r in rows if any(_cell_to_str(c) for c in r)]

    text = file_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:3000]
    counts = {";": sample.count(";"), ",": sample.count(","), "\t": sample.count("\t")}
    delimiter = max(counts, key=counts.get)
    if counts[delimiter] == 0:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [r for r in reader if any(c.strip() for c in r)]


def _detect_columns(header_row: list[Any]) -> dict[str, int | None] | None:
    norm = [_normalize_header(_cell_to_str(c)) for c in header_row]
    col_buque = next(
        (
            i
            for i, h in enumerate(norm)
            if h in {"buque", "buques", "surnom", "surnoms", "nickname"}
            or "buque" in h.split()
            or "surnom" in h.split()
        ),
        None,
    )
    if col_buque is None:
        return None

    col_proms = next(
        (
            i
            for i, h in enumerate(norm)
            if h in {"promss", "proms", "promo", "promotion", "promotions"}
            or any(tok.startswith("prom") for tok in h.split())
        ),
        None,
    )
    col_year = next(
        (
            i
            for i, h in enumerate(norm)
            if h in {"annee", "annees", "annee dentree", "annee entree", "anss", "year", "entree"}
            or "annee" in h.split()
        ),
        None,
    )
    col_ct = next(
        (
            i
            for i, h in enumerate(norm)
            if h in {"ct", "est ct", "is ct", "comite", "comite des traditions"}
            or "ct" in h.split()
            or "traditions" in h.split()
        ),
        None,
    )
    col_nom = next(
        (
            i
            for i, h in enumerate(norm)
            if h in {"nom", "noms", "nom de famille", "nom de peks", "patronyme"}
        ),
        None,
    )
    col_prenom = next(
        (i for i, h in enumerate(norm) if h in {"prenom", "prenoms"}), None
    )
    col_fams = next(
        (i for i, h in enumerate(norm) if h in {"fams", "famille", "familles"}), None
    )

    return {
        "buque": col_buque,
        "proms": col_proms,
        "year": col_year,
        "ct": col_ct,
        "nom": col_nom,
        "prenom": col_prenom,
        "fams": col_fams,
    }


def parse_unified_table(
    file_bytes: bytes,
    filename: str = "import.csv",
    force_mode: str = "auto",
    default_proms: int | None = None,
    batch_name: str = "Import manuel",
) -> list[dict[str, Any]]:
    """
    Analyse un fichier .xlsx ou .csv unifié.
    Colonnes reconnues automatiquement :
    - Buque (obligatoire)
    - Prom'ss et/ou Année d'entrée (ex: 225, Cl225, 2025, 2025-2026)
    - CT (Vrai / Faux / Oui / Non / 1 / 0)
    - Optionnelles : Nom, Prénom, Fam's
    """
    rows = _read_table_rows(file_bytes, filename)
    if not rows:
        raise ValueError("Le fichier est vide ou illisible.")

    header_idx = None
    cols = None
    for i, row in enumerate(rows[:6]):
        detected = _detect_columns(row)
        if detected is not None:
            header_idx = i
            cols = detected
            break

    if cols is None or header_idx is None:
        raise ValueError(
            "Colonne « Buque » introuvable dans les premières lignes. "
            "En-têtes attendus : Buque, Prom'ss / Année d'entrée, CT."
        )

    out: list[dict[str, Any]] = []
    for row in rows[header_idx + 1 :]:
        b_idx = cols["buque"]
        if b_idx is None or b_idx >= len(row):
            continue
        buque = _cell_to_str(row[b_idx])
        if not _is_valid_buque(buque):
            continue

        proms_cell = row[cols["proms"]] if cols["proms"] is not None and cols["proms"] < len(row) else None
        year_cell = row[cols["year"]] if cols["year"] is not None and cols["year"] < len(row) else None
        proms_val, annee_val = parse_proms_and_year(proms_cell, year_cell)

        if proms_val is None and default_proms is not None:
            proms_val = int(default_proms)
            if not annee_val:
                annee_val = str(1800 + proms_val)

        if force_mode == "ct":
            is_ct = True
        elif force_mode == "pg":
            is_ct = False
        elif cols["ct"] is not None and cols["ct"] < len(row):
            is_ct = parse_ct_bool(row[cols["ct"]])
        else:
            is_ct = False

        if not is_ct and proms_val is None:
            raise ValueError(
                f"Impossible de déterminer la Prom'ss ou l'année d'entrée pour « {buque} ». "
                "Ajoutez une colonne Prom'ss / Année d'entrée ou renseignez la Prom'ss par défaut."
            )

        nom = _cell_to_str(row[cols["nom"]]) if cols["nom"] is not None and cols["nom"] < len(row) else ""
        prenom = _cell_to_str(row[cols["prenom"]]) if cols["prenom"] is not None and cols["prenom"] < len(row) else ""
        fams = _cell_to_str(row[cols["fams"]]) if cols["fams"] is not None and cols["fams"] < len(row) else ""

        out.append(
            {
                "kind": "ct" if is_ct else "pg",
                "is_ct": is_ct,
                "buque": buque,
                "nom": nom,
                "prenom": prenom,
                "fams": fams,
                "proms": proms_val,
                "annee": annee_val,
                "batch_name": batch_name,
            }
        )

    if not out:
        raise ValueError("Aucune buque valide trouvée dans ce fichier.")
    return out


def generate_bdd_template_xlsx() -> bytes:
    """Génère un fichier Excel modèle prêt à remplir pour l'import de buques."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Modele_Buques"

    headers = ["Buque", "Année d'entrée / Prom'ss", "CT", "Nom", "Prénom", "Fam's"]
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"

    examples = [
        ["Pompl(Arts)", 225, "Faux", "Brondin", "", "19-115"],
        ["Rapido", 2025, "Vrai", "Dupont", "", "60"],
        ["Pastaga", 2002, "Vrai", "", "", "96-153"],
    ]
    for r_idx, row_vals in enumerate(examples, start=2):
        for c_idx, val in enumerate(row_vals, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    widths = [24, 26, 12, 20, 16, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- Parseurs historiques conservés pour la compilation vers Liste_PGs_Clun_ssois.xlsx ---

def parse_legacy_pg_csv(path: Path) -> list[BddRecord]:
    if not path.exists():
        return []
    dedup: dict[tuple[str, int | None, str], BddRecord] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    header_idx = 0
    for i, row in enumerate(rows[:5]):
        joined = ",".join(c.strip().lower() for c in row)
        if "buque" in joined and "prom" in joined:
            header_idx = i
            break

    for row in rows[header_idx + 1 :]:
        if len(row) < 5:
            continue
        nom = row[0].strip()
        prenom = row[1].strip()
        buque = row[2].strip()
        fams = row[3].strip()
        proms_raw = row[4].strip()
        if not _is_valid_buque(buque):
            continue
        proms = int(proms_raw) if proms_raw.isdigit() else None
        prof = build_profile(buque)
        key = (prof.visual_clean or buque.lower(), proms, nom.lower())
        if key in dedup:
            if fams and fams not in dedup[key].fams.split(", "):
                dedup[key].fams = f"{dedup[key].fams}, {fams}".strip(", ")
        else:
            dedup[key] = BddRecord(
                kind="pg",
                buque=buque,
                nom=nom,
                prenom=prenom,
                fams=fams,
                proms=proms,
                annee=str(1800 + proms) if proms else "",
                source="Liste PGs Clunss",
                profile=prof,
            )
    return list(dedup.values())


def parse_legacy_cl225_csv(path: Path) -> list[BddRecord]:
    if not path.exists():
        return []
    records: list[BddRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return records
    for row in rows[1:]:
        if len(row) < 2:
            continue
        nom = row[0].strip()
        buque = row[1].strip()
        fams = row[2].strip() if len(row) > 2 else ""
        if not _is_valid_buque(buque):
            continue
        records.append(
            BddRecord(
                kind="pg",
                buque=buque,
                nom=nom,
                prenom="",
                fams=fams,
                proms=225,
                annee="2025",
                source="CL225",
                profile=build_profile(buque),
            )
        )
    return records


def _extract_proms_int_legacy(proms_str: str) -> int | None:
    s = proms_str.strip()
    m = _PROMS_CODE_RE.match(s)
    if not m:
        return None
    val = int(m.group(1))
    if val < 100:
        return 100 + val
    return val


def _clean_ct_candidate(raw_cell: str) -> list[str]:
    s = raw_cell.strip()
    if not s or not _is_valid_buque(s):
        return []
    if _PURE_FAMS_RE.match(s) or _YEAR_PREFIX_RE.match(s):
        return []
    if re.match(r"^(?:Cl\s*\d+|\d+\s*\(sortie\)|Comité)", s, re.IGNORECASE):
        return []
    s = _CT_STATUS_SUFFIX_RE.sub("", s).strip()
    if not _is_valid_buque(s):
        return []
    return [p.strip() for p in s.split("/") if _is_valid_buque(p.strip())]


def parse_legacy_ct_csv(path: Path) -> list[BddRecord]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    records: list[BddRecord] = []
    seen: set[tuple[str, str]] = set()
    mode = "standard"
    last_annee = ""
    last_proms1_str = ""
    last_proms2_str = ""

    def _add_ct(buque_raw: str, annee: str, proms_str: str) -> None:
        for b in _clean_ct_candidate(buque_raw):
            p_int = _extract_proms_int_legacy(proms_str)
            prof = build_profile(b)
            key = (prof.visual_clean or b.lower(), proms_str or annee)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                BddRecord(
                    kind="ct",
                    buque=b,
                    nom="",
                    prenom="",
                    fams="",
                    proms=p_int,
                    annee=annee or proms_str,
                    source="Liste des CT",
                    profile=prof,
                )
            )

    for row in rows:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        col0 = cells[0] if len(cells) > 0 else ""

        if col0.startswith("An'ss"):
            joined = " ".join(cells)
            if "Président aux traditions" in joined or "Veneb" in joined or "Paillasse" in joined:
                mode = "dual"
            else:
                mode = "standard"
            continue

        if col0.startswith("Période lacunaire"):
            mode = "lacunaire"
            continue

        if mode == "lacunaire":
            col1 = cells[1] if len(cells) > 1 else ""
            if col0:
                last_annee = col0
            if col1.startswith("Cl"):
                for c in cells[2:]:
                    _add_ct(c, last_annee or "1969", col1)
            else:
                for c in cells[1:]:
                    _add_ct(c, last_annee or "1969-1982", "1969-1982")
            continue

        if mode == "dual":
            col1 = cells[1] if len(cells) > 1 else ""
            col8 = cells[8] if len(cells) > 8 else ""
            if col0:
                last_annee = col0
            if col1:
                last_proms1_str = col1
            if col8:
                last_proms2_str = col8
            for idx in (2, 4, 6):
                if idx < len(cells) and cells[idx]:
                    _add_ct(cells[idx], last_annee, last_proms1_str)
            for idx in (9, 11, 13):
                if idx < len(cells) and cells[idx]:
                    _add_ct(cells[idx], last_annee, last_proms2_str)
            continue

        col1 = cells[1] if len(cells) > 1 else ""
        if col0:
            last_annee = col0
        if col1:
            last_proms1_str = col1
        idx = 2
        while idx < len(cells):
            if cells[idx]:
                _add_ct(cells[idx], last_annee, last_proms1_str)
            idx += 2

    return records


def load_bdd_index(
    bdd_file: Path | None = None, db_path: Path | None = None
) -> BddIndex:
    """
    Charge UNIQUEMENT le fichier unifié par défaut (bdd/Liste_PGs_Clun_ssois.xlsx)
    + les imports manuels stockés en SQLite.
    """
    if bdd_file is not None:
        target_file = Path(bdd_file)
    else:
        env_file = os.environ.get("BUQUES_BDD_FILE")
        target_file = Path(env_file) if env_file else DEFAULT_BDD_FILE

    pg_records: list[BddRecord] = []
    ct_records: list[BddRecord] = []
    pg_seen: set[tuple[str, int | None]] = set()
    ct_seen: set[tuple[str, int | None, str]] = set()
    default_loaded = False

    def _register_row(
        buque: str,
        nom: str,
        prenom: str,
        fams: str,
        proms: int | None,
        annee: str,
        is_ct: bool,
        source: str,
    ) -> None:
        prof = build_profile(buque)
        vis_key = prof.visual_clean or buque.lower()

        # Enregistrer en tant que PG si prom's connue (Règle 1)
        if not is_ct or proms is not None:
            pg_k = (vis_key, proms)
            if pg_k not in pg_seen:
                pg_seen.add(pg_k)
                pg_records.append(
                    BddRecord(
                        kind="pg",
                        buque=buque,
                        nom=nom,
                        prenom=prenom,
                        fams=fams,
                        proms=proms,
                        annee=annee,
                        source=source,
                        profile=prof,
                    )
                )

        # Enregistrer en tant que CT si CT=Vrai (Règle 2)
        if is_ct:
            ct_k = (vis_key, proms, annee if proms is None else "")
            if ct_k not in ct_seen:
                ct_seen.add(ct_k)
                ct_records.append(
                    BddRecord(
                        kind="ct",
                        buque=buque,
                        nom=nom,
                        prenom=prenom,
                        fams=fams,
                        proms=proms,
                        annee=annee,
                        source=source,
                        profile=prof,
                    )
                )

    if target_file.exists():
        parsed = parse_unified_table(
            target_file.read_bytes(),
            filename=target_file.name,
            force_mode="auto",
            batch_name=target_file.name,
        )
        for row in parsed:
            _register_row(
                buque=row["buque"],
                nom=row["nom"],
                prenom=row["prenom"],
                fams=row["fams"],
                proms=row["proms"],
                annee=row["annee"],
                is_ct=row["is_ct"],
                source=target_file.name,
            )
        default_loaded = True

    extra_rows = database.list_extra_bdd_records(db_path)
    batches_summary: dict[str, dict[str, Any]] = {}
    for er in extra_rows:
        is_ct = er["kind"] == "ct"
        _register_row(
            buque=er["buque"],
            nom=er["nom"],
            prenom=er["prenom"],
            fams=er["fams"],
            proms=er["proms"],
            annee=er["annee"],
            is_ct=is_ct,
            source=f"Import : {er['batch_name']}",
        )

        bname = er["batch_name"]
        if bname not in batches_summary:
            batches_summary[bname] = {
                "batch_name": bname,
                "kind": er["kind"],
                "proms": er["proms"],
                "count": 0,
            }
        batches_summary[bname]["count"] += 1

    index = BddIndex(
        pg_records=pg_records,
        ct_records=ct_records,
        extra_batches=list(batches_summary.values()),
        default_file_loaded=default_loaded,
        default_file_name=str(target_file.name),
    )

    for rec in pg_records:
        if rec.proms is not None:
            index.pg_by_proms.setdefault(rec.proms, []).append(rec)

    for rec in ct_records:
        if rec.profile.visual_clean:
            index.ct_by_visual.setdefault(rec.profile.visual_clean, []).append(rec)
        for ph in rec.profile.phonetic_readings:
            if ph:
                index.ct_by_phonetic.setdefault(ph, []).append(rec)

    return index

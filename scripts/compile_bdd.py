"""Compile et déduplique sans perte d'information toutes les bases de bdd/ vers bdd/Liste_PGs_Clun_ssois.xlsx."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
import unicodedata

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import bdd_loader
from app.phonetics import compare_profiles


def _merge_tokens(*values: str) -> str:
    parts: list[str] = []
    for val in values:
        for item in str(val or "").split(","):
            clean = item.strip()
            if clean and clean not in parts:
                parts.append(clean)
    return ", ".join(parts)


def _norm_name(s: str) -> str:
    nfd = unicodedata.normalize("NFD", str(s or ""))
    ascii_s = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"[^a-z0-9]", "", ascii_s)


def _buque_richness(b: str) -> tuple[int, int, int]:
    """Score de richesse pour choisir la meilleure graphie entre deux variantes d'un même PG."""
    has_notation = 1 if re.search(r"[()\[\]²³⁰ᵗᵀπφΩ∞]", b) else 0
    has_mixed_or_accent = 1 if (not b.isupper() or any(ord(c) > 127 for c in b)) else 0
    return (has_notation, has_mixed_or_accent, len(b))


def _choose_richer_buque(b1: str, b2: str) -> str:
    if not b1:
        return b2
    if not b2:
        return b1
    return b1 if _buque_richness(b1) >= _buque_richness(b2) else b2


def _norm_fams(fams: str) -> str:
    return re.sub(r"\s+", " ", str(fams or "").strip()).lower()


def _fams_tokens(fams: str) -> set[str]:
    return {tok.lower() for tok in re.split(r"[-&+/,\s()]+", str(fams or "").strip()) if tok}


def _choose_richer_fams(f1: str, f2: str) -> str:
    s1 = str(f1 or "").strip()
    s2 = str(f2 or "").strip()
    if not s1:
        return s2
    if not s2:
        return s1
    t1 = _fams_tokens(s1)
    t2 = _fams_tokens(s2)
    if t1 < t2:
        return s2
    if t2 < t1:
        return s1
    return s1 if len(s1) >= len(s2) else s2


def _apply_merge(target: dict, rec: bdd_loader.BddRecord, *, update_fams: bool = True) -> None:
    target["buque"] = _choose_richer_buque(target["buque"], rec.buque)
    if not target["nom"] and rec.nom:
        target["nom"] = rec.nom
    if not target["prenom"] and rec.prenom:
        target["prenom"] = rec.prenom
    if update_fams:
        target["fams"] = _choose_richer_fams(target["fams"], rec.fams)
    target["sortie"] = _merge_tokens(target["sortie"], rec.sortie)
    target["sources"] = _merge_tokens(target["sources"], rec.source)
    target["profile"] = bdd_loader.build_profile(target["buque"])


def _select_person_rows(cands: list[dict], ct_fams: str) -> list[dict]:
    if not cands:
        return []
    groups: dict[str, list[dict]] = {}
    for row in cands:
        groups.setdefault(_norm_name(row["nom"]), []).append(row)
    if len(groups) == 1:
        return cands
    ct_toks = _fams_tokens(ct_fams)
    if ct_toks:
        for grp in groups.values():
            grp_toks = set().union(*(_fams_tokens(r["fams"]) for r in grp))
            if grp_toks & ct_toks:
                return grp
    return next(iter(groups.values()))


def compile_unified_xlsx(
    bdd_dir: Path | None = None, output_path: Path | None = None
) -> dict[str, object]:
    directory = bdd_dir or (ROOT_DIR / "bdd")
    out_file = output_path or (directory / "Liste_PGs_Clun_ssois.xlsx")

    pg_xlsx = bdd_loader.parse_legacy_pg_xlsx(
        directory / "222_Liste PGs Clun_sssois - à jour.xlsx"
    )
    pg_csv = bdd_loader.parse_legacy_pg_csv(
        directory / "Liste PGs Clun_sssois - à jour.xlsx - Liste PGs Clunss.csv"
    )
    cl225 = bdd_loader.parse_legacy_cl225_csv(
        directory / "CL225 buques - buques(1).csv"
    )
    cts_raw = bdd_loader.parse_legacy_ct_csv(
        directory / "Liste des CT.xlsx - Feuil1.csv"
    )

    pg_xlsx_main = [r for r in pg_xlsx if r.source != "Check buque 2.22"]
    pg_xlsx_check = [r for r in pg_xlsx if r.source == "Check buque 2.22"]

    # 1. Fusion des PGs sans perte d'information :
    #    - Conserve les multi-Fam's sur des lignes indépendantes (une ligne par Fam's)
    #    - Fusionne les doublons exacts d'un même (PG, Fam's) entre fichiers
    #    - Conserve deux lignes distinctes si deux PGs différents partagent la même buque dans une promo (Noms distincts)
    by_vp: dict[tuple[str, int | None], list[dict]] = {}
    pg_merged_count = 0

    for rec in pg_xlsx_main + pg_csv + cl225 + pg_xlsx_check:
        vis = rec.profile.visual_clean or rec.buque.lower()
        vp_key = (vis, rec.proms)
        candidates = by_vp.setdefault(vp_key, [])
        rec_nom_norm = _norm_name(rec.nom)
        rec_fams_norm = _norm_fams(rec.fams)
        rec_fams_toks = _fams_tokens(rec.fams)

        target: dict | None = None
        covered_by_existing_person = False

        if candidates:
            if rec_nom_norm:
                # Cas A : deux enregistrements avec Nom -> fusionner uniquement si même Nom ET même Fam's (ou Fam's manquante)
                for row in candidates:
                    row_nom_norm = _norm_name(row["nom"])
                    row_fams_norm = _norm_fams(row["fams"])
                    if row_nom_norm and row_nom_norm == rec_nom_norm:
                        if rec_fams_norm == row_fams_norm or not rec_fams_norm or not row_fams_norm:
                            target = row
                            break
                # Priorité B4 : ligne existante sans Nom correspondant au même Fam's (ou sans Fam's)
                if target is None:
                    for row in candidates:
                        row_nom_norm = _norm_name(row["nom"])
                        row_fams_norm = _norm_fams(row["fams"])
                        if not row_nom_norm and (
                            not row_fams_norm or not rec_fams_norm or row_fams_norm == rec_fams_norm
                        ):
                            target = row
                            break
            else:
                # Cas B : enregistrement sans Nom (ex: Check buque 2.22 ou Cl223)
                # Priorité B1 : correspondance exacte de Fam's (en privilégiant la même graphie de buque)
                b1_matches = [row for row in candidates if _norm_fams(row["fams"]) == rec_fams_norm]
                if b1_matches:
                    target = next(
                        (r for r in b1_matches if r["buque"].strip().lower() == rec.buque.strip().lower()),
                        b1_matches[0],
                    )

                # Priorité B2 : Fam's vide sur une entrée existante -> éviter une ligne orpheline
                if target is None and not rec_fams_norm:
                    target = candidates[0]

                # Priorité B3 : ligne anonyme couvrant une ou plusieurs lignes existantes
                if target is None:
                    distinct_noms = {_norm_name(r["nom"]) for r in candidates}
                    union_toks = set().union(*(_fams_tokens(r["fams"]) for r in candidates))
                    if len(candidates) > 1 and len(distinct_noms) == 1 and rec_fams_toks and rec_fams_toks <= union_toks:
                        for r in candidates:
                            if _fams_tokens(r["fams"]) & rec_fams_toks:
                                _apply_merge(r, rec, update_fams=False)
                        covered_by_existing_person = True
                    else:
                        sub_matches = [
                            r
                            for r in candidates
                            if not _fams_tokens(r["fams"])
                            or _fams_tokens(r["fams"]) <= rec_fams_toks
                            or rec_fams_toks <= _fams_tokens(r["fams"])
                        ]
                        if sub_matches:
                            target = next(
                                (r for r in sub_matches if r["buque"].strip().lower() == rec.buque.strip().lower()),
                                sub_matches[0],
                            )

        if covered_by_existing_person:
            pg_merged_count += 1
        elif target is not None:
            pg_merged_count += 1
            _apply_merge(target, rec, update_fams=True)
        else:
            candidates.append(
                {
                    "buque": rec.buque,
                    "proms": rec.proms,
                    "annee": str(1800 + rec.proms) if rec.proms else rec.annee,
                    "sortie": rec.sortie,
                    "ct": False,
                    "ct_info": "",
                    "nom": rec.nom,
                    "prenom": rec.prenom,
                    "fams": rec.fams,
                    "sources": rec.source,
                    "profile": rec.profile,
                }
            )

    # 2. Fusion des CTs dans la table PG sur toutes les lignes indépendantes du PG correspondant
    all_pg_by_proms: dict[int | None, list[dict]] = {}
    for vp_list in by_vp.values():
        for row in vp_list:
            all_pg_by_proms.setdefault(row["proms"], []).append(row)

    ct_matched_into_pg = 0
    ct_added_new = 0
    extra_ct_rows: dict[tuple[str, int | None, str], dict] = {}

    for ct_rec in cts_raw:
        vis = ct_rec.profile.visual_clean or ct_rec.buque.lower()
        target_rows: list[dict] | None = None

        # Priorité 1 : match exact (visual_clean, proms)
        if (vis, ct_rec.proms) in by_vp and by_vp[(vis, ct_rec.proms)]:
            target_rows = _select_person_rows(by_vp[(vis, ct_rec.proms)], ct_rec.fams)

        # Priorité 2 : même prom's + même phonétique principale
        if target_rows is None and ct_rec.proms is not None:
            best_score = 0.0
            best_cand = None
            for cand in all_pg_by_proms.get(ct_rec.proms, []):
                if cand["profile"].primary_phonetic == ct_rec.profile.primary_phonetic:
                    score, _, _ = compare_profiles(ct_rec.profile, cand["profile"], min_threshold=0.7)
                    if score > best_score:
                        best_score = score
                        best_cand = cand
            if best_cand is not None:
                cand_vis = best_cand["profile"].visual_clean or best_cand["buque"].lower()
                cand_nom = _norm_name(best_cand["nom"])
                target_rows = [
                    r
                    for r in all_pg_by_proms.get(ct_rec.proms, [])
                    if (r["profile"].visual_clean or r["buque"].lower()) == cand_vis
                    and _norm_name(r["nom"]) == cand_nom
                ]

        # Priorité 3 : anciens PGs (proms <= 195), écart possible ±1 (sortie vs entrée)
        if target_rows is None and ct_rec.proms is not None and ct_rec.proms <= 195:
            for dp in (-1, 1):
                if (vis, ct_rec.proms + dp) in by_vp and by_vp[(vis, ct_rec.proms + dp)]:
                    target_rows = _select_person_rows(by_vp[(vis, ct_rec.proms + dp)], ct_rec.fams)
                    break

        if target_rows:
            single_row = len(target_rows) == 1
            for tr in target_rows:
                tr["ct"] = True
                tr["ct_info"] = _merge_tokens(tr["ct_info"], ct_rec.ct_info)
                tr["sources"] = _merge_tokens(tr["sources"], ct_rec.source)
                if single_row:
                    if not tr["fams"] or _fams_tokens(tr["fams"]) < _fams_tokens(ct_rec.fams):
                        tr["fams"] = _choose_richer_fams(tr["fams"], ct_rec.fams)
                elif not tr["fams"] and ct_rec.fams:
                    tr["fams"] = ct_rec.fams
            ct_matched_into_pg += 1
        else:
            ex_key = (vis, ct_rec.proms, ct_rec.annee if ct_rec.proms is None else "")
            if ex_key in extra_ct_rows:
                ex = extra_ct_rows[ex_key]
                ex["fams"] = _merge_tokens(ex["fams"], ct_rec.fams)
                ex["ct_info"] = _merge_tokens(ex["ct_info"], ct_rec.ct_info)
            else:
                annee_val = (
                    str(1800 + ct_rec.proms)
                    if ct_rec.proms is not None
                    else ct_rec.annee
                )
                extra_ct_rows[ex_key] = {
                    "buque": ct_rec.buque,
                    "proms": ct_rec.proms,
                    "annee": annee_val,
                    "sortie": "",
                    "ct": True,
                    "ct_info": ct_rec.ct_info,
                    "nom": "",
                    "prenom": "",
                    "fams": ct_rec.fams,
                    "sources": ct_rec.source,
                    "profile": ct_rec.profile,
                }
                ct_added_new += 1

    # 3. Assemblage & tri final : Prom'ss décroissante, CT Vrai d'abord, Buque, Nom, Fam's numérique
    def _fams_sort_key(val: str) -> tuple[int, int | str]:
        s = str(val or "").strip()
        if s.isdigit():
            return (0, int(s))
        return (1, s.lower())

    all_rows = [row for vp_list in by_vp.values() for row in vp_list] + list(extra_ct_rows.values())
    final_rows = sorted(
        all_rows,
        key=lambda r: (
            -(r["proms"] if r["proms"] is not None else -1),
            0 if r["ct"] else 1,
            r["buque"].lower(),
            _norm_name(r["nom"]),
            _fams_sort_key(r["fams"]),
        ),
    )

    # 4. Génération du classeur Excel final
    wb = Workbook()
    ws = wb.active
    ws.title = "Buques Clun'ss"

    headers = [
        "Buque",
        "Prom'ss",
        "Année d'entrée",
        "Sortie",
        "CT",
        "Année CT",
        "Nom",
        "Prénom",
        "Fam's",
        "Sources",
    ]
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    ct_fill = PatternFill(start_color="F3E8FF", end_color="F3E8FF", fill_type="solid")
    ct_font = Font(name="Calibri", size=11, bold=True, color="581C87")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if c_idx in (2, 3, 4, 5) else "left", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:J{len(final_rows) + 1}"

    for idx, row in enumerate(final_rows, start=2):
        annee_cell_val = int(row["annee"]) if str(row["annee"]).isdigit() else row["annee"]
        sortie_cell_val = int(row["sortie"]) if str(row["sortie"]).isdigit() else row["sortie"]
        vals = [
            row["buque"],
            row["proms"] if row["proms"] is not None else "",
            annee_cell_val,
            sortie_cell_val,
            "Vrai" if row["ct"] else "Faux",
            row["ct_info"],
            row["nom"],
            row["prenom"],
            row["fams"],
            row["sources"],
        ]
        for c_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=idx, column=c_idx, value=val)
            cell.border = thin_border
            if c_idx in (2, 3, 4, 5):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            if row["ct"]:
                cell.fill = ct_fill
                if c_idx in (1, 5):
                    cell.font = ct_font

    widths = [26, 11, 16, 11, 9, 18, 22, 18, 18, 32]
    for c_idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c_idx)].width = w

    out_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(out_file)
    except PermissionError as exc:
        raise PermissionError(
            f"Impossible d'enregistrer {out_file} : le fichier est actuellement ouvert "
            "dans Excel ou verrouillé par un autre processus. Fermez-le puis réessayez."
        ) from exc

    pg_groups = Counter(
        (
            r["profile"].visual_clean or r["buque"].lower(),
            r["proms"],
            _norm_name(r["nom"]),
            r["annee"] if r["proms"] is None else "",
        )
        for r in final_rows
    )
    unique_pgs = len(pg_groups)
    multi_fams_pgs = sum(1 for c in pg_groups.values() if c > 1)
    multi_fams_extra_rows = sum(c - 1 for c in pg_groups.values() if c > 1)
    recent_counts = Counter(r["proms"] for r in final_rows if r["proms"] and 216 <= r["proms"] <= 225)
    return {
        "total_rows": len(final_rows),
        "unique_pgs": unique_pgs,
        "multi_fams_pgs": multi_fams_pgs,
        "multi_fams_extra_rows": multi_fams_extra_rows,
        "total_ct_vrai_rows": sum(1 for r in final_rows if r["ct"]),
        "pg_merged_count": pg_merged_count,
        "ct_matched_into_pg": ct_matched_into_pg,
        "ct_added_new": ct_added_new,
        "recent_proms": dict(sorted(recent_counts.items())),
    }


if __name__ == "__main__":
    s = compile_unified_xlsx()
    print("Compilation terminée -> bdd/Liste_PGs_Clun_ssois.xlsx")
    for k, v in s.items():
        print(f"  {k}: {v}")

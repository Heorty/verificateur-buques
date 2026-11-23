"""Compile et déduplique les 3 CSV de référence en un seul classeur Excel : bdd/Liste_PGs_Clun_ssois.xlsx."""

from __future__ import annotations

from pathlib import Path
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import bdd_loader
from app.phonetics import compare_profiles


def _merge_fams(f1: str, f2: str) -> str:
    parts: list[str] = []
    for src in (f1, f2):
        for p in src.split(","):
            clean = p.strip()
            if clean and clean not in parts:
                parts.append(clean)
    return ", ".join(parts)


def compile_unified_xlsx(
    bdd_dir: Path | None = None, output_path: Path | None = None
) -> dict[str, int]:
    directory = bdd_dir or (ROOT_DIR / "bdd")
    out_file = output_path or (directory / "Liste_PGs_Clun_ssois.xlsx")

    pg_main = bdd_loader.parse_legacy_pg_csv(
        directory / "Liste PGs Clun_sssois - à jour.xlsx - Liste PGs Clunss.csv"
    )
    cl225 = bdd_loader.parse_legacy_cl225_csv(
        directory / "CL225 buques - buques(1).csv"
    )
    cts_raw = bdd_loader.parse_legacy_ct_csv(
        directory / "Liste des CT.xlsx - Feuil1.csv"
    )

    # 1. Déduplication des PGs sur (visual_clean, proms)
    merged: dict[tuple[str, int | None, str], dict] = {}
    pg_duplicates_removed = 0

    for rec in pg_main + cl225:
        vis = rec.profile.visual_clean or rec.buque.lower()
        key = (vis, rec.proms, "")
        if key in merged:
            pg_duplicates_removed += 1
            cur = merged[key]
            cur["fams"] = _merge_fams(cur["fams"], rec.fams)
            if not cur["nom"] and rec.nom:
                cur["nom"] = rec.nom
            if not cur["prenom"] and rec.prenom:
                cur["prenom"] = rec.prenom
        else:
            merged[key] = {
                "buque": rec.buque,
                "proms": rec.proms,
                "annee": str(1800 + rec.proms) if rec.proms else rec.annee,
                "ct": False,
                "nom": rec.nom,
                "prenom": rec.prenom,
                "fams": rec.fams,
                "profile": rec.profile,
            }

    # 2. Déduplication interne des CTs sur (visual_clean, proms, annee_si_sans_proms)
    ct_unique: dict[tuple[str, int | None, str], bdd_loader.BddRecord] = {}
    ct_duplicates_removed = 0
    for rec in cts_raw:
        vis = rec.profile.visual_clean or rec.buque.lower()
        key = (vis, rec.proms, rec.annee if rec.proms is None else "")
        if key in ct_unique:
            ct_duplicates_removed += 1
        else:
            ct_unique[key] = rec

    # 3. Fusion des CTs dans la table PG sans doublons
    # Index auxiliaires pour rattacher les CTs dont l'orthographe diffère (ex: Chartreuse <-> Ch(Arts)treuse)
    by_vis_proms = {(k[0], k[1]): k for k in merged}
    by_proms_rows: dict[int | None, list[tuple[tuple[str, int | None, str], dict]]] = {}
    for k, row in merged.items():
        by_proms_rows.setdefault(k[1], []).append((k, row))

    ct_matched_into_pg = 0
    ct_added_new = 0

    for ct_rec in ct_unique.values():
        vis = ct_rec.profile.visual_clean or ct_rec.buque.lower()
        target_key = None

        # Priorité 1 : match exact (visual_clean, proms)
        if (vis, ct_rec.proms) in by_vis_proms:
            target_key = by_vis_proms[(vis, ct_rec.proms)]

        # Priorité 2 : même prom's + même phonétique principale
        if target_key is None and ct_rec.proms is not None:
            best_score = 0.0
            for cand_k, cand_row in by_proms_rows.get(ct_rec.proms, []):
                if cand_row["profile"].primary_phonetic == ct_rec.profile.primary_phonetic:
                    score, _, _ = compare_profiles(ct_rec.profile, cand_row["profile"], min_threshold=0.7)
                    if score > best_score:
                        best_score = score
                        target_key = cand_k

        # Priorité 3 : anciens PGs (proms <= 195), écart possible ±1 (sortie vs entrée)
        if target_key is None and ct_rec.proms is not None and ct_rec.proms <= 195:
            for dp in (-1, 1):
                if (vis, ct_rec.proms + dp) in by_vis_proms:
                    target_key = by_vis_proms[(vis, ct_rec.proms + dp)]
                    break

        if target_key is not None:
            merged[target_key]["ct"] = True
            ct_matched_into_pg += 1
        else:
            new_key = (vis, ct_rec.proms, ct_rec.annee if ct_rec.proms is None else "")
            if new_key not in merged:
                annee_val = (
                    str(1800 + ct_rec.proms)
                    if ct_rec.proms is not None
                    else ct_rec.annee
                )
                row_obj = {
                    "buque": ct_rec.buque,
                    "proms": ct_rec.proms,
                    "annee": annee_val,
                    "ct": True,
                    "nom": "",
                    "prenom": "",
                    "fams": "",
                    "profile": ct_rec.profile,
                }
                merged[new_key] = row_obj
                by_vis_proms[(vis, ct_rec.proms)] = new_key
                by_proms_rows.setdefault(ct_rec.proms, []).append((new_key, row_obj))
                ct_added_new += 1
            else:
                merged[new_key]["ct"] = True
                ct_matched_into_pg += 1

    # 4. Tri propre : Prom'ss décroissante, CT Vrai d'abord, puis Buque
    final_rows = sorted(
        merged.values(),
        key=lambda r: (
            -(r["proms"] if r["proms"] is not None else -1),
            0 if r["ct"] else 1,
            r["buque"].lower(),
        ),
    )

    # 5. Génération Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Buques Clun'ss"

    headers = [
        "Buque",
        "Prom'ss",
        "Année d'entrée",
        "CT",
        "Nom",
        "Prénom",
        "Fam's",
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
        cell.alignment = Alignment(horizontal="center" if c_idx in (2, 3, 4) else "left", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{len(final_rows) + 1}"

    for idx, row in enumerate(final_rows, start=2):
        annee_cell_val = int(row["annee"]) if str(row["annee"]).isdigit() else row["annee"]
        vals = [
            row["buque"],
            row["proms"] if row["proms"] is not None else "",
            annee_cell_val,
            "Vrai" if row["ct"] else "Faux",
            row["nom"],
            row["prenom"],
            row["fams"],
        ]
        for c_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=idx, column=c_idx, value=val)
            cell.border = thin_border
            if c_idx in (2, 3, 4):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            if row["ct"]:
                cell.fill = ct_fill
                if c_idx in (1, 4):
                    cell.font = ct_font

    widths = [28, 12, 18, 10, 22, 18, 16]
    for c_idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c_idx)].width = w

    out_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_file)

    stats = {
        "total_rows": len(final_rows),
        "total_ct_vrai": sum(1 for r in final_rows if r["ct"]),
        "pg_duplicates_removed": pg_duplicates_removed,
        "ct_duplicates_removed": ct_duplicates_removed,
        "ct_matched_into_pg": ct_matched_into_pg,
        "ct_added_new": ct_added_new,
    }
    return stats


if __name__ == "__main__":
    s = compile_unified_xlsx()
    print("Compilation terminée -> bdd/Liste_PGs_Clun_ssois.xlsx")
    for k, v in s.items():
        print(f"  {k}: {v}")

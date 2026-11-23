"""Exportation du tableau comparatif 4 colonnes vers Excel (.xlsx) coloré et CSV."""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


COLOR_STYLES: dict[str, tuple[PatternFill, Font]] = {
    "rouge": (
        PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="9C0006"),
    ),
    "violet": (
        PatternFill(start_color="E4C1F9", end_color="E4C1F9", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="4A148C"),
    ),
    "jaune": (
        PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="9C6500"),
    ),
    "orange": (
        PatternFill(start_color="FFD8A8", end_color="FFD8A8", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="9C4221"),
    ),
    "vert": (
        PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="006100"),
    ),
    "empty": (
        PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid"),
        Font(name="Calibri", size=11, italic=True, color="6B7280"),
    ),
}

_THIN_BORDER = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)

_HEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")


def _format_conflicts_summary(choice: dict[str, Any]) -> str:
    conflicts = choice.get("conflicts", {})
    active = set(choice.get("active_rules", []))
    lines: list[str] = []

    if 2 in active and conflicts.get("r2"):
        top = ", ".join(
            f"{m['buque']} ({m.get('annee') or m.get('proms') or 'CT'} - {m['score']}%)"
            for m in conflicts["r2"][:3]
        )
        lines.append(f"Règle 2 (CT) : {top}")

    if 1 in active and conflicts.get("r1"):
        top = ", ".join(
            f"{m['buque']} (Cl{m['proms']} - {m['score']}%)"
            for m in conflicts["r1"][:3]
        )
        lines.append(f"Règle 1 (< 10 ans) : {top}")

    if 4 in active and conflicts.get("r4"):
        top = ", ".join(m.get("reason") or m.get("term", "") for m in conflicts["r4"][:2])
        lines.append(f"Règle 4 (Problématique) : {top}")

    if 3 in active and conflicts.get("r3"):
        top = ", ".join(
            f"{m['nom']} / {m['buque']} (Choix {m['choice_index']} - {m['score']}%)"
            for m in conflicts["r3"][:3]
        )
        lines.append(f"Règle 3 (Même prom'ss) : {top}")

    return "\n".join(lines)


def _auto_fit_columns(ws, min_width: int = 16, max_width: int = 44) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row == 1:
                continue
            val = str(cell.value or "")
            for line in val.splitlines():
                if len(line) > max_len:
                    max_len = len(line)
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, max_len + 4))


def export_xlsx(comparison: dict[str, Any]) -> bytes:
    """Génère un classeur Excel avec le tableau 4 colonnes coloré + un onglet détaillé."""
    wb = Workbook()

    # Onglet 1 : Tableau 4 colonnes exact demandé dans README.md
    ws1 = wb.active
    ws1.title = "Tableau 4 colonnes"
    ws1.views.sheetView[0].showGridLines = True

    proms = comparison["settings"]["current_proms"]
    ws1.merge_cells("A1:D1")
    banner = ws1["A1"]
    banner.value = (
        f"Vérification des Buques — Prom's Cl{proms}  |  "
        "Rouge = Règle 1 (< 10 ans)  ·  Violet = Règle 2 (CT)  ·  "
        "Jaune = Règle 3 (Même prom'ss)  ·  Orange = Règle 4 (Problématique)  ·  "
        "Vert = Utilisable"
    )
    banner.font = Font(name="Calibri", size=10, bold=True, color="1E293B")
    banner.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    banner.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws1.row_dimensions[1].height = 28

    headers1 = ["Nom de famille", "Choix 1", "Choix 2", "Choix 3"]
    for col_idx, h in enumerate(headers1, start=1):
        cell = ws1.cell(row=3, column=col_idx, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = _THIN_BORDER
    ws1.row_dimensions[3].height = 24
    ws1.freeze_panes = "A4"

    rows = sorted(comparison["rows"], key=lambda r: r["nom"].lower())
    for offset, entry in enumerate(rows):
        r_idx = 4 + offset
        ws1.row_dimensions[r_idx].height = 22

        nom_label = entry["nom"]
        if entry.get("prenom"):
            nom_label = f"{entry['nom']} ({entry['prenom']})"
        nom_cell = ws1.cell(row=r_idx, column=1, value=nom_label)
        nom_cell.font = Font(name="Calibri", size=11, bold=True, color="111827")
        nom_cell.alignment = Alignment(horizontal="left", vertical="center")
        nom_cell.border = _THIN_BORDER

        for idx in (1, 2, 3):
            choice = entry["choices"][idx - 1]
            c_idx = 1 + idx
            val = choice["raw"] if choice["raw"] else "—"
            cell = ws1.cell(row=r_idx, column=c_idx, value=val)
            fill, font = COLOR_STYLES.get(choice["color"], COLOR_STYLES["empty"])
            cell.fill = fill
            cell.font = font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = _THIN_BORDER

            summary_txt = _format_conflicts_summary(choice)
            if summary_txt:
                cell.comment = Comment(summary_txt, "Vérificateur de Buques")

    _auto_fit_columns(ws1, min_width=20, max_width=36)

    # Onglet 2 : Détails & Polices
    ws2 = wb.create_sheet("Détails & Polices")
    headers2 = [
        "Nom de famille",
        "Prénom",
        "Choix 1",
        "Police 1",
        "Lecture 1",
        "Statut 1",
        "Conflits 1",
        "Choix 2",
        "Police 2",
        "Lecture 2",
        "Statut 2",
        "Conflits 2",
        "Choix 3",
        "Police 3",
        "Lecture 3",
        "Statut 3",
        "Conflits 3",
        "Saisi par",
    ]
    for col_idx, h in enumerate(headers2, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _THIN_BORDER
    ws2.row_dimensions[1].height = 24
    ws2.freeze_panes = "B2"

    for offset, entry in enumerate(rows):
        r_idx = 2 + offset
        ws2.cell(row=r_idx, column=1, value=entry["nom"]).border = _THIN_BORDER
        ws2.cell(row=r_idx, column=2, value=entry.get("prenom", "")).border = _THIN_BORDER

        col_cursor = 3
        for idx in (1, 2, 3):
            ch = entry["choices"][idx - 1]
            c_buque = ws2.cell(row=r_idx, column=col_cursor, value=ch["raw"])
            c_police = ws2.cell(row=r_idx, column=col_cursor + 1, value=ch["police"])
            lecture = " / ".join(ch["phonetic"].get("expanded_readings", []))
            c_lect = ws2.cell(row=r_idx, column=col_cursor + 2, value=lecture)
            c_stat = ws2.cell(row=r_idx, column=col_cursor + 3, value=ch["label"])
            c_conf = ws2.cell(
                row=r_idx, column=col_cursor + 4, value=_format_conflicts_summary(ch)
            )
            c_conf.alignment = Alignment(wrap_text=True, vertical="center")

            fill, font = COLOR_STYLES.get(ch["color"], COLOR_STYLES["empty"])
            c_stat.fill = fill
            c_stat.font = font
            c_stat.alignment = Alignment(horizontal="center", vertical="center")

            for c in (c_buque, c_police, c_lect, c_stat, c_conf):
                c.border = _THIN_BORDER

            col_cursor += 5

        c_user = ws2.cell(
            row=r_idx,
            column=col_cursor,
            value=entry.get("updated_by") or entry.get("created_by") or "",
        )
        c_user.border = _THIN_BORDER

    _auto_fit_columns(ws2, min_width=14, max_width=40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_csv(comparison: dict[str, Any]) -> bytes:
    """Exporte en CSV UTF-8 avec BOM (séparateur point-virgule pour Excel français)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Nom de famille",
            "Prénom",
            "Choix 1",
            "Statut 1",
            "Police 1",
            "Choix 2",
            "Statut 2",
            "Police 2",
            "Choix 3",
            "Statut 3",
            "Police 3",
            "Détails conflits",
        ]
    )
    rows = sorted(comparison["rows"], key=lambda r: r["nom"].lower())
    for entry in rows:
        details = []
        row_vals = [entry["nom"], entry.get("prenom", "")]
        for idx in (1, 2, 3):
            ch = entry["choices"][idx - 1]
            row_vals.extend([ch["raw"], ch["label"], ch["police"]])
            summary = _format_conflicts_summary(ch)
            if summary:
                details.append(f"[Choix {idx}] {summary.replace(chr(10), ' | ')}")
        row_vals.append(" || ".join(details))
        writer.writerow(row_vals)

    return ("\ufeff" + buf.getvalue()).encode("utf-8")

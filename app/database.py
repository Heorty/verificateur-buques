"""Persistance SQLite pour le Vérificateur de Buques."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "buques.db"

DEFAULT_SETTINGS: dict[str, str] = {
    "current_proms": "226",
    "rule1_years": "10",
    "threshold_r12": "0.85",
    "threshold_r3": "0.75",
    "r3_scope": "all",
}

# Liste de départ pour la règle 4 (modifiable à tout moment depuis l'interface)
SEED_PROBLEMATIC_TERMS: list[tuple[str, str, str]] = [
    ("hitler", "Extrémisme / Histoire", "Référence nazie"),
    ("adolf", "Extrémisme / Histoire", "Prénom associé au nazisme"),
    ("staline", "Extrémisme / Histoire", "Dictateur"),
    ("stalin", "Extrémisme / Histoire", "Dictateur"),
    ("mussolini", "Extrémisme / Histoire", "Régime fasciste"),
    ("goebbels", "Extrémisme / Histoire", "Régime nazi"),
    ("himmler", "Extrémisme / Histoire", "Régime nazi"),
    ("mengele", "Extrémisme / Histoire", "Régime nazi"),
    ("gestapo", "Extrémisme / Histoire", "Police nazie"),
    ("waffen", "Extrémisme / Histoire", "Waffen-SS"),
    ("reich", "Extrémisme / Histoire", "Référence au IIIe Reich"),
    ("swastika", "Extrémisme / Histoire", "Symbole nazi"),
    ("svastika", "Extrémisme / Histoire", "Symbole nazi"),
    ("auschwitz", "Extrémisme / Histoire", "Camp d'extermination"),
    ("shoah", "Extrémisme / Histoire", "Génocide"),
    ("daesh", "Extrémisme / Violence", "Organisation terroriste"),
    ("benladen", "Extrémisme / Violence", "Terrorisme"),
    ("abdeslam", "Extrémisme / Violence", "Terrorisme"),
    ("dutroux", "Faits divers graves", "Criminel"),
    ("fourniret", "Faits divers graves", "Criminel"),
    ("nordahl", "Faits divers graves", "Criminel"),
    ("epstein", "Faits divers graves", "Affaire criminelle"),
    ("negre", "Propos haineux", "Injurieux / raciste"),
    ("negro", "Propos haineux", "Injurieux / raciste"),
    ("bougnoule", "Propos haineux", "Injurieux / raciste"),
    ("bamboula", "Propos haineux", "Injurieux / raciste"),
    ("youpin", "Propos haineux", "Injurieux / antisémite"),
    ("feuj", "Propos haineux", "À vérifier selon contexte"),
    ("pede", "Propos haineux", "Injurieux / homophobe"),
    ("pd", "Propos haineux", "Injurieux / homophobe"),
    ("tapette", "Propos haineux", "Injurieux / homophobe"),
    ("gouine", "Propos haineux", "Injurieux / homophobe"),
    ("salope", "Vulgarité / Sexisme", "Injurieux"),
    ("putain", "Vulgarité", "Vulgaire"),
    ("pute", "Vulgarité / Sexisme", "Injurieux"),
    ("connard", "Vulgarité", "Injurieux"),
    ("encule", "Vulgarité", "Injurieux"),
    ("branleur", "Vulgarité", "Vulgaire"),
    ("couille", "Vulgarité", "Vulgaire"),
    ("chatte", "Vulgarité", "À vérifier selon contexte"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> Path:
    env_path = os.environ.get("BUQUES_DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nom TEXT NOT NULL,
                    prenom TEXT DEFAULT '',
                    choix1 TEXT DEFAULT '',
                    police1 TEXT DEFAULT '',
                    choix2 TEXT DEFAULT '',
                    police2 TEXT DEFAULT '',
                    choix3 TEXT DEFAULT '',
                    police3 TEXT DEFAULT '',
                    created_by TEXT DEFAULT '',
                    updated_by TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS choice_overrides (
                    entry_id INTEGER NOT NULL,
                    choice_index INTEGER NOT NULL CHECK (choice_index IN (1, 2, 3)),
                    is_problematic INTEGER DEFAULT 0,
                    problematic_reason TEXT DEFAULT '',
                    ignored_rules TEXT DEFAULT '[]',
                    updated_by TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (entry_id, choice_index),
                    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS problematic_terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT UNIQUE NOT NULL,
                    category TEXT DEFAULT 'Personnalisé',
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS extra_bdd_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK (kind IN ('pg', 'ct')),
                    buque TEXT NOT NULL,
                    nom TEXT DEFAULT '',
                    prenom TEXT DEFAULT '',
                    fams TEXT DEFAULT '',
                    proms INTEGER,
                    annee TEXT DEFAULT '',
                    batch_name TEXT DEFAULT ''
                );
                """
            )
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
                )

            existing_count = conn.execute(
                "SELECT COUNT(*) FROM problematic_terms"
            ).fetchone()[0]
            if existing_count == 0:
                conn.executemany(
                    "INSERT OR IGNORE INTO problematic_terms (term, category, notes) VALUES (?, ?, ?)",
                    SEED_PROBLEMATIC_TERMS,
                )
    finally:
        conn.close()


def list_entries(db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM entries ORDER BY LOWER(nom) ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_entry(entry_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_entry(data: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    now = _utc_now()
    user = (data.get("user") or data.get("created_by") or "").strip()
    nom = (data.get("nom") or "").strip()
    if not nom:
        raise ValueError("Le nom de famille est obligatoire.")

    fields = (
        nom,
        (data.get("prenom") or "").strip(),
        (data.get("choix1") or "").strip(),
        (data.get("police1") or "").strip(),
        (data.get("choix2") or "").strip(),
        (data.get("police2") or "").strip(),
        (data.get("choix3") or "").strip(),
        (data.get("police3") or "").strip(),
        user,
        user,
        now,
        now,
    )
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO entries (
                    nom, prenom, choix1, police1, choix2, police2, choix3, police3,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                fields,
            )
            row = conn.execute(
                "SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)
    finally:
        conn.close()


def update_entry(
    entry_id: int, data: dict[str, Any], db_path: Path | None = None
) -> dict[str, Any] | None:
    now = _utc_now()
    user = (data.get("user") or data.get("updated_by") or "").strip()
    nom = (data.get("nom") or "").strip()
    if not nom:
        raise ValueError("Le nom de famille est obligatoire.")

    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT * FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if not existing:
                return None
            conn.execute(
                """
                UPDATE entries
                SET nom = ?, prenom = ?,
                    choix1 = ?, police1 = ?,
                    choix2 = ?, police2 = ?,
                    choix3 = ?, police3 = ?,
                    updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    nom,
                    (data.get("prenom") or "").strip(),
                    (data.get("choix1") or "").strip(),
                    (data.get("police1") or "").strip(),
                    (data.get("choix2") or "").strip(),
                    (data.get("police2") or "").strip(),
                    (data.get("choix3") or "").strip(),
                    (data.get("police3") or "").strip(),
                    user or existing["updated_by"],
                    now,
                    entry_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            return dict(row)
    finally:
        conn.close()


def delete_entry(entry_id: int, db_path: Path | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            return cur.rowcount > 0
    finally:
        conn.close()


def get_known_fonts(db_path: Path | None = None) -> list[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT police1 AS p FROM entries WHERE TRIM(police1) != ''
            UNION
            SELECT police2 AS p FROM entries WHERE TRIM(police2) != ''
            UNION
            SELECT police3 AS p FROM entries WHERE TRIM(police3) != ''
            ORDER BY p ASC
            """
        ).fetchall()
        return [r["p"] for r in rows]
    finally:
        conn.close()


def get_overrides_map(db_path: Path | None = None) -> dict[tuple[int, int], dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM choice_overrides").fetchall()
        result: dict[tuple[int, int], dict[str, Any]] = {}
        for r in rows:
            try:
                ignored = json.loads(r["ignored_rules"] or "[]")
            except json.JSONDecodeError:
                ignored = []
            result[(r["entry_id"], r["choice_index"])] = {
                "entry_id": r["entry_id"],
                "choice_index": r["choice_index"],
                "is_problematic": int(r["is_problematic"] or 0),
                "problematic_reason": r["problematic_reason"] or "",
                "ignored_rules": [int(x) for x in ignored],
                "updated_by": r["updated_by"] or "",
                "updated_at": r["updated_at"],
            }
        return result
    finally:
        conn.close()


def save_override(
    entry_id: int,
    choice_index: int,
    is_problematic: int,
    problematic_reason: str,
    ignored_rules: list[int],
    user: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    if choice_index not in (1, 2, 3):
        raise ValueError("choice_index doit valoir 1, 2 ou 3.")
    now = _utc_now()
    cleaned_ignored = sorted({int(r) for r in ignored_rules if int(r) in (1, 2, 3, 4)})
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO choice_overrides (
                    entry_id, choice_index, is_problematic, problematic_reason,
                    ignored_rules, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id, choice_index) DO UPDATE SET
                    is_problematic = excluded.is_problematic,
                    problematic_reason = excluded.problematic_reason,
                    ignored_rules = excluded.ignored_rules,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    entry_id,
                    choice_index,
                    int(is_problematic),
                    (problematic_reason or "").strip(),
                    json.dumps(cleaned_ignored),
                    user.strip(),
                    now,
                ),
            )
            return {
                "entry_id": entry_id,
                "choice_index": choice_index,
                "is_problematic": int(is_problematic),
                "problematic_reason": (problematic_reason or "").strip(),
                "ignored_rules": cleaned_ignored,
                "updated_by": user.strip(),
                "updated_at": now,
            }
    finally:
        conn.close()


def get_settings(db_path: Path | None = None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        raw = {**DEFAULT_SETTINGS, **{r["key"]: r["value"] for r in rows}}
        return {
            "current_proms": int(raw["current_proms"]),
            "rule1_years": int(raw["rule1_years"]),
            "threshold_r12": float(raw["threshold_r12"]),
            "threshold_r3": float(raw["threshold_r3"]),
            "r3_scope": raw["r3_scope"] if raw["r3_scope"] in ("all", "choice1") else "all",
        }
    finally:
        conn.close()


def update_settings(updates: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    allowed = {
        "current_proms": lambda v: str(max(1, int(v))),
        "rule1_years": lambda v: str(max(1, min(100, int(v)))),
        "threshold_r12": lambda v: str(max(0.5, min(1.0, float(v)))),
        "threshold_r3": lambda v: str(max(0.5, min(1.0, float(v)))),
        "r3_scope": lambda v: "choice1" if str(v) == "choice1" else "all",
    }
    conn = get_connection(db_path)
    try:
        with conn:
            for k, validator in allowed.items():
                if k in updates and updates[k] is not None:
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (k, validator(updates[k])),
                    )
    finally:
        conn.close()
    return get_settings(db_path)


def list_problematic_terms(db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM problematic_terms ORDER BY LOWER(term) ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_problematic_term(
    term: str, category: str = "Personnalisé", notes: str = "", db_path: Path | None = None
) -> dict[str, Any]:
    cleaned = term.strip().lower()
    if not cleaned:
        raise ValueError("Le terme ne peut pas être vide.")
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO problematic_terms (term, category, notes) VALUES (?, ?, ?)",
                (cleaned, (category or "Personnalisé").strip(), (notes or "").strip()),
            )
            row = conn.execute(
                "SELECT * FROM problematic_terms WHERE term = ?", (cleaned,)
            ).fetchone()
            return dict(row)
    finally:
        conn.close()


def delete_problematic_term(term_id: int, db_path: Path | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM problematic_terms WHERE id = ?", (term_id,))
            return cur.rowcount > 0
    finally:
        conn.close()


def list_extra_bdd_records(db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM extra_bdd_records ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_extra_bdd_records(
    records: list[dict[str, Any]], db_path: Path | None = None
) -> int:
    if not records:
        return 0
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executemany(
                """
                INSERT INTO extra_bdd_records (
                    kind, buque, nom, prenom, fams, proms, annee, batch_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["kind"],
                        r["buque"],
                        r.get("nom", ""),
                        r.get("prenom", ""),
                        r.get("fams", ""),
                        r.get("proms"),
                        r.get("annee", ""),
                        r.get("batch_name", "Import manuel"),
                    )
                    for r in records
                ],
            )
        return len(records)
    finally:
        conn.close()


def delete_extra_bdd_batch(batch_name: str, db_path: Path | None = None) -> int:
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM extra_bdd_records WHERE batch_name = ?", (batch_name,)
            )
            return cur.rowcount
    finally:
        conn.close()

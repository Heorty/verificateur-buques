"""Serveur Starlette + WebSocket temps réel pour la saisie et la comparaison des buques."""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import mimetypes
from pathlib import Path
import socket
from typing import Any

mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import bdd_loader, comparator, database, exporter
from .phonetics import build_profile


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

_DB_LOCK = asyncio.Lock()
_BDD_INDEX: bdd_loader.BddIndex | None = None


def get_bdd() -> bdd_loader.BddIndex:
    global _BDD_INDEX
    if _BDD_INDEX is None:
        _BDD_INDEX = bdd_loader.load_bdd_index()
    return _BDD_INDEX


def reload_bdd() -> bdd_loader.BddIndex:
    global _BDD_INDEX
    _BDD_INDEX = bdd_loader.load_bdd_index()
    return _BDD_INDEX


def get_lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if addr and not addr.startswith("127.") and addr not in ips:
                ips.append(addr)
    except OSError:
        pass

    if not ips:
        ips.append("127.0.0.1")
    return ips


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[WebSocket, dict[str, Any]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections[ws] = {"user": "Anonyme", "editing": None}
        await self.broadcast_presence()

    def disconnect(self, ws: WebSocket) -> None:
        self.connections.pop(ws, None)

    async def handle_message(self, ws: WebSocket, data: dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "hello":
            user = str(data.get("user") or "Anonyme").strip()[:40] or "Anonyme"
            if ws in self.connections:
                self.connections[ws]["user"] = user
            await self.broadcast_presence()
        elif msg_type == "editing":
            if ws in self.connections:
                self.connections[ws]["editing"] = data.get("field")
            await self.broadcast_presence()

    def presence_payload(self) -> dict[str, Any]:
        users = [
            {
                "user": info["user"],
                "editing": info.get("editing"),
            }
            for info in self.connections.values()
        ]
        return {
            "type": "presence",
            "count": len(users),
            "users": users,
        }

    async def broadcast_presence(self) -> None:
        await self.broadcast(self.presence_payload())

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        payload = json.dumps(message, ensure_ascii=False)
        for ws in list(self.connections.keys()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.pop(ws, None)


MANAGER = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    await MANAGER.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    await MANAGER.handle_message(ws, data)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        MANAGER.disconnect(ws)
        await MANAGER.broadcast_presence()
    except Exception:
        MANAGER.disconnect(ws)
        await MANAGER.broadcast_presence()


async def index_page(request: Request) -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


async def api_network_info(request: Request) -> JSONResponse:
    port = request.url.port or 8000
    ips = get_lan_ips()
    urls = [f"http://{ip}:{port}" for ip in ips]
    return JSONResponse({"ips": ips, "port": port, "urls": urls})


async def api_list_entries(request: Request) -> JSONResponse:
    entries = database.list_entries()
    fonts = database.get_known_fonts()
    return JSONResponse({"entries": entries, "fonts": fonts})


async def api_create_entry(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    try:
        async with _DB_LOCK:
            created = database.create_entry(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await MANAGER.broadcast(
        {
            "type": "entries_changed",
            "action": "create",
            "entry_id": created["id"],
            "by": payload.get("user", ""),
        }
    )
    return JSONResponse({"entry": created}, status_code=201)


async def api_update_entry(request: Request) -> JSONResponse:
    entry_id = int(request.path_params["entry_id"])
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    try:
        async with _DB_LOCK:
            updated = database.update_entry(entry_id, payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not updated:
        return JSONResponse({"error": "Entrée introuvable."}, status_code=404)

    await MANAGER.broadcast(
        {
            "type": "entries_changed",
            "action": "update",
            "entry_id": entry_id,
            "by": payload.get("user", ""),
        }
    )
    return JSONResponse({"entry": updated})


async def api_delete_entry(request: Request) -> JSONResponse:
    entry_id = int(request.path_params["entry_id"])
    user = request.query_params.get("user", "")
    async with _DB_LOCK:
        ok = database.delete_entry(entry_id)
    if not ok:
        return JSONResponse({"error": "Entrée introuvable."}, status_code=404)

    await MANAGER.broadcast(
        {
            "type": "entries_changed",
            "action": "delete",
            "entry_id": entry_id,
            "by": user,
        }
    )
    return JSONResponse({"ok": True})


async def api_import_entries(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    csv_text = payload.get("csv_text", "")
    user = str(payload.get("user", "Import CSV"))
    if not csv_text.strip():
        return JSONResponse({"error": "Fichier CSV vide."}, status_code=400)

    # Détection auto du séparateur (, ou ;)
    sample = csv_text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return JSONResponse({"error": "Aucune ligne détectée."}, status_code=400)

    header = [c.strip().lower() for c in rows[0]]
    has_header = any("nom" in h or "choix" in h for h in header)
    start_idx = 1 if has_header else 0

    def _find_col(keywords: tuple[str, ...], default: int | None) -> int | None:
        if not has_header:
            return default
        for i, h in enumerate(header):
            if any(kw in h for kw in keywords):
                return i
        return default

    c_nom = _find_col(("nom",), 0)
    c_prenom = _find_col(("prénom", "prenom"), None)
    c_ch1 = _find_col(("choix 1", "choix1", "buque 1"), 1)
    c_p1 = _find_col(("police 1", "police1"), None)
    c_ch2 = _find_col(("choix 2", "choix2", "buque 2"), 2)
    c_p2 = _find_col(("police 2", "police2"), None)
    c_ch3 = _find_col(("choix 3", "choix3", "buque 3"), 3)
    c_p3 = _find_col(("police 3", "police3"), None)

    imported = 0
    async with _DB_LOCK:
        for row in rows[start_idx:]:
            nom = row[c_nom].strip() if c_nom is not None and c_nom < len(row) else ""
            if not nom:
                continue
            database.create_entry(
                {
                    "nom": nom,
                    "prenom": row[c_prenom].strip() if c_prenom is not None and c_prenom < len(row) else "",
                    "choix1": row[c_ch1].strip() if c_ch1 is not None and c_ch1 < len(row) else "",
                    "police1": row[c_p1].strip() if c_p1 is not None and c_p1 < len(row) else "",
                    "choix2": row[c_ch2].strip() if c_ch2 is not None and c_ch2 < len(row) else "",
                    "police2": row[c_p2].strip() if c_p2 is not None and c_p2 < len(row) else "",
                    "choix3": row[c_ch3].strip() if c_ch3 is not None and c_ch3 < len(row) else "",
                    "police3": row[c_p3].strip() if c_p3 is not None and c_p3 < len(row) else "",
                    "user": user,
                }
            )
            imported += 1

    await MANAGER.broadcast(
        {"type": "entries_changed", "action": "bulk_import", "by": user}
    )
    return JSONResponse({"imported": imported})


def _get_effective_settings(request: Request) -> dict[str, Any]:
    settings = database.get_settings()
    qp = request.query_params
    if "threshold_r12" in qp:
        try:
            settings["threshold_r12"] = max(0.5, min(1.0, float(qp["threshold_r12"])))
        except ValueError:
            pass
    if "threshold_r3" in qp:
        try:
            settings["threshold_r3"] = max(0.5, min(1.0, float(qp["threshold_r3"])))
        except ValueError:
            pass
    if "r3_scope" in qp and qp["r3_scope"] in ("all", "choice1"):
        settings["r3_scope"] = qp["r3_scope"]
    return settings


async def api_compare(request: Request) -> JSONResponse:
    settings = _get_effective_settings(request)
    entries = database.list_entries()
    overrides = database.get_overrides_map()
    terms = database.list_problematic_terms()
    result = comparator.evaluate_all(entries, get_bdd(), settings, overrides, terms)
    return JSONResponse(result)


async def api_test_buque(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    buque = str(payload.get("buque") or "")
    preview_only = bool(payload.get("preview_only", False))
    if preview_only:
        prof = build_profile(buque)
        return JSONResponse({"phonetic": prof.to_dict()})

    settings = database.get_settings()
    entries = database.list_entries()
    terms = database.list_problematic_terms()
    result = comparator.evaluate_single_buque(buque, entries, get_bdd(), settings, terms)
    return JSONResponse(result)


async def api_save_override(request: Request) -> JSONResponse:
    entry_id = int(request.path_params["entry_id"])
    choice_index = int(request.path_params["choice_index"])
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    try:
        async with _DB_LOCK:
            entry = database.get_entry(entry_id)
            if not entry:
                return JSONResponse({"error": "Entrée introuvable."}, status_code=404)
            saved = database.save_override(
                entry_id=entry_id,
                choice_index=choice_index,
                is_problematic=int(payload.get("is_problematic", 0)),
                problematic_reason=str(payload.get("problematic_reason", "")),
                ignored_rules=list(payload.get("ignored_rules", [])),
                user=str(payload.get("user", "")),
            )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await MANAGER.broadcast(
        {"type": "entries_changed", "action": "override", "entry_id": entry_id}
    )
    return JSONResponse({"override": saved})


async def api_get_settings(request: Request) -> JSONResponse:
    return JSONResponse({"settings": database.get_settings()})


async def api_update_settings(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    async with _DB_LOCK:
        updated = database.update_settings(payload)
    await MANAGER.broadcast({"type": "settings_changed"})
    return JSONResponse({"settings": updated})


async def api_list_problematic_terms(request: Request) -> JSONResponse:
    return JSONResponse({"terms": database.list_problematic_terms()})


async def api_add_problematic_term(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    try:
        async with _DB_LOCK:
            created = database.add_problematic_term(
                term=str(payload.get("term", "")),
                category=str(payload.get("category", "Personnalisé")),
                notes=str(payload.get("notes", "")),
            )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await MANAGER.broadcast({"type": "settings_changed"})
    return JSONResponse({"term": created}, status_code=201)


async def api_delete_problematic_term(request: Request) -> JSONResponse:
    term_id = int(request.path_params["term_id"])
    async with _DB_LOCK:
        ok = database.delete_problematic_term(term_id)
    if not ok:
        return JSONResponse({"error": "Terme introuvable."}, status_code=404)
    await MANAGER.broadcast({"type": "settings_changed"})
    return JSONResponse({"ok": True})


async def api_bdd_status(request: Request) -> JSONResponse:
    settings = database.get_settings()
    stats = get_bdd().get_stats(
        current_proms=settings["current_proms"],
        rule1_years=settings["rule1_years"],
    )
    return JSONResponse(stats)


async def api_bdd_search(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "")
    kind = request.query_params.get("kind", "all")
    results = get_bdd().search(q, kind=kind, limit=80)
    return JSONResponse({"results": results})


async def api_bdd_import(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalide."}, status_code=400)

    mode = str(payload.get("mode") or payload.get("kind") or "auto").lower()
    if mode not in ("auto", "pg", "ct"):
        return JSONResponse({"error": "mode doit valoir 'auto', 'pg' ou 'ct'."}, status_code=400)

    filename = str(payload.get("filename") or "import.csv").strip()
    content_b64 = payload.get("content_b64")
    if content_b64:
        try:
            file_bytes = base64.b64decode(content_b64)
        except Exception:
            return JSONResponse({"error": "Contenu base64 invalide."}, status_code=400)
    else:
        csv_text = str(payload.get("csv_text", ""))
        file_bytes = csv_text.encode("utf-8")

    proms_raw = payload.get("proms")
    proms_int = int(proms_raw) if proms_raw not in (None, "") else None
    batch_name = str(payload.get("batch_name") or filename or "Import manuel").strip()

    try:
        records = bdd_loader.parse_unified_table(
            file_bytes=file_bytes,
            filename=filename,
            force_mode=mode,
            default_proms=proms_int,
            batch_name=batch_name,
        )
        async with _DB_LOCK:
            count = database.add_extra_bdd_records(records)
            reload_bdd()
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await MANAGER.broadcast({"type": "bdd_changed"})
    return JSONResponse({"imported": count, "batch_name": batch_name})


async def api_bdd_template_xlsx(request: Request) -> Response:
    xlsx_bytes = bdd_loader.generate_bdd_template_xlsx()
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="modele_bdd_buques.xlsx"'},
    )


async def api_bdd_delete_batch(request: Request) -> JSONResponse:
    batch_name = request.path_params["batch_name"]
    async with _DB_LOCK:
        deleted = database.delete_extra_bdd_batch(batch_name)
        reload_bdd()
    if deleted == 0:
        return JSONResponse({"error": "Lot introuvable."}, status_code=404)
    await MANAGER.broadcast({"type": "bdd_changed"})
    return JSONResponse({"deleted": deleted})


async def api_export_xlsx(request: Request) -> Response:
    settings = _get_effective_settings(request)
    entries = database.list_entries()
    overrides = database.get_overrides_map()
    terms = database.list_problematic_terms()
    comparison = comparator.evaluate_all(entries, get_bdd(), settings, overrides, terms)
    xlsx_bytes = exporter.export_xlsx(comparison)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tableau_buques.xlsx"'},
    )


async def api_export_csv(request: Request) -> Response:
    settings = _get_effective_settings(request)
    entries = database.list_entries()
    overrides = database.get_overrides_map()
    terms = database.list_problematic_terms()
    comparison = comparator.evaluate_all(entries, get_bdd(), settings, overrides, terms)
    csv_bytes = exporter.export_csv(comparison)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tableau_buques.csv"'},
    )


def on_startup() -> None:
    database.init_db()
    reload_bdd()


routes = [
    Route("/", index_page, methods=["GET"]),
    WebSocketRoute("/ws", websocket_endpoint),
    Route("/api/network-info", api_network_info, methods=["GET"]),
    Route("/api/entries", api_list_entries, methods=["GET"]),
    Route("/api/entries", api_create_entry, methods=["POST"]),
    Route("/api/entries/import", api_import_entries, methods=["POST"]),
    Route("/api/entries/{entry_id:int}", api_update_entry, methods=["PUT"]),
    Route("/api/entries/{entry_id:int}", api_delete_entry, methods=["DELETE"]),
    Route("/api/compare", api_compare, methods=["GET"]),
    Route("/api/test-buque", api_test_buque, methods=["POST"]),
    Route("/api/overrides/{entry_id:int}/{choice_index:int}", api_save_override, methods=["PUT"]),
    Route("/api/settings", api_get_settings, methods=["GET"]),
    Route("/api/settings", api_update_settings, methods=["PUT"]),
    Route("/api/problematic-terms", api_list_problematic_terms, methods=["GET"]),
    Route("/api/problematic-terms", api_add_problematic_term, methods=["POST"]),
    Route("/api/problematic-terms/{term_id:int}", api_delete_problematic_term, methods=["DELETE"]),
    Route("/api/bdd/status", api_bdd_status, methods=["GET"]),
    Route("/api/bdd/search", api_bdd_search, methods=["GET"]),
    Route("/api/bdd/import", api_bdd_import, methods=["POST"]),
    Route("/api/bdd/template.xlsx", api_bdd_template_xlsx, methods=["GET"]),
    Route("/api/bdd/batch/{batch_name:str}", api_bdd_delete_batch, methods=["DELETE"]),
    Route("/api/export/xlsx", api_export_xlsx, methods=["GET"]),
    Route("/api/export/csv", api_export_csv, methods=["GET"]),
    Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
]


def create_app() -> Starlette:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    return Starlette(routes=routes, on_startup=[on_startup])


app = create_app()

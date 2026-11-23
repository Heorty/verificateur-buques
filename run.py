"""Point d'entrée CLI pour lancer le Vérificateur de Buques sur le réseau local."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import uvicorn

from app.server import get_lan_ips


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vérificateur de Buques — Clun'ss (Arts & Métiers)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Adresse d'écoute (défaut: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port HTTP/WS (défaut: 8000)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne pas ouvrir automatiquement le navigateur au démarrage",
    )
    args = parser.parse_args()

    lan_ips = get_lan_ips()
    local_url = f"http://127.0.0.1:{args.port}"
    print("=" * 64)
    print("  VÉRIFICATEUR DE BUQUES — CLUN'SS (ARTS & MÉTIERS)")
    print("=" * 64)
    print(f"  Accès local (cet ordinateur) : {local_url}")
    for ip in lan_ips:
        print(f"  Accès Wi-Fi / réseau local   : http://{ip}:{args.port}")
    print("  Partagez l'adresse Wi-Fi pour la saisie simultanée !")
    print("=" * 64)

    if not args.no_browser:
        def _open_browser() -> None:
            time.sleep(1.0)
            webbrowser.open(local_url)

        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "app.server:app",
        host=args.host,
        port=args.port,
        ws="wsproto",
        log_level="info",
    )


if __name__ == "__main__":
    main()

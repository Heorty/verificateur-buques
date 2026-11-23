"""Suite de tests automatisés pour le Vérificateur de Buques."""

from __future__ import annotations

import base64
import html.parser
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from openpyxl import Workbook, load_workbook
import requests
import uvicorn
import websocket

from app import bdd_loader, comparator, database, exporter, phonetics, server


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestPhonetics(unittest.TestCase):
    def test_transpose_notations(self):
        for expr, target in [
            ("(toto)^T", "otot"),
            ("(toto)ᵀ", "otot"),
            ("ᵀ(mot)", "tom"),
            ("ᵗ(mot)", "tom"),
            ("(mot)⊤", "tom"),
            ("(mot)ᵗ", "tom"),
            ("(mot)**T", "tom"),
            ("(Arts)**T zowski", "strazowski"),
            ("GO^t(ARTS)", "ogarts"),
            ("Wyst(Arts)^T", "wyststra"),
            ("Wyst(Arts)ᵀ", "wyststra"),
        ]:
            p1 = phonetics.build_profile(expr)
            p2 = phonetics.build_profile(target)
            matched, best, _, _ = phonetics.is_match(p1, p2, 0.90, mode="r12")
            self.assertTrue(
                matched and best >= 0.95,
                f"{expr} devrait correspondre à {target} (reçu {p1.expanded_readings}, score={best})",
            )

    def test_entry_tab_order_and_transpose_char_ui(self):
        html_path = Path(__file__).resolve().parent.parent / "static" / "index.html"
        content = html_path.read_text(encoding="utf-8")

        class _FormParser(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_entry_form = False
                self.tabbable_inputs = []
                self.sym_btns = []

            def handle_starttag(self, tag, attrs):
                d = dict(attrs)
                if tag == "form" and d.get("id") == "entry-form":
                    self.in_entry_form = True
                elif self.in_entry_form and tag == "input" and d.get("tabindex") != "-1":
                    self.tabbable_inputs.append(d.get("id"))
                if tag == "button" and "sym-btn" in (d.get("class") or "").split():
                    self.sym_btns.append(d)

            def handle_endtag(self, tag):
                if tag == "form" and self.in_entry_form:
                    self.in_entry_form = False

        parser = _FormParser()
        parser.feed(content)
        self.assertEqual(
            parser.tabbable_inputs,
            [
                "input-nom",
                "input-choix1",
                "input-choix2",
                "input-choix3",
                "input-police1",
                "input-police2",
                "input-police3",
            ],
        )
        self.assertTrue(all(b.get("tabindex") == "-1" for b in parser.sym_btns))
        inserts = [b.get("data-insert") for b in parser.sym_btns]
        self.assertIn("ᵀ", inserts)
        self.assertNotIn("^T", inserts)

    def test_square_double_and_karse_readings(self):
        # 1) Mot entier avant ² lu 2 fois + règle des parenthèses
        repeat_cases = [
            ("Bip²", "BipBip"),
            ("Piou²ouaich²", "PiouPiououaichouaich"),
            ("Mou²", "MouMou"),
            ("π²", "Pipi"),
            ("(BUG)²", "Bugbug"),
            ("Paga(ni)²", "Paganini"),
            ("super(mot)²", "supermotmot"),
            ("(J(arts))²", "JarJar"),
            ("((mot)²)ᵀ", "tomtom"),
        ]
        for expr, target in repeat_cases:
            p1 = phonetics.build_profile(expr)
            p2 = phonetics.build_profile(target)
            matched, best, _, _ = phonetics.is_match(p1, p2, 0.95, mode="r12")
            self.assertTrue(
                matched and best == 1.0,
                f"{expr} devrait aussi se lire {target} (reçu {p1.expanded_readings}, score={best})",
            )

        # 2) Lecture « karse » avec ou sans parenthèses
        karse_cases = [
            ("Mou²", "Moukarse"),
            ("Mou²", "Moukars"),
            ("(Mou)²", "Moukars"),
            ("Ba²", "Bacars"),
            ("Bip²", "Bipkarse"),
            ("(BUG)²", "Bugkarse"),
            ("π²", "Picarse"),
            ("π²", "Pikars"),
        ]
        for expr, target in karse_cases:
            p1 = phonetics.build_profile(expr)
            p2 = phonetics.build_profile(target)
            matched, best, _, _ = phonetics.is_match(p1, p2, 0.95, mode="r12")
            self.assertTrue(
                matched and best == 1.0,
                f"{expr} devrait aussi se lire {target} (reçu {p1.expanded_readings}, score={best})",
            )

        # AL2ISON sans ^ ni ² ne doit pas être développé
        p_al = phonetics.build_profile("AL2ISON")
        self.assertEqual(p_al.expanded_readings, ("AL2ISON",))

    def test_normal_t_not_reversed(self):
        p_artiphis = phonetics.build_profile("(Arts)tiphi's")
        self.assertIn("artiphis", p_artiphis.visual_readings)
        self.assertFalse(any("stra" in r.lower() for r in p_artiphis.expanded_readings))

        p_clarte = phonetics.build_profile("Cl(Arts)té")
        self.assertIn("clarté", [r.lower() for r in p_clarte.expanded_readings])
        self.assertFalse(any("stra" in r.lower() for r in p_clarte.expanded_readings))

    def test_power_zero_dropped(self):
        for expr, target in [
            ("Super(test)^0", "Super"),
            ("(inutile)⁰Astucieux", "Astucieux"),
            ("Bon(jour)^0soir", "Bonsoir"),
        ]:
            p1 = phonetics.build_profile(expr)
            p2 = phonetics.build_profile(target)
            matched, best, _, _ = phonetics.is_match(p1, p2, 0.95, mode="r12")
            self.assertTrue(matched and best == 1.0, f"{expr} != {target} ({p1.expanded_readings})")

    def test_visual_parentheses_and_real_bdd_cases(self):
        pairs = [
            ("pompl(arts)", "pomplart", 1.0),
            ("pompl(arts)", "pomplard", 1.0),
            ("pompl(arts)", "pomplar", 1.0),
            ("Bas(art)", "Bazar", 1.0),
            ("πRHANA", "Piranha", 1.0),
            ("L∞πng", "Looping", 1.0),
            ("Asph(H2O)dèle", "Asphodèle", 1.0),
            ("(BUG)²", "Bugbug", 1.0),
            ("KratΩs", "Cratos", 1.0),
            ("Calypso", "Kalipso", 1.0),
        ]
        for a, b, min_score in pairs:
            pa = phonetics.build_profile(a)
            pb = phonetics.build_profile(b)
            matched, best, ortho, phon = phonetics.is_match(pa, pb, 0.85, mode="r12")
            self.assertTrue(
                matched and best >= min_score,
                f"Échec sur {a} vs {b} -> best={best} (ortho={ortho}, phon={phon}, {pa.phonetic_readings} vs {pb.phonetic_readings})",
            )

    def test_short_string_false_positive_guard(self):
        for a, b in [("Bob", "Rob"), ("Sam", "Tam")]:
            pa = phonetics.build_profile(a)
            pb = phonetics.build_profile(b)
            matched_r12, _, _, _ = phonetics.is_match(pa, pb, 0.85, mode="r12")
            matched_r3, _, _, _ = phonetics.is_match(pa, pb, 0.75, mode="r3")
            self.assertFalse(matched_r12, f"{a} et {b} ne doivent pas matcher en R1/R2")
            self.assertFalse(matched_r3, f"{a} et {b} ne doivent pas matcher en R3")


class TestBddLoader(unittest.TestCase):
    def test_unified_table_parser_and_missing_default_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            dbp = tmp_dir / "test_empty.db"
            database.init_db(dbp)

            # 1) Démarrage propre même si le fichier par défaut n'existe pas (ex: clone GitHub)
            empty_idx = bdd_loader.load_bdd_index(
                bdd_file=tmp_dir / "inexistant.xlsx", db_path=dbp
            )
            self.assertFalse(empty_idx.default_file_loaded)
            self.assertEqual(len(empty_idx.pg_records), 0)
            self.assertEqual(len(empty_idx.ct_records), 0)

            # 2) Fichier Excel unifié avec colonnes Buque, Année d'entrée / Prom'ss, CT
            wb = Workbook()
            ws = wb.active
            ws.append(["Buque", "Année d'entrée / Prom'ss", "CT", "Nom", "Fam's"])
            ws.append(["Zylphoria", 2025, "Faux", "Durand", "12"])
            ws.append(["MaitreTrad", "Cl224", "Vrai", "Martin", "45"])
            ws.append(["AncienSage", 1998, "Oui", "", ""])
            ws.append(["SansCT", "2024-2025", "Non", "Petit", ""])
            xlsx_path = tmp_dir / "custom.xlsx"
            wb.save(xlsx_path)

            idx = bdd_loader.load_bdd_index(bdd_file=xlsx_path, db_path=dbp)
            self.assertTrue(idx.default_file_loaded)
            self.assertEqual(len(idx.pg_records), 4)
            self.assertEqual(len(idx.ct_records), 2)
            self.assertEqual({r.buque for r in idx.ct_records}, {"MaitreTrad", "AncienSage"})
            proms_by_buque = {r.buque: r.proms for r in idx.pg_records}
            self.assertEqual(proms_by_buque["Zylphoria"], 225)
            self.assertEqual(proms_by_buque["MaitreTrad"], 224)
            self.assertEqual(proms_by_buque["AncienSage"], 198)
            self.assertEqual(proms_by_buque["SansCT"], 224)

            # 3) Fichier CSV point-virgule
            csv_bytes = "Buque;Prom'ss;CT\nCsvTest;225;0\nCsvCT;2000;1\n".encode("utf-8")
            parsed_csv = bdd_loader.parse_unified_table(csv_bytes, "custom.csv")
            self.assertEqual(len(parsed_csv), 2)
            self.assertFalse(parsed_csv[0]["is_ct"])
            self.assertTrue(parsed_csv[1]["is_ct"])
            self.assertEqual(parsed_csv[1]["proms"], 200)

    @unittest.skipUnless(
        bdd_loader.DEFAULT_BDD_FILE.exists(),
        "bdd/Liste_PGs_Clun_ssois.xlsx absent sur ce clone",
    )
    def test_load_default_unified_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbp = Path(tmp) / "test.db"
            database.init_db(dbp)
            idx = bdd_loader.load_bdd_index(db_path=dbp)

        self.assertTrue(idx.default_file_loaded)
        self.assertEqual(idx.default_file_name, "Liste_PGs_Clun_ssois.xlsx")
        self.assertGreater(len(idx.pg_records), 9500)
        cl225 = [r for r in idx.pg_records if r.proms == 225]
        self.assertGreater(len(cl225), 150)
        self.assertGreater(len(idx.ct_records), 350)

        # Vérifier qu'il n'y a aucun doublon (visual_clean, proms) dans Liste_PGs_Clun_ssois.xlsx
        wb = load_workbook(bdd_loader.DEFAULT_BDD_FILE, read_only=True, data_only=True)
        ws = wb.active
        seen_keys = set()
        for row in list(ws.iter_rows(values_only=True))[1:]:
            buque = str(row[0] or "").strip()
            proms = row[1]
            annee = str(row[2] or "").strip()
            vis = phonetics.normalize_visual(buque)
            key = (vis, proms, annee if not proms else "")
            self.assertNotIn(key, seen_keys, f"Doublon détecté dans le xlsx unifié : {row}")
            seen_keys.add(key)
        wb.close()

        ct_names = {r.buque for r in idx.ct_records}
        ct_phonetics = {ph for r in idx.ct_records for ph in r.profile.phonetic_readings}
        for expected in [
            "Aspy",
            "Banco",
            "Citroën",
            "Bazar",
            "Wakand(arts)",
            "Rapido",
            "Calypso",
            "Moust(arts)Ki",
            "killy",
            "Steff",
            "Moukars",
        ]:
            exp_ph = phonetics.build_profile(expected).primary_phonetic
            self.assertIn(exp_ph, ct_phonetics, f"CT manquant : {expected}")

        for junk in ["?", "DEMISSIONNAIRE", "Cl225", "An'ss", "119👑34", "------"]:
            self.assertNotIn(junk, ct_names, f"Parasite CT détecté : {junk}")


class TestComparatorAndExporter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_cmp.db"
        database.init_db(self.db_path)
        self.bdd = bdd_loader.load_bdd_index(db_path=self.db_path)
        self.settings = database.get_settings(self.db_path)
        self.terms = database.list_problematic_terms(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_rules_precedence_and_colors(self):
        # Dupont : Pomplart (R1 vs Pompl(Arts) de CL225 -> Rouge),
        #          Pastaga (R2 CT 2002 -> Violet),
        #          Zylphorik (R3 vs Durand Zylphorix -> Jaune)
        e1 = database.create_entry(
            {
                "nom": "Dupont",
                "prenom": "Jean",
                "choix1": "Pomplart",
                "police1": "Garamond",
                "choix2": "Pastaga",
                "police2": "Impact",
                "choix3": "Zylphorik",
                "police3": "Futura",
                "user": "Test",
            },
            self.db_path,
        )
        # Durand : Rapido (CL225 + CT -> Violet prioritaire avec R1+R2 actifs),
        #          Zylphorix (R3 avec Dupont, mais pas ses propres choix),
        #          ValkyrionZ (Vert)
        e2 = database.create_entry(
            {
                "nom": "Durand",
                "prenom": "Marc",
                "choix1": "Rapido",
                "police1": "Arial",
                "choix2": "Zylphorix",
                "police2": "Helvetica",
                "choix3": "ValkyrionZ",
                "police3": "Clarendon",
                "user": "Test",
            },
            self.db_path,
        )
        # Martin : Hitler (R4 auto -> Orange), Xalathor (Vert), testeur (flag manuel R4)
        e3 = database.create_entry(
            {
                "nom": "Martin",
                "choix1": "Hitler",
                "choix2": "Xalathor",
                "choix3": "Zorglubz",
                "user": "Test",
            },
            self.db_path,
        )
        # Meme etudiant avec deux choix identiques ne doit pas se déclencher R3 sur lui-même
        e4 = database.create_entry(
            {
                "nom": "Bernard",
                "choix1": "Qwertyzop",
                "choix2": "Qwertyzop",
                "choix3": "Kratos",
                "user": "Test",
            },
            self.db_path,
        )
        database.save_override(e3["id"], 3, 1, "Référence interne douteuse", [], "Test", self.db_path)

        entries = database.list_entries(self.db_path)
        overrides = database.get_overrides_map(self.db_path)
        res = comparator.evaluate_all(entries, self.bdd, self.settings, overrides, self.terms)
        by_id = {r["id"]: r for r in res["rows"]}

        # Dupont
        self.assertEqual(by_id[e1["id"]]["choices"][0]["color"], "rouge")
        self.assertEqual(by_id[e1["id"]]["choices"][1]["color"], "violet")
        self.assertEqual(by_id[e1["id"]]["choices"][2]["color"], "jaune")

        # Durand : Rapido est CT récent (R1 + R2 -> Violet prioritaire)
        rapido_ch = by_id[e2["id"]]["choices"][0]
        self.assertEqual(rapido_ch["color"], "violet")
        self.assertIn(1, rapido_ch["active_rules"])
        self.assertIn(2, rapido_ch["active_rules"])
        self.assertEqual(by_id[e2["id"]]["choices"][1]["color"], "jaune")
        self.assertEqual(by_id[e2["id"]]["choices"][2]["color"], "vert")

        # Martin : Orange auto & manuel
        self.assertEqual(by_id[e3["id"]]["choices"][0]["color"], "orange")
        self.assertEqual(by_id[e3["id"]]["choices"][1]["color"], "vert")
        self.assertEqual(by_id[e3["id"]]["choices"][2]["color"], "orange")

        # Bernard : auto-comparaison ignorée pour R3
        self.assertNotIn(3, by_id[e4["id"]]["choices"][0]["active_rules"])
        self.assertEqual(by_id[e4["id"]]["choices"][0]["color"], "vert")

        # Export Excel coloré
        xlsx_bytes = exporter.export_xlsx(res)
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        self.assertIn("Tableau 4 colonnes", wb.sheetnames)
        self.assertIn("Détails & Polices", wb.sheetnames)
        ws1 = wb["Tableau 4 colonnes"]
        self.assertEqual(
            [ws1.cell(3, c).value for c in range(1, 5)],
            ["Nom de famille", "Choix 1", "Choix 2", "Choix 3"],
        )

        row_by_nom = {}
        for r in range(4, ws1.max_row + 1):
            row_by_nom[ws1.cell(r, 1).value] = r

        r_dupont = row_by_nom["Dupont (Jean)"]
        self.assertEqual(ws1.cell(r_dupont, 2).fill.start_color.rgb[-6:], "FFC7CE")  # Rouge
        self.assertEqual(ws1.cell(r_dupont, 3).fill.start_color.rgb[-6:], "E4C1F9")  # Violet
        self.assertEqual(ws1.cell(r_dupont, 4).fill.start_color.rgb[-6:], "FFEB9C")  # Jaune
        self.assertIsNotNone(ws1.cell(r_dupont, 2).comment)

        r_durand = row_by_nom["Durand (Marc)"]
        self.assertEqual(ws1.cell(r_durand, 4).fill.start_color.rgb[-6:], "C6EFCE")  # Vert

        r_martin = row_by_nom["Martin"]
        self.assertEqual(ws1.cell(r_martin, 2).fill.start_color.rgb[-6:], "FFD8A8")  # Orange

        # Vérification des règles avec lecture « karse » sur ²
        res_mou2 = comparator.evaluate_single_buque("Mou²", entries, self.bdd, self.settings, self.terms)
        self.assertEqual(res_mou2["color"], "violet")  # Match CT Cl222 Moukars
        res_ba2 = comparator.evaluate_single_buque("Ba²", entries, self.bdd, self.settings, self.terms)
        self.assertEqual(res_ba2["color"], "rouge")  # Match CL225 Bacars

    def test_performance_180_students(self):
        pool = [r.buque for r in self.bdd.pg_records if r.proms and 195 <= r.proms <= 205][:540]
        for i in range(180):
            database.create_entry(
                {
                    "nom": f"Etudiant_{i:03d}",
                    "choix1": pool[3 * i],
                    "choix2": pool[3 * i + 1],
                    "choix3": "Pompl(arts)" if i == 0 else pool[3 * i + 2],
                    "user": "Bench",
                },
                self.db_path,
            )
        entries = database.list_entries(self.db_path)
        overrides = database.get_overrides_map(self.db_path)

        t0 = time.perf_counter()
        res = comparator.evaluate_all(entries, self.bdd, self.settings, overrides, self.terms)
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(res["rows"]), 180)
        self.assertLess(elapsed, 2.0, f"Évaluation trop lente : {elapsed:.2f}s")


class TestEndToEndServerAndWebSocket(unittest.TestCase):
    def test_live_http_and_multiuser_ws(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("BUQUES_DB_PATH")
            os.environ["BUQUES_DB_PATH"] = str(Path(tmp) / "e2e.db")
            try:
                port = _find_free_port()
                config = uvicorn.Config(
                    server.app,
                    host="127.0.0.1",
                    port=port,
                    ws="wsproto",
                    log_level="error",
                )
                srv = uvicorn.Server(config)
                thread = threading.Thread(target=srv.run, daemon=True)
                thread.start()

                base = f"http://127.0.0.1:{port}"
                # Attendre que le serveur réponde
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    try:
                        r = requests.get(base + "/", timeout=0.5)
                        if r.status_code == 200:
                            break
                    except requests.RequestException:
                        time.sleep(0.1)
                else:
                    self.fail("Le serveur Uvicorn n'a pas démarré à temps.")

                # Vérifier l'accueil HTML
                r_home = requests.get(base + "/", timeout=2)
                self.assertEqual(r_home.status_code, 200)
                self.assertIn("Vérificateur de Buques", r_home.text)

                # Connecter 2 clients WebSocket simultanés
                ws_url = f"ws://127.0.0.1:{port}/ws"
                ws_alice = websocket.create_connection(ws_url, timeout=3)
                ws_bob = websocket.create_connection(ws_url, timeout=3)
                try:
                    ws_alice.send(json.dumps({"type": "hello", "user": "Alice"}))
                    ws_bob.send(json.dumps({"type": "hello", "user": "Bob"}))

                    # Lire jusqu'à voir Alice et Bob dans presence
                    seen_both = False
                    for _ in range(10):
                        msg = json.loads(ws_bob.recv())
                        if msg.get("type") == "presence":
                            names = {u["user"] for u in msg.get("users", [])}
                            if {"Alice", "Bob"}.issubset(names):
                                seen_both = True
                                break
                    self.assertTrue(seen_both, "La présence multi-utilisateurs n'a pas convergé.")

                    # Alice crée une feuille via API REST -> Bob reçoit entries_changed en WS
                    r_post = requests.post(
                        base + "/api/entries",
                        json={
                            "nom": "TestWS",
                            "choix1": "Pompl(arts)",
                            "police1": "Garamond",
                            "choix2": "Rapido",
                            "police2": "Arial",
                            "choix3": "Xylophia",
                            "police3": "Futura",
                            "user": "Alice",
                        },
                        timeout=3,
                    )
                    self.assertEqual(r_post.status_code, 201)

                    got_sync = False
                    for _ in range(8):
                        msg = json.loads(ws_bob.recv())
                        if msg.get("type") == "entries_changed" and msg.get("by") == "Alice":
                            got_sync = True
                            break
                    self.assertTrue(got_sync, "Bob n'a pas reçu la mise à jour temps réel WebSocket.")

                    # Comparaison, Testeur & Exports
                    r_cmp = requests.get(base + "/api/compare", timeout=5)
                    self.assertEqual(r_cmp.status_code, 200)
                    cmp_data = r_cmp.json()
                    self.assertEqual(cmp_data["summary"]["total_students"], 1)

                    r_test = requests.post(
                        base + "/api/test-buque",
                        json={"buque": "Bas(art)"},
                        timeout=3,
                    )
                    self.assertEqual(r_test.status_code, 200)
                    self.assertEqual(r_test.json()["color"], "violet")

                    r_xlsx = requests.get(base + "/api/export/xlsx", timeout=5)
                    self.assertEqual(r_xlsx.status_code, 200)
                    self.assertTrue(r_xlsx.content.startswith(b"PK"))

                    r_csv = requests.get(base + "/api/export/csv", timeout=5)
                    self.assertEqual(r_csv.status_code, 200)
                    self.assertIn("TestWS", r_csv.text)

                    # Modèle Excel & import unifié .xlsx (base64)
                    r_tpl = requests.get(base + "/api/bdd/template.xlsx", timeout=5)
                    self.assertEqual(r_tpl.status_code, 200)
                    self.assertTrue(r_tpl.content.startswith(b"PK"))

                    wb_up = Workbook()
                    ws_up = wb_up.active
                    ws_up.append(["Buque", "Année d'entrée / Prom'ss", "CT"])
                    ws_up.append(["UploadTestUnique", 2024, "Vrai"])
                    buf_up = io.BytesIO()
                    wb_up.save(buf_up)
                    r_imp = requests.post(
                        base + "/api/bdd/import",
                        json={
                            "filename": "lot_test.xlsx",
                            "mode": "auto",
                            "batch_name": "LotTestE2E",
                            "content_b64": base64.b64encode(buf_up.getvalue()).decode("ascii"),
                        },
                        timeout=5,
                    )
                    self.assertEqual(r_imp.status_code, 200)
                    self.assertEqual(r_imp.json()["imported"], 1)

                    r_check = requests.post(
                        base + "/api/test-buque",
                        json={"buque": "UploadTestUnique"},
                        timeout=3,
                    )
                    self.assertEqual(r_check.status_code, 200)
                    self.assertEqual(r_check.json()["color"], "violet")
                finally:
                    ws_alice.close()
                    ws_bob.close()
                    srv.should_exit = True
                    thread.join(timeout=3)
            finally:
                if old_env is None:
                    os.environ.pop("BUQUES_DB_PATH", None)
                else:
                    os.environ["BUQUES_DB_PATH"] = old_env


if __name__ == "__main__":
    unittest.main()

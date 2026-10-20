import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.security import hash_password, valid_hash, verify_password
os.environ["OPPES_ADMIN_PASSWORD_HASH"] = hash_password("tests-only-password-123!")
os.environ["OPPES_SESSION_SECRET"] = "tests-only-session-secret-0123456789abcdef0123456789"

from fastapi.testclient import TestClient
import webapp.main as web
import webapp.services as services
from src.engine.execution_history import ExecutionHistory
from webapp.services import OperationManager
from scripts import iniciar_web


class TestWebApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/raw/metabase").mkdir(parents=True)
        (self.root / "data/raw/google_sheets").mkdir(parents=True)
        (self.root / "config").mkdir()
        (self.root / "docs/relatorios").mkdir(parents=True)
        (self.root / "logs").mkdir()
        (self.root / "config/metabase_cards.json").write_text('{"cards":{}}', encoding="utf-8")
        (self.root / "config/sistema.json").write_text('{"fontes":{"google_sheets":{"frequencia":"semanal"}},"geral":{}}', encoding="utf-8")
        (self.root / "config/google_sheets.json").write_text('[{"id":"sheet_a"}]', encoding="utf-8")
        mb = [{"dashboard_uuid":"dash-uuid","dashboard_name":"Painel","card_id":"8","card_name":"Card oito","status":"SUCESSO","quantidade_linhas":4,"quantidade_colunas":2,"arquivo_csv":"data/raw/card.csv"}]
        sheets = [{"fonte_id":"sheet_a","nome_fonte":"Planilha A","status":"SUCESSO","quantidade_linhas":3,"quantidade_colunas":1,"arquivo_csv":"data/raw/sheet.csv","url_original":"https://example.gov/sheet"}]
        (self.root / "data/raw/metabase/catalogo_metabase.json").write_text(json.dumps(mb), encoding="utf-8")
        (self.root / "data/raw/google_sheets/catalogo_sheets.json").write_text(json.dumps(sheets), encoding="utf-8")
        self.history = ExecutionHistory(self.root / "data/history")
        self.history.add_execution("metabase", "dash-uuid:8", "SUCESSO", linhas=4, colunas=2)
        self.old_root = services.ROOT
        self.old_history = web.history
        services.ROOT = self.root
        web.ROOT = self.root
        web.history = self.history
        self.client_context = TestClient(web.app)
        self.client = self.client_context.__enter__()
        session = self.client.get("/api/session").json()
        self.csrf = session["csrf_token"]

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        services.ROOT = self.old_root
        web.ROOT = self.old_root
        web.history = self.old_history
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/login", json={"password":"tests-only-password-123!"}, headers={"X-CSRF-Token":self.csrf})
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"]

    def test_password_hash_is_salted_and_plaintext_is_not_accepted(self):
        encoded=hash_password("tests-only-password-123!")
        self.assertTrue(valid_hash(encoded))
        self.assertNotEqual(encoded, "tests-only-password-123!")
        self.assertTrue(verify_password("tests-only-password-123!", encoded))
        self.assertFalse(verify_password("wrong-test-password", encoded))
        self.assertFalse(valid_hash("tests-only-password-123!"))

    def test_authentication_csrf_and_pages(self):
        self.assertEqual(self.client.get("/api/sources").status_code, 401)
        self.assertEqual(self.client.get("/api/exports").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password":"incorrect"}, headers={"X-CSRF-Token":self.csrf}).status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/exports").status_code, 200)
        self.assertEqual(self.client.post("/api/logout", headers={"X-CSRF-Token":"bad"}).status_code, 403)
        self.assertTrue(csrf)
        logged_out=self.client.post("/api/logout", headers={"X-CSRF-Token":csrf})
        self.assertEqual(logged_out.status_code, 200)
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])

    def test_exports_require_csrf_and_missing_configuration_is_clear(self):
        csrf = self.login()
        no_csrf = self.client.post("/api/exports/test", json={})
        self.assertEqual(no_csrf.status_code, 403)
        status = self.client.get("/api/exports").json()
        self.assertFalse(status["configured"])
        self.assertIn("OPPES_SHEETS_EXPORT_SPREADSHEET_ID", status["message"])
        unavailable = self.client.post("/api/exports/test", json={}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(unavailable.status_code, 503)
        self.assertIn("credenciais", unavailable.json()["detail"])
        no_confirmation = self.client.post("/api/exports", json={"all":True}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(no_confirmation.status_code, 400)

    def test_export_job_is_persisted_and_reports_progress(self):
        csrf = self.login()
        exporter = type("Exporter", (), {"configured":True, "_sources":lambda self:{"dash-uuid:8":{}}})()
        with patch("webapp.main.GoogleSheetsExporter", return_value=exporter), patch.object(web.export_executor, "submit"):
            started = self.client.post("/api/exports", json={"source_ids":["dash-uuid:8"]}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(started.status_code, 200)
        job_id = started.json()["id"]
        job = self.client.get(f"/api/exports/jobs/{job_id}").json()
        self.assertEqual(job["status"], "EM_ANDAMENTO")
        self.assertEqual(job["total"], 1)
        web.active_export_id = None

    def test_dashboard_sources_search_detail_and_manual_frequency(self):
        self.login()
        dash = self.client.get("/api/dashboard")
        self.assertEqual(dash.status_code, 200)
        self.assertEqual(dash.json()["total_sources"], 2)
        self.assertIn("manual", dash.json()["counts"])
        with patch("webapp.main.scheduler_status", return_value={"exists":False,"enabled":None,"state":"não configurada","detail":""}):
            settings = self.client.get("/api/settings")
        self.assertEqual(settings.status_code, 200)
        self.assertIn("mensal", settings.json()["frequencies"])
        listing = self.client.get("/api/sources?search=Card%20oito&type=metabase").json()
        self.assertEqual(listing["total"], 1)
        detail = self.client.get("/api/sources/dash-uuid%3A8").json()
        self.assertEqual(detail["source"]["frequency"], "manual")
        self.assertEqual(len(detail["history"]), 1)

    def test_empty_dashboard_uses_empty_sqlite_without_inventing_history(self):
        self.login()
        empty_history=ExecutionHistory(self.root / "empty_history")
        with patch.object(web, "history", empty_history), patch("webapp.main.scheduler_status", return_value={"exists":False,"enabled":None,"state":"não configurada","detail":""}):
            result=self.client.get("/api/dashboard")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["total_sources"], 2)
        self.assertIsNone(result.json()["last_execution"])
        self.assertEqual(result.json()["trend"], [])
        self.assertEqual(result.json()["counts"].get("manual"), 1)

    def test_frequency_validation_and_config_write_stays_in_project(self):
        csrf = self.login()
        response = self.client.patch("/api/sources/dash-uuid%3A8/frequency", json={"frequency":"mensal","periodicity_source":"Fonte oficial mensal"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(response.status_code, 200)
        saved = json.loads((self.root / "config/metabase_cards.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["cards"]["dash-uuid:8"]["frequencia"], "mensal")
        listed = self.client.get("/api/sources?search=Card%20oito").json()["items"][0]
        self.assertEqual(listed["periodicity_source"], "Fonte oficial mensal")
        bad = self.client.patch("/api/sources/dash-uuid%3A8/frequency", json={"frequency":"hourly"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(bad.status_code, 422)

    def test_invalid_config_is_not_overwritten_by_frequency_update(self):
        csrf = self.login()
        config = self.root / "config/metabase_cards.json"
        config.write_text("{broken", encoding="utf-8")
        response = self.client.patch("/api/sources/dash-uuid%3A8/frequency", json={"frequency":"mensal"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(config.read_text(encoding="utf-8"), "{broken")

    def test_batch_confirmation_and_job_creation_are_controlled(self):
        csrf = self.login()
        denied = self.client.post("/api/operations", json={"operation":"all"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(denied.status_code, 400)
        with patch.object(web.operations, "start", return_value={"id":"job-test","status":"EM_ANDAMENTO"}) as start:
            accepted = self.client.post("/api/operations", json={"operation":"all","confirm":True}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(accepted.status_code, 200)
        start.assert_called_once_with("all", None)

    def test_history_and_dry_run_do_not_register_scheduler(self):
        csrf = self.login()
        rows = self.client.get("/api/history?source_id=dash-uuid%3A8&status=SUCESSO").json()
        self.assertEqual(rows["total"], 1)
        invalid_range=self.client.get("/api/history?date_from=2026-10-16&date_to=2026-10-15")
        self.assertEqual(invalid_range.status_code, 422)
        preview = self.client.post("/api/scheduler/dry-run", json={"action":"install","frequency":"weekly","time":"06:00"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["task_created"])
        self.assertIn("schtasks.exe", preview.json()["command_preview"])

    def test_scheduler_query_is_read_only_and_admin_protected(self):
        self.assertEqual(self.client.get("/api/scheduler").status_code, 401)
        self.login()
        result = type("Result", (), {"returncode":0,"stdout":"TaskName: ObservatorioDiademaColeta\nScheduled Task State: Enabled","stderr":""})()
        with patch("webapp.services.subprocess.run", return_value=result) as run:
            response = self.client.get("/api/scheduler")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])
        self.assertIn("/Query", run.call_args.args[0])
        self.assertNotIn("/Create", run.call_args.args[0])

    def test_network_plain_http_is_rejected(self):
        remote = TestClient(web.app, client=("192.168.1.25", 4567))
        response = remote.get("/api/session")
        self.assertEqual(response.status_code, 426)
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")

    def test_https_sets_secure_cookie_and_rotates_csrf(self):
        remote = TestClient(web.app, base_url="https://secure.test", client=("192.168.1.25", 4567))
        with remote:
            before = remote.get("/api/session").json()["csrf_token"]
            login = remote.post("/api/login", json={"password":"tests-only-password-123!"}, headers={"X-CSRF-Token":before})
            self.assertEqual(login.status_code, 200)
            cookie=login.headers.get("set-cookie", "").lower()
            self.assertIn("; secure", cookie)
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=strict", cookie)
            self.assertIn("max-age=28800", cookie)
            after = login.json()["csrf_token"]
            self.assertNotEqual(before, after)
            denied = remote.post("/api/scheduler/dry-run", json={"action":"query"}, headers={"X-CSRF-Token":before})
            self.assertEqual(denied.status_code, 403)

    def test_launcher_requires_secrets_and_tls_certificate_pair(self):
        with patch("scripts.iniciar_web.os.chdir"), patch.dict(os.environ, {"OPPES_ADMIN_PASSWORD_HASH":"", "OPPES_SESSION_SECRET":""}, clear=False):
            with self.assertRaises(SystemExit):
                iniciar_web.main([])
        valid_admin_hash=hash_password("tests-only-password-123!")
        with patch("scripts.iniciar_web.os.chdir"), patch.dict(os.environ, {"OPPES_ADMIN_PASSWORD_HASH":valid_admin_hash, "OPPES_SESSION_SECRET":""}, clear=False):
            with self.assertRaises(SystemExit):
                iniciar_web.main([])
        with patch("scripts.iniciar_web.os.chdir") as change_dir, patch("uvicorn.run") as server, patch.dict(os.environ, {"OPPES_ADMIN_PASSWORD_HASH":valid_admin_hash, "OPPES_SESSION_SECRET":"tests-only-session-secret-0123456789abcdef0123456789"}, clear=False):
            self.assertEqual(iniciar_web.main([]), 0)
            self.assertEqual(server.call_args.kwargs["host"], "127.0.0.1")
            change_dir.assert_called_once_with(iniciar_web.ROOT)
        with patch("scripts.iniciar_web.os.chdir"), patch.dict(os.environ, {"OPPES_ADMIN_PASSWORD_HASH":valid_admin_hash, "OPPES_SESSION_SECRET":"tests-only-session-secret-0123456789abcdef0123456789", "OPPES_TLS_CERT":"", "OPPES_TLS_KEY":""}, clear=False):
            with self.assertRaises(SystemExit):
                iniciar_web.main(["--rede"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
            cert.write_text("not a certificate", encoding="utf-8")
            key.write_text("not a key", encoding="utf-8")
            with patch.object(iniciar_web, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "inválidos"):
                    iniciar_web.validate_tls_files(str(cert), str(key))
                with self.assertRaisesRegex(ValueError, "fora do projeto"):
                    iniciar_web.validate_tls_files(str(root / "cert.pem"), str(key))

    def test_background_operation_records_result_and_rejects_overlap(self):
        gate = threading.Event()
        finished = threading.Event()
        manager = OperationManager()
        def worker(operation, root, source):
            gate.wait(2)
            finished.set()
            return {"total_sucessos":1,"total_falhas":0,"total_fontes_coletadas":1}
        with patch("webapp.services.ROOT", self.root), patch("webapp.services.run_collection", side_effect=worker):
            # Use a manager rooted in the fixture database.
            manager.history = ExecutionHistory(self.root / "data/history")
            first = manager.start("source", "dash-uuid:8")
            with self.assertRaises(RuntimeError):
                manager.start("all")
            gate.set()
            deadline=time.time()+3
            while manager.active_id and time.time()<deadline:
                time.sleep(.02)
            self.assertTrue(finished.is_set())
            saved=next(row for row in manager.history.get_web_operations(5) if row["id"]==first["id"])
            self.assertEqual(saved["status"],"SUCESSO")
            self.assertEqual(saved["resultado"]["total_sucessos"],1)
        manager.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from src.engine.execution_history import ExecutionHistory
from src.engine.google_sheets_exporter import ExportError, GoogleSheetsExporter


class FakeRequest:
    def __init__(self, response=None, fail=False):
        self.response, self.fail = response or {}, fail
    def execute(self):
        if self.fail:
            raise RuntimeError("simulated API failure")
        return self.response


class FakeSheetsAPI:
    def __init__(self, old_title=None, fail_update=False):
        self.old_title, self.fail_update = old_title, fail_update
        self.final_batches, self.values_updates = [], []
        self.sheets = {10: old_title} if old_title else {}
        self.control_rows = []
    def spreadsheets(self): return self
    def get(self, **kwargs):
        if "range" in kwargs:
            return FakeRequest({"values": self.control_rows})
        sheets = [{"properties": {"sheetId": sid, "title": title}} for sid, title in self.sheets.items()]
        return FakeRequest({"spreadsheetId": "spreadsheet-test", "properties": {"title": "Destino"}, "sheets": sheets})
    def batchUpdate(self, **kwargs):
        requests = kwargs["body"]["requests"]
        self.final_batches.append(requests)
        for request in requests:
            if "addSheet" in request:
                props = request["addSheet"]["properties"]
                self.sheets[props["sheetId"]] = props["title"]
                if props["title"] == "Controle_OPPES":
                    self.control_rows = [["fonte_id", "nome_fonte", "tipo_origem", "url_original", "aba_destino",
                        "ultima_coleta_sucesso_utc", "ultima_exportacao_sucesso_utc", "linhas", "colunas", "resultado", "mensagem_erro"]]
            elif "updateSheetProperties" in request:
                props = request["updateSheetProperties"]["properties"]
                self.sheets[props["sheetId"]] = props["title"]
            elif "deleteSheet" in request:
                self.sheets.pop(request["deleteSheet"]["sheetId"], None)
            elif "updateCells" in request:
                data = request["updateCells"]
                start = data["range"]["startRowIndex"]
                while len(self.control_rows) < start + len(data["rows"]):
                    self.control_rows.append([])
                for offset, row in enumerate(data["rows"]):
                    self.control_rows[start + offset] = [cell.get("userEnteredValue", {}).get("stringValue", "") for cell in row["values"]]
        return FakeRequest()
    def values(self): return self
    def update(self, **kwargs):
        self.values_updates.append(kwargs)
        return FakeRequest(fail=self.fail_update)

class TestGoogleSheetsExporter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/raw/google_sheets").mkdir(parents=True)
        (self.root / "data/raw/google_sheets/catalogo_sheets.json").write_text(
            '[{"fonte_id":"sheet-a","nome_fonte":"Fonte A","url_original":"https://example.test"}]', encoding="utf-8")
        self.csv = self.root / "data/raw/google_sheets/a.csv"
        self.csv.write_text('nome,valor\n"Diadema \u2014 a\u00e7\u00e3o",\n=1+1,42\n', encoding="utf-8")
        self.history = ExecutionHistory(self.root / "data/history")
        record = self.history.add_execution("sheets", "sheet-a", "SUCESSO", linhas=2, colunas=2,
                                            arquivo_csv=str(self.csv))
        self.exporter = GoogleSheetsExporter(self.root, spreadsheet_id="spreadsheet-test",
                                              credentials_file="service-account-test.json", service=Mock(), sleep=lambda _: None)
        # Keep the expected collection timestamp in a format consumed by export code.
        with closing(sqlite3.connect(self.root / "data/history/historico.sqlite3")) as db:
            db.execute("UPDATE execucoes SET data_fim_utc=? WHERE fonte_id=?", (record["data_fim_utc"], "sheet-a"))
            db.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_configuration_is_explicit(self):
        exp = GoogleSheetsExporter(self.root, spreadsheet_id="", credentials_file="")
        self.assertFalse(exp.status()["configured"])
        with self.assertRaisesRegex(ExportError, "configure"):
            exp.test_connection()

    def test_csv_read_preserves_unicode_and_formula_as_raw_text(self):
        rows, record, digest = self.exporter._csv_rows("sheet-a")
        self.assertEqual(rows[1][0], "Diadema — ação")
        self.assertEqual(rows[2][0], "=1+1")
        self.assertEqual(rows[1][1], "")
        self.assertTrue(digest)

    def test_source_mapping_is_stable_and_unique_for_similar_names(self):
        first = self.exporter._title("source-a", "Planilha / Sa\u00fade[]:*?/\\")
        self.assertEqual(first, self.exporter._title("source-a", "Nome alterado"))
        second = self.exporter._title("source-b", "Planilha / Sa\u00fade")
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first), 100)
        self.assertFalse(any(ch in first for ch in "[]:*?/\\"))

    def test_successful_local_collection_is_required(self):
        with self.assertRaisesRegex(ExportError, "sucesso"):
            self.exporter._csv_rows("unknown-source")

    def test_mangled_legacy_absolute_path_recovers_only_inside_raw_directory(self):
        with closing(sqlite3.connect(self.root / "data/history/historico.sqlite3")) as db:
            db.execute("UPDATE execucoes SET arquivo_csv=? WHERE fonte_id=?",
                       ("C:/old/project/data/raw/google_sheets/a.csv", "sheet-a"))
            db.commit()
        rows, _, _ = self.exporter._csv_rows("sheet-a")
        self.assertEqual(rows[1][0], "Diadema — ação")

    def test_export_uses_raw_values_and_updates_destination_tab(self):
        target = self.exporter._title("sheet-a", "Fonte A")
        api = FakeSheetsAPI(old_title=target)
        exporter = GoogleSheetsExporter(self.root, "spreadsheet-test", "external.json", service=api, sleep=lambda _: None)
        result = exporter.export("sheet-a")
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(api.values_updates[0]["valueInputOption"], "RAW")
        final = api.final_batches[-1]
        self.assertTrue(any("deleteSheet" in request for request in final))
        self.assertTrue(any("updateCells" in request for request in final))

    def test_failed_stage_upload_does_not_issue_swap_batch(self):
        target = self.exporter._title("sheet-a", "Fonte A")
        api = FakeSheetsAPI(old_title=target, fail_update=True)
        exporter = GoogleSheetsExporter(self.root, "spreadsheet-test", "external.json", service=api, sleep=lambda _: None)
        result = exporter.export("sheet-a")
        self.assertEqual(result["status"], "FALHA")
        # The only batch deletes the staging sheet; prior destination is not renamed/deleted.
        self.assertEqual(len(api.final_batches), 2)  # create staging, then clean it up
        self.assertEqual(list(api.final_batches[-1][0]), ["deleteSheet"])

    def test_repeating_source_replaces_same_tab_without_duplicate_control_rows(self):
        api = FakeSheetsAPI()
        exporter = GoogleSheetsExporter(self.root, "spreadsheet-test", "external.json", service=api, sleep=lambda _: None)
        self.assertEqual(exporter.export("sheet-a")["status"], "SUCESSO")
        self.assertEqual(exporter.export("sheet-a")["status"], "SUCESSO")
        target = exporter._title("sheet-a", "Fonte A")
        self.assertEqual(sum(title == target for title in api.sheets.values()), 1)
        self.assertFalse(any(title.startswith("_OPPES_TMP_") for title in api.sheets.values()))
        self.assertEqual(sum(1 for row in api.control_rows[1:] if row and row[0] == "sheet-a"), 1)

    def test_failure_is_reflected_in_control_and_previous_success_is_kept(self):
        target = self.exporter._title("sheet-a", "Fonte A")
        api = FakeSheetsAPI(old_title=target, fail_update=True)
        api.sheets[11] = "Controle_OPPES"
        api.control_rows = [["fonte_id", "nome_fonte", "tipo_origem", "url_original", "aba_destino",
            "ultima_coleta_sucesso_utc", "ultima_exportacao_sucesso_utc", "linhas", "colunas", "resultado", "mensagem_erro"],
            ["sheet-a", "Fonte A", "Google Sheets", "", target, "collection-ok", "previous-ok", "2", "2", "SUCESSO", ""]]
        exporter = GoogleSheetsExporter(self.root, "spreadsheet-test", "external.json", service=api, sleep=lambda _: None)
        self.assertEqual(exporter.export("sheet-a")["status"], "FALHA")
        row = next(row for row in api.control_rows[1:] if row and row[0] == "sheet-a")
        self.assertEqual(row[9], "FALHA")
        self.assertEqual(row[5], "collection-ok")
        self.assertEqual(sum(title == target for title in api.sheets.values()), 1)

    def test_existing_unmapped_tab_is_not_replaced(self):
        target = self.exporter._title("sheet-a", "Fonte A")
        with closing(sqlite3.connect(self.root / "data/history/historico.sqlite3")) as db:
            db.execute("DELETE FROM export_mapeamentos WHERE fonte_id='sheet-a'")
            db.commit()
        api = FakeSheetsAPI(old_title=target)
        exporter = GoogleSheetsExporter(self.root, "spreadsheet-test", "external.json", service=api, sleep=lambda _: None)
        result = exporter.export("sheet-a")
        self.assertEqual(result["status"], "SUCESSO")
        self.assertIn(target, api.sheets.values())
        self.assertNotEqual(result["sheet_title"], target)


if __name__ == "__main__":
    unittest.main()

"""Exporta snapshots CSV locais para uma planilha central via Google Sheets API."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.engine.execution_history import ExecutionHistory
from src.engine.collection_operations import source_catalogs

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
CONTROL = "Controle_OPPES"
MAX_CELLS = 10_000_000
CHUNK_ROWS = 400
CONTROL_HEADERS = ["fonte_id", "nome_fonte", "tipo_origem", "url_original", "aba_destino",
                   "ultima_coleta_sucesso_utc", "ultima_exportacao_sucesso_utc", "linhas",
                   "colunas", "resultado", "mensagem_erro"]


@contextmanager
def _db(path: Path):
    conn = sqlite3.connect(path, timeout=30)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class ExportError(RuntimeError):
    pass


def _api_error(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403:
        return "Acesso negado. Compartilhe a planilha de destino com a conta de serviço como editora."
    if status == 404:
        return "Planilha central não encontrada; confira o ID e o compartilhamento."
    if status in (429, 500, 502, 503, 504):
        return "A API do Google está temporariamente indisponível ou limitou as requisições."
    return f"Falha na API Google ({status or type(exc).__name__})."


class GoogleSheetsExporter:
    def __init__(self, root: Path, spreadsheet_id: str | None = None,
                 credentials_file: str | None = None, service: Any = None,
                 sleep=time.sleep):
        self.root = Path(root).resolve()
        self.spreadsheet_id = spreadsheet_id if spreadsheet_id is not None else os.getenv("OPPES_SHEETS_EXPORT_SPREADSHEET_ID", "")
        self.credentials_file = credentials_file if credentials_file is not None else os.getenv("OPPES_GOOGLE_SERVICE_ACCOUNT_FILE", "")
        self.service = service
        self.sleep = sleep
        self.history = ExecutionHistory(self.root / "data/history")
        self.db_path = self.root / "data/history/historico.sqlite3"
        with _db(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS exportacoes (
                id TEXT PRIMARY KEY, fonte_id TEXT NOT NULL, inicio_utc TEXT NOT NULL,
                fim_utc TEXT, resultado TEXT NOT NULL, linhas INTEGER DEFAULT 0,
                colunas INTEGER DEFAULT 0, spreadsheet_id TEXT, sheet_title TEXT,
                mensagem TEXT, hash_sha256 TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS export_mapeamentos (
                fonte_id TEXT PRIMARY KEY, sheet_title TEXT NOT NULL UNIQUE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS sheets_export_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, checked_at TEXT NOT NULL,
                ok INTEGER NOT NULL, message TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS export_jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, total INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, inicio_utc TEXT NOT NULL,
                fim_utc TEXT, resultado_json TEXT, mensagem TEXT)""")

    @property
    def configured(self) -> bool:
        return bool(self.spreadsheet_id and self.credentials_file)

    def status(self) -> dict[str, Any]:
        latest = {}
        with _db(self.db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM exportacoes ORDER BY inicio_utc").fetchall()
        for row in rows:
            latest[row["fonte_id"]] = dict(row)
        with _db(self.db_path) as db:
            check = db.execute("SELECT checked_at,ok,message FROM sheets_export_checks ORDER BY id DESC LIMIT 1").fetchone()
        return {"configured": self.configured, "spreadsheet_id": self.spreadsheet_id or None,
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit" if self.spreadsheet_id else None,
                "message": "Configure OPPES_SHEETS_EXPORT_SPREADSHEET_ID e OPPES_GOOGLE_SERVICE_ACCOUNT_FILE para habilitar." if not self.configured else "Configuração presente; teste a conexão para confirmar acesso.",
                "last_check": ({"checked_at": check[0], "ok": bool(check[1]), "message": check[2]} if check else None),
                "latest": latest, "history": list(reversed([dict(r) for r in rows]))[:100]}

    def _client(self):
        if not self.configured:
            raise ExportError("Exportação indisponível: configure o ID da planilha central e o arquivo de credenciais.")
        if self.service is not None:
            return self.service
        cred = Path(self.credentials_file).expanduser().resolve()
        if self.root == cred or self.root in cred.parents:
            raise ExportError("Mantenha as credenciais fora do repositório OPPES.")
        if not cred.is_file():
            raise ExportError("Arquivo de credenciais da conta de serviço não encontrado.")
        try:
            from google.oauth2.service_account import Credentials
            from google_auth_httplib2 import AuthorizedHttp
            from googleapiclient.discovery import build
            import httplib2
            credentials = Credentials.from_service_account_file(str(cred), scopes=[SCOPE])
            http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=30))
            return build("sheets", "v4", http=http, cache_discovery=False)
        except ImportError as exc:
            raise ExportError("Dependências da Google Sheets API ausentes. Execute: py -m pip install -r requirements.txt") from exc
        except Exception as exc:
            raise ExportError("Não foi possível carregar credenciais válidas da conta de serviço.") from exc

    def _call(self, func):
        for attempt in range(4):
            try:
                return func()
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise ExportError(_api_error(exc)) from exc
                self.sleep(min(2 ** attempt, 8))

    def test_connection(self) -> dict[str, Any]:
        checked = datetime.now(timezone.utc).isoformat()
        try:
            service = self._client()
            data = self._call(lambda: service.spreadsheets().get(spreadsheetId=self.spreadsheet_id,
                                                                  fields="spreadsheetId,properties.title,sheets.properties").execute())
            result = {"ok": True, "spreadsheet_id": data.get("spreadsheetId"),
                      "title": data.get("properties", {}).get("title"), "tabs": len(data.get("sheets", [])),
                      "checked_at": checked, "message": "Leitura da planilha central confirmada."}
        except Exception as exc:
            result = {"ok": False, "checked_at": checked,
                      "message": str(exc) if isinstance(exc, ExportError) else _api_error(exc)}
        with _db(self.db_path) as db:
            db.execute("INSERT INTO sheets_export_checks(checked_at,ok,message) VALUES(?,?,?)",
                       (checked, int(result["ok"]), result["message"][:500]))
        if not result["ok"]:
            raise ExportError(result["message"])
        return result

    def _sources(self) -> dict[str, dict]:
        mb, sheets = source_catalogs(self.root)
        result = {str(s.get("fonte_id")): {**s, "_type": "Google Sheets"} for s in sheets}
        for card in mb:
            key = f"{card.get('dashboard_uuid')}:{card.get('card_id')}"
            result[key] = {**card, "fonte_id": key, "nome_fonte": card.get("card_name"), "_type": "Metabase"}
        return result

    def _title(self, source_id: str, name: str) -> str:
        with _db(self.db_path) as db:
            row = db.execute("SELECT sheet_title FROM export_mapeamentos WHERE fonte_id=?", (source_id,)).fetchone()
            if row:
                return row[0]
            slug = re.sub(r"[^A-Za-z0-9_ -]", "", name).strip().replace(" ", "_") or "Fonte"
            title = f"{slug[:75]}_{hashlib.sha256(source_id.encode()).hexdigest()[:10]}"[:100]
            db.execute("INSERT INTO export_mapeamentos(fonte_id,sheet_title) VALUES(?,?)", (source_id, title))
            return title

    def _record_failed_control(self, service, source_id: str, source: dict, title: str | None,
        finished: str, rows: list[list[str]], message: str) -> None:
        """Best-effort latest status in the workbook; full attempts remain in SQLite."""
        try:
            meta = self._call(lambda: service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id, fields="sheets.properties").execute())
            tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            if CONTROL not in tabs:
                return
            existing = self._call(lambda: service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=f"'{CONTROL}'!A:K").execute()).get("values", [])
            if not existing or existing[0] != CONTROL_HEADERS:
                return
            row_index = next((i for i, row in enumerate(existing[1:], 1) if row and row[0] == source_id), len(existing))
            previous = existing[row_index] if row_index < len(existing) else []
            last_success = previous[5] if len(previous) > 5 else ""
            data = [source_id, source.get("nome_fonte") or source.get("name", ""), source.get("_type", ""),
                    source.get("url_original") or source.get("url", ""), title or "", last_success, finished,
                    str(max(0, len(rows) - 1)), str(max(map(len, rows), default=0)), "FALHA", message[:500]]
            request = {"updateCells": {"range": {"sheetId": tabs[CONTROL], "startRowIndex": row_index,
                "startColumnIndex": 0}, "rows": [{"values": [{"userEnteredValue": {"stringValue": str(v)}} for v in data]}],
                "fields": "userEnteredValue"}}
            self._call(lambda: service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id,
                body={"requests": [request]}).execute())
        except Exception:
            # A failed attempt must not hide the original export error.
            pass

    def _csv_rows(self, source_id: str) -> tuple[list[list[str]], dict, str]:
        success = self.history.get_last_success(source_id)
        if not success:
            raise ExportError("A fonte ainda não tem coleta local concluída com sucesso.")
        path = Path(success.get("arquivo_csv") or "")
        if not path.is_absolute():
            path = (self.root / path).resolve()
        else:
            path = path.resolve()
        raw_dir = (self.root / "data/raw").resolve()
        if not path.is_file() or raw_dir not in path.parents:
            # Older Windows rows may contain a mangled absolute project path after
            # a console-codepage conversion. Recover only by the recorded basename
            # within the fixed raw-data directory; never follow the stored path.
            basename = Path(success.get("arquivo_csv") or "").name
            candidates = [candidate.resolve() for candidate in raw_dir.rglob(basename) if candidate.is_file()]
            if len(candidates) == 1 and raw_dir in candidates[0].parents:
                path = candidates[0]
        if raw_dir not in path.parents or not path.is_file():
            raise ExportError("CSV da última coleta não está disponível dentro de data/raw.")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ExportError("Não foi possível ler o CSV local da coleta.") from exc
        width = max((len(row) for row in rows), default=0)
        cells = max(len(rows), 1) * max(width, 1)
        if cells > MAX_CELLS:
            raise ExportError(f"Fonte excede o limite de {MAX_CELLS:,} células; consulte o CSV local completo.")
        rows = [row + [""] * (width - len(row)) for row in rows]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return rows, success, digest

    def export(self, source_id: str) -> dict[str, Any]:
        source = self._sources().get(source_id)
        if not source:
            raise ExportError("Fonte não encontrada no catálogo cadastrado.")
        start = datetime.now(timezone.utc).isoformat()
        export_id = str(uuid.uuid4())
        title = None
        rows: list[list[str]] = []
        digest = None
        try:
            rows, collection, digest = self._csv_rows(source_id)
            with _db(self.db_path) as db:
                had_mapping = db.execute("SELECT 1 FROM export_mapeamentos WHERE fonte_id=?", (source_id,)).fetchone() is not None
            title = self._title(source_id, source.get("nome_fonte") or source.get("name") or source_id)
            service = self._client()
            meta = self._call(lambda: service.spreadsheets().get(spreadsheetId=self.spreadsheet_id,
                                                                  fields="sheets.properties").execute())
            tabs = meta.get("sheets", [])
            by_title = {s["properties"]["title"]: s["properties"]["sheetId"] for s in tabs}
            if title in by_title and not had_mapping:
                # Never claim or replace a workbook tab that was not mapped by OPPES.
                base = title.rsplit("_", 1)[0]
                title = f"{base[:65]}_{hashlib.sha256((source_id + self.spreadsheet_id).encode()).hexdigest()[:16]}"
                with _db(self.db_path) as db:
                    db.execute("INSERT OR REPLACE INTO export_mapeamentos(fonte_id,sheet_title) VALUES(?,?)", (source_id, title))
            next_sheet_id = max(by_title.values(), default=0) + 1
            control_id = by_title.get(CONTROL)
            existing_id = by_title.get(title)
            stage_title = f"_OPPES_TMP_{uuid.uuid4().hex[:16]}"
            stage_id = next_sheet_id
            add = {"addSheet": {"properties": {"sheetId": stage_id, "title": stage_title,
                   "gridProperties": {"rowCount": max(1, len(rows)), "columnCount": max(1, max(map(len, rows), default=1))}}}}
            self._call(lambda: service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": [add]}).execute())
            try:
                for start_row in range(0, len(rows), CHUNK_ROWS):
                    chunk = rows[start_row:start_row + CHUNK_ROWS]
                    # RAW makes strings beginning with =, +, - or @ plain text.
                    self._call(lambda chunk=chunk, start_row=start_row: service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id, range=f"'{stage_title}'!A{start_row + 1}",
                        valueInputOption="RAW", body={"values": chunk}).execute())
                requests = []
                backup_title = None
                if existing_id is not None:
                    backup_title = f"_OPPES_OLD_{uuid.uuid4().hex[:12]}"
                    requests.append({"updateSheetProperties": {"properties": {"sheetId": existing_id, "title": backup_title}, "fields": "title"}})
                requests.append({"updateSheetProperties": {"properties": {"sheetId": stage_id, "title": title}, "fields": "title"}})
                if backup_title:
                    requests.append({"deleteSheet": {"sheetId": existing_id}})
                if control_id is None:
                    control_id = next_sheet_id + 1
                    requests.append({"addSheet": {"properties": {"sheetId": control_id, "title": CONTROL,
                        "gridProperties": {"rowCount": 1000, "columnCount": len(CONTROL_HEADERS)}}}})
                    control_row = 1
                    control_start = 0
                    write_rows = [CONTROL_HEADERS]
                else:
                    existing_control = self._call(lambda: service.spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id, range=f"'{CONTROL}'!A:K").execute()).get("values", [])
                    control_row = next((i for i, row in enumerate(existing_control[1:], 1)
                                        if row and row[0] == source_id), len(existing_control))
                    control_start = control_row
                    write_rows = []
                    if not existing_control or existing_control[0] != CONTROL_HEADERS:
                        write_rows.append(CONTROL_HEADERS)
                        control_start = 0
                        control_row = next((i for i, row in enumerate(existing_control)
                                            if row and row[0] == source_id), len(existing_control))
                        if control_row == 0:
                            control_row = 1
                control_data = [source_id, source.get("nome_fonte") or source.get("name", ""),
                    source.get("_type", ""), source.get("url_original") or source.get("url", ""), title,
                    collection.get("data_fim_utc"), datetime.now(timezone.utc).isoformat(), str(max(0, len(rows)-1)),
                    str(max(map(len, rows), default=0)), "SUCESSO", ""]
                write_rows.append(control_data)
                requests.append({"updateCells": {"range": {"sheetId": control_id, "startRowIndex": control_start,
                    "startColumnIndex": 0}, "rows": [{"values": [{"userEnteredValue": {"stringValue": str(v)}} for v in row]}
                    for row in write_rows], "fields": "userEnteredValue"}})
                self._call(lambda: service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": requests}).execute())
            except Exception:
                try:
                    self._call(lambda: service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id,
                        body={"requests": [{"deleteSheet": {"sheetId": stage_id}}]}).execute())
                except Exception:
                    pass
                raise
            outcome, message = "SUCESSO", "Exportação confirmada pela API Google."
        except Exception as exc:
            outcome = "FALHA"
            message = str(exc) if isinstance(exc, ExportError) else _api_error(exc)
        finish = datetime.now(timezone.utc).isoformat()
        if outcome == "FALHA" and 'service' in locals():
            self._record_failed_control(service, source_id, source, title, finish, rows, message)
        with _db(self.db_path) as db:
            db.execute("INSERT INTO exportacoes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (export_id, source_id, start, finish, outcome, max(0, len(rows)-1), max(map(len, rows), default=0),
                 self.spreadsheet_id or None, title, message[:500], digest))
        return {"id": export_id, "source_id": source_id, "status": outcome, "started_at": start,
                "finished_at": finish, "rows": max(0, len(rows)-1), "columns": max(map(len, rows), default=0),
                "sheet_title": title, "message": message}

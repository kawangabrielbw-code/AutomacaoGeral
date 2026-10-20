from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import uuid
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.engine.collection_operations import run_collection, source_catalogs
from src.engine.execution_history import ExecutionHistory
from scripts.agendamento_windows import build_command, TASK_NAME

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)
FREQUENCIES = {
    "diaria": "Diária", "semanal": "Semanal", "quinzenal": "Quinzenal",
    "mensal": "Mensal", "trimestral": "Trimestral", "semestral": "Semestral",
    "anual": "Anual", "manual": "Manual", "estatica": "Estática", "pontual": "Pontual",
}


class OperationManager:
    """One in-process worker; collector's existing filesystem lock protects across processes."""
    def __init__(self) -> None:
        self.history = ExecutionHistory(ROOT / "data/history")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oppes-coleta")
        self.guard = threading.Lock()
        self.active_id: Optional[str] = None

    def start(self, operation: str, target: Optional[str] = None) -> dict[str, Any]:
        with self.guard:
            if self.active_id:
                raise RuntimeError("Já existe uma operação web em andamento.")
            operation_id = str(uuid.uuid4())
            self.history.create_web_operation(operation_id, operation, target)
            self.active_id = operation_id
            self.executor.submit(self._execute, operation_id, operation, target)
            return next(row for row in self.history.get_web_operations(1) if row["id"] == operation_id)

    def _execute(self, operation_id: str, operation: str, target: Optional[str]) -> None:
        try:
            result = run_collection(operation, ROOT, target)
            failed = int(result.get("total_falhas", 0))
            status = "SEM_FONTES" if result.get("sem_fontes") else ("PARCIAL" if failed else "SUCESSO")
            self.history.finish_web_operation(operation_id, status, result=result)
        except Exception as exc:  # Persist only useful exception text; no traceback or secret env.
            logger.exception("Coleta web falhou (%s)", operation_id)
            message = str(exc)[:1000]
            self.history.finish_web_operation(operation_id, "FALHA", error=message)
        finally:
            with self.guard:
                if self.active_id == operation_id:
                    self.active_id = None

    def active(self) -> Optional[dict[str, Any]]:
        with self.guard:
            active_id = self.active_id
        if not active_id:
            return None
        return next((row for row in self.history.get_web_operations(10) if row["id"] == active_id), None)


operations = OperationManager()


def catalog_rows(history: Optional[ExecutionHistory] = None) -> list[dict[str, Any]]:
    history = history or ExecutionHistory(ROOT / "data/history")
    mb, sheets = source_catalogs(ROOT)
    states = {row["fonte_id"]: row for row in history.get_schedule_states()}
    latest: dict[str, dict] = {}
    for row in history.get_records():
        latest[row["fonte_id"]] = row
    metabase_config = _read(ROOT / "config/metabase_cards.json", {})
    freq_config = metabase_config.get("cards", {}) if isinstance(metabase_config, dict) else {}
    system_config = _read(ROOT / "config/sistema.json", {})
    if not isinstance(freq_config, dict):
        freq_config = {}
    if not isinstance(system_config, dict):
        system_config = {}
    sheet_freq = system_config.get("frequencias_por_fonte", {})
    if not isinstance(sheet_freq, dict):
        sheet_freq = {}
    sheets_settings = system_config.get("fontes", {})
    if not isinstance(sheets_settings, dict):
        sheets_settings = {}
    sheets_settings = sheets_settings.get("google_sheets", {})
    if not isinstance(sheets_settings, dict):
        sheets_settings = {}
    rows: list[dict[str, Any]] = []
    for card in mb:
        source_id = f"{card.get('dashboard_uuid')}:{card.get('card_id')}"
        key = f"gsheet_{source_id}"
        state, attempt = states.get(source_id, {}), latest.get(source_id)
        card_config = freq_config.get(source_id, {})
        if not isinstance(card_config, dict):
            card_config = {}
        frequency = card_config.get("frequencia", state.get("frequencia", "manual"))
        history.set_frequency(source_id, "metabase", frequency)
        due, success, next_run = history.is_due_for_update(source_id, frequency)
        status = _state(attempt, due, frequency, success)
        rows.append({"id": source_id, "type": "metabase", "name": card.get("card_name"),
            "dashboard": card.get("dashboard_name"), "dashboard_uuid": card.get("dashboard_uuid"),
            "card_id": str(card.get("card_id")), "url": f"https://analytics.diadema.sp.gov.br/public/dashboard/{card.get('dashboard_uuid')}",
            "frequency": frequency, "periodicity_source": card_config.get("fonte_periodicidade"),
            "last_attempt": state.get("ultima_tentativa_utc") or (attempt or {}).get("data_fim_utc"),
            "last_success": state.get("ultima_atualizacao_sucesso_utc") or (success or {}).get("data_fim_utc"),
            "next_run": state.get("proxima_execucao_utc") or (next_run.isoformat() if next_run else None),
            "status": "falha" if attempt and str(attempt.get("status", "")).startswith(("FALHA", "REQUER_AUTENTICACAO")) else status,
            "rows": card.get("quantidade_linhas", 0), "columns": card.get("quantidade_colunas", 0),
            "csv_path": card.get("arquivo_csv"), "error": (attempt or {}).get("mensagem") if attempt and str(attempt.get("status", "")).startswith("FALHA") else None,
            "last_result": attempt.get("status") if attempt else card.get("status")})
    for sheet in sheets:
        source_id = str(sheet.get("fonte_id"))
        config_key = f"gsheet_{source_id}"
        entry = sheet_freq.get(config_key, {})
        if not isinstance(entry, dict):
            entry = {}
        frequency = entry.get("frequencia", sheets_settings.get("frequencia", "semanal"))
        state, attempt = states.get(source_id, {}), latest.get(source_id)
        history.set_frequency(source_id, "sheets", frequency)
        due, success, next_run = history.is_due_for_update(source_id, frequency)
        rows.append({"id": source_id, "type": "sheets", "name": sheet.get("nome_fonte"), "dashboard": None,
            "dashboard_uuid": None, "card_id": None, "url": _public_url(sheet.get("url_original")), "frequency": frequency,
            "periodicity_source": entry.get("observacao"),
            "last_attempt": state.get("ultima_tentativa_utc") or (attempt or {}).get("data_fim_utc"),
            "last_success": state.get("ultima_atualizacao_sucesso_utc") or (success or {}).get("data_fim_utc"),
            "next_run": state.get("proxima_execucao_utc") or (next_run.isoformat() if next_run else None),
            "status": "falha" if attempt and str(attempt.get("status", "")).startswith(("FALHA", "REQUER_AUTENTICACAO")) else _state(attempt, due, frequency, success),
            "rows": sheet.get("quantidade_linhas", 0), "columns": sheet.get("quantidade_colunas", 0),
            "csv_path": sheet.get("arquivo_csv"), "error": (attempt or {}).get("mensagem") if attempt and str(attempt.get("status", "")).startswith(("FALHA", "REQUER_AUTENTICACAO")) else None,
            "last_result": attempt.get("status") if attempt else sheet.get("status")})
    return rows


def _state(attempt: Optional[dict], due: bool, frequency: str, success: Optional[dict]) -> str:
    if attempt and str(attempt.get("status", "")).startswith(("FALHA", "REQUER_AUTENTICACAO")):
        return "falha"
    if due:
        return "vencida"
    if frequency in {"manual", "estatica", "pontual"}:
        return "manual"
    return "atualizada" if success else "pendente"


def source_history(source_id: str, history: Optional[ExecutionHistory] = None) -> list[dict]:
    history = history or ExecutionHistory(ROOT / "data/history")
    return [row for row in history.get_records() if row.get("fonte_id") == source_id]


def save_frequency(source_id: str, frequency: str, periodicity_source: Optional[str] = None) -> dict:
    if frequency not in FREQUENCIES:
        raise ValueError("Periodicidade inválida.")
    rows = catalog_rows()
    source = next((row for row in rows if row["id"] == source_id), None)
    if not source:
        raise LookupError("Fonte não encontrada.")
    if periodicity_source is not None and len(periodicity_source) > 240:
        raise ValueError("A justificativa de periodicidade deve ter até 240 caracteres.")
    if source["type"] == "metabase":
        path = ROOT / "config/metabase_cards.json"
        data = _read_for_update(path, {"cards": {}})
        if not isinstance(data.get("cards", {}), dict):
            raise ValueError("A configuração cards em metabase_cards.json precisa ser um objeto JSON.")
        data.setdefault("cards", {})[source_id] = {"frequencia": frequency}
        if periodicity_source:
            data["cards"][source_id]["fonte_periodicidade"] = periodicity_source.strip()
    else:
        path = ROOT / "config/sistema.json"
        data = _read_for_update(path, {})
        if not isinstance(data.get("frequencias_por_fonte", {}), dict):
            raise ValueError("A configuração frequencias_por_fonte em sistema.json precisa ser um objeto JSON.")
        source_config = data.setdefault("frequencias_por_fonte", {}).setdefault(f"gsheet_{source_id}", {})
        if not isinstance(source_config, dict):
            raise ValueError("A configuração da fonte em sistema.json precisa ser um objeto JSON.")
        source_config["frequencia"] = frequency
        if periodicity_source:
            source_config["observacao"] = periodicity_source.strip()
    if periodicity_source is not None and not periodicity_source.strip():
        if source["type"] == "metabase":
            data["cards"][source_id].pop("fonte_periodicidade", None)
        else:
            data["frequencias_por_fonte"][f"gsheet_{source_id}"].pop("observacao", None)
    _write_json(path, data)
    history = ExecutionHistory(ROOT / "data/history")
    history.set_frequency(source_id, source["type"], frequency)
    return {"source_id": source_id, "frequency": frequency, "next_run": history.is_due_for_update(source_id, frequency)[2]}


def scheduler_status() -> dict[str, Any]:
    command = build_command("query")
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exists": False, "task_name": TASK_NAME, "state": "indisponível", "detail": str(exc)[:300]}
    output = (proc.stdout or proc.stderr or "").strip()
    exists = proc.returncode == 0
    lower = output.casefold()
    disabled = any(token in lower for token in ("disabled", "desabilitada", "desabilitado"))
    enabled = any(token in lower for token in ("scheduled task state: enabled", "estado da tarefa agendada: habilitada", "estado da tarefa agendada: enabled"))
    state = "pausada" if exists and disabled else ("habilitada" if exists and enabled else ("estado não confirmado" if exists else "não configurada"))
    return {"exists": exists, "enabled": (False if disabled else (True if enabled else None)), "task_name": TASK_NAME,
            "state": state,
            "detail": output[:2000]}


def execute_scheduler_action(action: str, frequency: str = "weekly", at: str = "06:00", confirm: bool = False) -> dict:
    if action not in {"install", "pause", "resume", "remove"}:
        raise ValueError("Ação de agendamento inválida.")
    if not confirm:
        raise ValueError("Confirme explicitamente a alteração do agendamento.")
    command = build_command(action, frequency, at)
    if sys.platform != "win32":
        raise OSError("O gerenciamento do Agendador exige Windows.")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    return {"success": result.returncode == 0, "action": action,
            "output": (result.stdout or result.stderr or "").strip()[:2000],
            "status": scheduler_status()}


def scheduler_dry_run(action: str, frequency: str, at: str) -> str:
    if action not in {"install", "pause", "resume", "remove", "query"}:
        raise ValueError("Ação inválida.")
    return subprocess.list2cmdline(build_command(action, frequency, at))


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _read_for_update(path: Path, default: Any) -> Any:
    """Do not overwrite a malformed config with a partial default during edits."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise ValueError(f"Não foi possível ler {path.name}; corrija o JSON antes de salvar.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"A configuração {path.name} precisa ser um objeto JSON.")
    return value


def _public_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None


def _write_json(path: Path, content: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

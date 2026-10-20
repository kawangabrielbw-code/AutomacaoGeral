"""Shared policy for CLI and web-triggered collection operations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from src.engine.execution_history import ExecutionHistory
from src.engine.source_schedule import select_due_metabase_cards, select_failed_metabase_cards
from src.engine.unified_harvester import UnifiedHarvester


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def source_catalogs(root: Path) -> Tuple[list[dict], list[dict]]:
    mb = _read_json(root / "data/raw/metabase/catalogo_metabase.json", [])
    sheets = _read_json(root / "data/raw/google_sheets/catalogo_sheets.json", [])
    return mb if isinstance(mb, list) else [], sheets if isinstance(sheets, list) else []


def due_ids(root: Path, history: ExecutionHistory, metabase: bool = True, sheets: bool = True) -> Set[str]:
    selected: Set[str] = set()
    if sheets:
        settings = _read_json(root / "config/sistema.json", {})
        per_source = settings.get("frequencias_por_fonte", {})
        global_frequency = settings.get("fontes", {}).get("google_sheets", {}).get("frequencia", "semanal")
        sheet_config = _read_json(root / "config/google_sheets.json", [])
        for cfg in sheet_config:
            source_id = str(cfg.get("id") or cfg.get("slug") or "")
            configured_key = f"gsheet_{source_id}"
            frequency = per_source.get(configured_key, {}).get("frequencia", global_frequency)
            history.set_frequency(source_id, "sheets", frequency)
            if history.is_due_for_update(source_id, frequency)[0]:
                selected.add(source_id)
    if metabase:
        cards, _ = source_catalogs(root)
        config = _read_json(root / "config/metabase_cards.json", {}).get("cards", {})
        for card in cards:
            key = f"{card.get('dashboard_uuid')}:{card.get('card_id')}"
            history.set_frequency(key, "metabase", config.get(key, {}).get("frequencia", "manual"))
        selected.update(select_due_metabase_cards(cards, config, history))
    return selected


def failed_ids(root: Path, history: ExecutionHistory) -> Set[str]:
    failed = set(history.get_failed_sources())
    cards, _ = source_catalogs(root)
    failed.update(select_failed_metabase_cards(cards, failed))
    return failed


def run_collection(operation: str, root: Path, source_id: Optional[str] = None) -> Dict[str, Any]:
    """Run an allowlisted operation through the existing unified collector."""
    history = ExecutionHistory(root / "data/history")
    base_dir = root / "data/raw"
    only_ids: Optional[Set[str]] = None
    skip_mb = skip_sheets = False
    if operation == "all":
        pass
    elif operation == "sheets":
        skip_mb = True
    elif operation == "metabase":
        skip_sheets = True
    elif operation == "due":
        only_ids = due_ids(root, history)
    elif operation == "due_metabase":
        only_ids = due_ids(root, history, sheets=False)
        skip_sheets = True
    elif operation == "failed":
        only_ids = failed_ids(root, history)
    elif operation == "source":
        if not source_id:
            raise ValueError("Informe o identificador da fonte.")
        mb, sheets = source_catalogs(root)
        mb_keys = {f"{c.get('dashboard_uuid')}:{c.get('card_id')}" for c in mb}
        sheet_ids = {str(c.get("fonte_id")) for c in sheets}
        if source_id in mb_keys:
            only_ids, skip_sheets = {source_id}, True
        elif source_id in sheet_ids:
            only_ids, skip_mb = {source_id}, True
        else:
            raise ValueError("Fonte não encontrada no catálogo atual.")
    else:
        raise ValueError("Operação não permitida.")

    if only_ids is not None and not only_ids:
        return {"sem_fontes": True, "operacao": operation, "total_fontes_coletadas": 0,
                "total_sucessos": 0, "total_falhas": 0, "mensagem": "Nenhuma fonte atende aos critérios."}
    if only_ids is not None:
        _, sheets = source_catalogs(root)
        sheets_available = {str(c.get("fonte_id")) for c in sheets}
        selected_sheets = bool(only_ids & sheets_available)
        selected_mb = any(":" in key for key in only_ids)
        skip_mb = skip_mb or not selected_mb
        skip_sheets = skip_sheets or not selected_sheets
    harvester = UnifiedHarvester(base_data_dir=base_dir, only_source_ids=only_ids)
    return harvester.run_all(skip_metabase=skip_mb, skip_sheets=skip_sheets)

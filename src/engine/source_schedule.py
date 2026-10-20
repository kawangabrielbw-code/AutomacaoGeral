"""Seleção pura de cards Metabase por frequência e último resultado real."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Set


def card_source_key(card: Dict[str, Any]) -> str:
    """Chave estável: UUID público do dashboard mais ID de card do Metabase."""
    return f"{card.get('dashboard_uuid')}:{card.get('card_id')}"


def select_due_metabase_cards(catalog: Iterable[Dict[str, Any]], config: Dict[str, Any], history: Any) -> Set[str]:
    selected: Set[str] = set()
    for card in catalog:
        key = card_source_key(card)
        frequency = config.get(key, {}).get("frequencia", "manual")
        if history.is_due_for_update(key, frequency)[0]:
            selected.add(key)
    return selected


def select_failed_metabase_cards(catalog: Iterable[Dict[str, Any]], failed_ids: Iterable[str]) -> Set[str]:
    failed = set(failed_ids)
    return {
        card_source_key(card) for card in catalog
        if card_source_key(card) in failed or str(card.get("card_id")) in failed
    }

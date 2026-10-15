"""
Módulo de Histórico de Execuções
Observatório de Políticas Públicas de Diadema (OPPES)

Registra cada execução de coleta com resultados, erros e timestamps,
permitindo controle de frequência, recuperação de falhas e auditoria.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Mapeamento de frequências para intervalos em dias
FREQUENCIA_DIAS = {
    "diaria": 1,
    "semanal": 7,
    "quinzenal": 15,
    "mensal": 30,
    "trimestral": 90,
    "semestral": 180,
    "anual": 365,
    "decenal": 3650,
    "manual": None,  # Sem atualização automática
    "estatica": None,  # Dados que não mudam
    "pontual": None,  # Coleta única
}


class ExecutionHistory:
    """Gerencia o histórico de execuções e controle de frequência por fonte."""

    def __init__(self, history_dir: str | Path = "data/history"):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.history_dir / "execucoes.json"
        self.log_file = self.history_dir / "execucoes.csv"

    def load_history(self) -> List[Dict[str, Any]]:
        """Carrega o histórico completo de execuções."""
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as err:
            logger.warning("Erro ao carregar histórico: %s", err)
            return []

    def save_history(self, records: List[Dict[str, Any]]) -> None:
        """Salva o histórico completo."""
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # JSON
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False, default=str)

        # CSV
        if records:
            fieldnames = [
                "execucao_id", "fonte_tipo", "fonte_id", "data_inicio_utc",
                "data_fim_utc", "status", "linhas_coletadas", "colunas",
                "duracao_segundos", "mensagem", "arquivo_csv",
            ]
            with open(self.log_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in records:
                    writer.writerow(r)

    def add_execution(
        self,
        fonte_tipo: str,
        fonte_id: str,
        status: str,
        linhas: int = 0,
        colunas: int = 0,
        duracao: float = 0.0,
        mensagem: str = "",
        arquivo_csv: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Registra uma nova execução no histórico."""
        records = self.load_history()
        now = datetime.now(timezone.utc)

        record = {
            "execucao_id": f"{fonte_id}_{now.strftime('%Y%m%d_%H%M%S')}",
            "fonte_tipo": fonte_tipo,
            "fonte_id": fonte_id,
            "data_inicio_utc": now.isoformat(),
            "data_fim_utc": now.isoformat(),
            "status": status,
            "linhas_coletadas": linhas,
            "colunas": colunas,
            "duracao_segundos": round(duracao, 2),
            "mensagem": mensagem,
            "arquivo_csv": arquivo_csv,
        }

        records.append(record)
        self.save_history(records)
        return record

    def get_last_success(self, fonte_id: str) -> Optional[Dict[str, Any]]:
        """Retorna a última execução bem-sucedida para uma fonte."""
        records = self.load_history()
        for r in reversed(records):
            if r.get("fonte_id") == fonte_id and r.get("status") == "SUCESSO":
                return r
        return None

    def get_last_attempt(self, fonte_id: str) -> Optional[Dict[str, Any]]:
        """Retorna a última tentativa (sucesso ou falha) para uma fonte."""
        records = self.load_history()
        for r in reversed(records):
            if r.get("fonte_id") == fonte_id:
                return r
        return None

    def get_failed_sources(self) -> List[str]:
        """Retorna IDs das fontes cuja última execução foi uma falha."""
        records = self.load_history()
        last_by_fonte: Dict[str, Dict] = {}
        for r in records:
            fid = r.get("fonte_id")
            if fid:
                last_by_fonte[fid] = r

        return [
            fid for fid, r in last_by_fonte.items()
            if r.get("status", "").startswith("FALHA")
        ]

    def is_due_for_update(
        self, fonte_id: str, frequencia: str = "semanal"
    ) -> Tuple[bool, Optional[datetime], Optional[datetime]]:
        """
        Verifica se uma fonte precisa ser atualizada com base na frequência.
        Retorna (precisa_atualizar, ultima_coleta, proxima_coleta).
        """
        dias = FREQUENCIA_DIAS.get(frequencia.lower())

        if dias is None:
            # Fonte manual/estática - nunca vence automaticamente
            last = self.get_last_success(fonte_id)
            last_dt = None
            if last and last.get("data_fim_utc"):
                try:
                    last_dt = datetime.fromisoformat(last["data_fim_utc"])
                except (ValueError, TypeError):
                    pass
            return False, last_dt, None

        last = self.get_last_success(fonte_id)
        if not last or not last.get("data_fim_utc"):
            return True, None, None

        try:
            last_dt = datetime.fromisoformat(last["data_fim_utc"])
        except (ValueError, TypeError):
            return True, None, None

        next_dt = last_dt + timedelta(days=dias)
        now = datetime.now(timezone.utc)
        is_due = now >= next_dt

        return is_due, last_dt, next_dt

    def get_execution_summary(self) -> Dict[str, Any]:
        """Gera um resumo analítico do histórico de execuções."""
        records = self.load_history()
        if not records:
            return {
                "total_execucoes": 0,
                "total_sucessos": 0,
                "total_falhas": 0,
                "fontes_unicas": 0,
                "primeira_execucao": None,
                "ultima_execucao": None,
            }

        return {
            "total_execucoes": len(records),
            "total_sucessos": sum(1 for r in records if r.get("status") == "SUCESSO"),
            "total_falhas": sum(1 for r in records if r.get("status", "").startswith("FALHA")),
            "fontes_unicas": len(set(r.get("fonte_id") for r in records if r.get("fonte_id"))),
            "primeira_execucao": records[0].get("data_inicio_utc") if records else None,
            "ultima_execucao": records[-1].get("data_inicio_utc") if records else None,
        }

    def cleanup_old_records(self, max_days: int = 90) -> int:
        """Remove registros mais antigos que max_days dias."""
        records = self.load_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        original_count = len(records)

        kept = []
        for r in records:
            try:
                dt = datetime.fromisoformat(r.get("data_fim_utc", ""))
                if dt >= cutoff:
                    kept.append(r)
            except (ValueError, TypeError):
                kept.append(r)  # Manter registros com data inválida

        self.save_history(kept)
        removed = original_count - len(kept)
        if removed > 0:
            logger.info("Histórico: %d registros antigos removidos.", removed)
        return removed

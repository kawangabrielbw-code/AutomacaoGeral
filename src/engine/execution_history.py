"""
Módulo de Histórico de Execuções
Observatório de Políticas Públicas de Diadema (OPPES)

Registra cada execução de coleta com resultados, erros e timestamps,
permitindo controle de frequência, recuperação de falhas e auditoria.
"""

from __future__ import annotations

import csv
import calendar
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
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
        self.db_file = self.history_dir / "historico.sqlite3"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execucoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, execucao_id TEXT NOT NULL,
                fonte_tipo TEXT, fonte_id TEXT NOT NULL, data_inicio_utc TEXT NOT NULL,
                data_fim_utc TEXT NOT NULL, status TEXT NOT NULL,
                linhas_coletadas INTEGER DEFAULT 0, colunas INTEGER DEFAULT 0,
                duracao_segundos REAL DEFAULT 0, mensagem TEXT, arquivo_csv TEXT,
                hash_sha256 TEXT, alteracao TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS fontes (
                fonte_id TEXT PRIMARY KEY, fonte_tipo TEXT NOT NULL, frequencia TEXT NOT NULL,
                ultima_tentativa_utc TEXT, ultima_atualizacao_sucesso_utc TEXT,
                proxima_execucao_utc TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS operacoes_web (
                id TEXT PRIMARY KEY, operacao TEXT NOT NULL, alvo TEXT, status TEXT NOT NULL,
                inicio_utc TEXT NOT NULL, fim_utc TEXT, duracao_segundos REAL,
                resultado_json TEXT, mensagem_erro TEXT)""")
            db.execute("""INSERT OR IGNORE INTO fontes
                (fonte_id,fonte_tipo,frequencia,ultima_tentativa_utc,ultima_atualizacao_sucesso_utc,proxima_execucao_utc)
                SELECT e.fonte_id, MAX(e.fonte_tipo), 'manual', MAX(e.data_fim_utc),
                    (SELECT s.data_fim_utc FROM execucoes s WHERE s.fonte_id=e.fonte_id
                     AND s.status IN ('SUCESSO','VAZIO') ORDER BY s.id DESC LIMIT 1), NULL
                FROM execucoes e GROUP BY e.fonte_id""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_file, timeout=30)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _sync_sqlite(self, record: Dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO execucoes
                (execucao_id,fonte_tipo,fonte_id,data_inicio_utc,data_fim_utc,status,
                linhas_coletadas,colunas,duracao_segundos,mensagem,arquivo_csv,hash_sha256,alteracao)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(record.get(k) for k in (
                "execucao_id","fonte_tipo","fonte_id","data_inicio_utc","data_fim_utc","status",
                "linhas_coletadas","colunas","duracao_segundos","mensagem","arquivo_csv","hash_sha256","alteracao")))

    def get_records(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM execucoes ORDER BY id")]

    def get_schedule_states(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM fontes ORDER BY fonte_tipo, fonte_id")]

    def create_web_operation(self, operation_id: str, operation: str, target: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO operacoes_web (id,operacao,alvo,status,inicio_utc) VALUES (?,?,?,?,?)",
                       (operation_id, operation, target, "EM_ANDAMENTO", now))

    def finish_web_operation(self, operation_id: str, status: str, result: Optional[Dict[str, Any]] = None,
                             error: Optional[str] = None) -> None:
        end = datetime.now(timezone.utc)
        with self._connect() as db:
            row = db.execute("SELECT inicio_utc FROM operacoes_web WHERE id=?", (operation_id,)).fetchone()
            if not row:
                return
            start = datetime.fromisoformat(row[0])
            db.execute("""UPDATE operacoes_web SET status=?,fim_utc=?,duracao_segundos=?,
                resultado_json=?,mensagem_erro=? WHERE id=?""",
                (status, end.isoformat(), round((end-start).total_seconds(), 2),
                 json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                 error, operation_id))

    def get_web_operations(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute("SELECT * FROM operacoes_web ORDER BY inicio_utc DESC LIMIT ?", (limit,))]
        for row in rows:
            try:
                row["resultado"] = json.loads(row.pop("resultado_json")) if row.get("resultado_json") else None
            except ValueError:
                row["resultado"] = None
        return rows

    def interrupt_open_web_operations(self) -> int:
        end = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cur = db.execute("""UPDATE operacoes_web SET status='INTERROMPIDA',fim_utc=?,
                mensagem_erro='Servidor reiniciado antes de registrar o resultado.'
                WHERE status='EM_ANDAMENTO'""", (end,))
            return cur.rowcount

    def set_frequency(self, fonte_id: str, fonte_tipo: str, frequencia: str) -> None:
        next_run = self.is_due_for_update(fonte_id, frequencia)[2]
        with self._connect() as db:
            db.execute("""INSERT INTO fontes (fonte_id,fonte_tipo,frequencia,proxima_execucao_utc)
                VALUES (?,?,?,?) ON CONFLICT(fonte_id) DO UPDATE SET
                fonte_tipo=excluded.fonte_tipo, frequencia=excluded.frequencia,
                proxima_execucao_utc=excluded.proxima_execucao_utc""",
                (fonte_id, fonte_tipo, frequencia, next_run.isoformat() if next_run else None))

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
        frequencia: str = "manual",
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
        self._sync_sqlite(record)
        last_success = self.get_last_success(fonte_id)
        last_success_at = last_success.get("data_fim_utc") if last_success else None
        next_run = self.is_due_for_update(fonte_id, frequencia)[2]
        with self._connect() as db:
            db.execute("""INSERT INTO fontes
                (fonte_id,fonte_tipo,frequencia,ultima_tentativa_utc,ultima_atualizacao_sucesso_utc,proxima_execucao_utc)
                VALUES (?,?,?,?,?,?) ON CONFLICT(fonte_id) DO UPDATE SET
                fonte_tipo=excluded.fonte_tipo, frequencia=excluded.frequencia,
                ultima_tentativa_utc=excluded.ultima_tentativa_utc,
                ultima_atualizacao_sucesso_utc=excluded.ultima_atualizacao_sucesso_utc,
                proxima_execucao_utc=excluded.proxima_execucao_utc""",
                (fonte_id, fonte_tipo, frequencia, record["data_fim_utc"], last_success_at,
                 next_run.isoformat() if next_run else None))
        return record

    def get_last_success(self, fonte_id: str) -> Optional[Dict[str, Any]]:
        """Retorna a última execução bem-sucedida para uma fonte."""
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM execucoes WHERE fonte_id=? AND status IN ('SUCESSO','VAZIO') ORDER BY id DESC LIMIT 1", (fonte_id,)).fetchone()
            return dict(row) if row else None

    def get_last_attempt(self, fonte_id: str) -> Optional[Dict[str, Any]]:
        """Retorna a última tentativa (sucesso ou falha) para uma fonte."""
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM execucoes WHERE fonte_id=? ORDER BY id DESC LIMIT 1", (fonte_id,)).fetchone()
            return dict(row) if row else None

    def get_failed_sources(self) -> List[str]:
        """Retorna IDs das fontes cuja última execução foi uma falha."""
        records = self.get_records()
        last_by_fonte: Dict[str, Dict] = {}
        for r in records:
            fid = r.get("fonte_id")
            if fid:
                last_by_fonte[fid] = r

        return [
            fid for fid, r in last_by_fonte.items()
            if r.get("status", "").startswith(("FALHA", "REQUER_AUTENTICACAO"))
        ]

    def is_due_for_update(
        self, fonte_id: str, frequencia: str = "semanal"
    ) -> Tuple[bool, Optional[datetime], Optional[datetime]]:
        """
        Verifica se uma fonte precisa ser atualizada com base na frequência.
        Retorna (precisa_atualizar, ultima_coleta, proxima_coleta).
        """
        frequency = frequencia.lower()
        dias = FREQUENCIA_DIAS.get(frequency)

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

        if frequency in {"mensal", "trimestral"}:
            months = 1 if frequency == "mensal" else 3
            month_index = last_dt.year * 12 + last_dt.month - 1 + months
            year, month = divmod(month_index, 12)
            month += 1
            next_dt = last_dt.replace(year=year, month=month, day=min(last_dt.day, calendar.monthrange(year, month)[1]))
        else:
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

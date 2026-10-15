"""
Módulo de Configuração Central
Observatório de Políticas Públicas de Diadema (OPPES)

Carrega e valida as configurações do sistema a partir de config/sistema.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "fontes": {
        "metabase": {
            "frequencia": "semanal",
            "timeout": 25,
            "max_retries": 3,
            "delay_entre_cards": 0.3,
            "habilitado": True,
        },
        "google_sheets": {
            "frequencia": "semanal",
            "timeout": 45,
            "max_retries": 3,
            "habilitado": True,
        },
    },
    "frequencias_por_fonte": {},
    "geral": {
        "diretorio_dados": "data/raw",
        "diretorio_processados": "data/processed",
        "diretorio_historico": "data/history",
        "diretorio_logs": "logs",
        "diretorio_relatorios": "reports",
        "max_execucoes_concorrentes": 1,
        "reter_historico_dias": 90,
        "lockfile": "data/.lock_coleta",
    },
}


class SystemConfig:
    """Gerencia a configuração do sistema de automação."""

    def __init__(self, config_path: str | Path = "config/sistema.json"):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Carrega configuração do arquivo JSON ou usa defaults."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                logger.info("Configuração carregada de '%s'.", self.config_path)
            except Exception as err:
                logger.warning("Erro ao carregar configuração: %s. Usando defaults.", err)
                self._config = DEFAULT_CONFIG.copy()
        else:
            logger.info("Arquivo de configuração não encontrado. Usando defaults.")
            self._config = DEFAULT_CONFIG.copy()

    @property
    def geral(self) -> Dict[str, Any]:
        return self._config.get("geral", DEFAULT_CONFIG["geral"])

    @property
    def fontes(self) -> Dict[str, Any]:
        return self._config.get("fontes", DEFAULT_CONFIG["fontes"])

    @property
    def frequencias_por_fonte(self) -> Dict[str, Any]:
        return self._config.get("frequencias_por_fonte", {})

    def get_frequencia(self, fonte_id: str, tipo_fonte: str = "metabase") -> str:
        """Retorna a frequência configurada para uma fonte específica ou o padrão do tipo."""
        # Verificar configuração individual
        per_source = self.frequencias_por_fonte.get(fonte_id, {})
        if per_source.get("frequencia"):
            return per_source["frequencia"]

        # Usar configuração do tipo de fonte
        tipo_config = self.fontes.get(tipo_fonte, {})
        return tipo_config.get("frequencia", "semanal")

    def get_lockfile_path(self) -> Path:
        return Path(self.geral.get("lockfile", "data/.lock_coleta"))


class ExecutionLock:
    """Lock simples baseado em arquivo para evitar execuções concorrentes."""

    def __init__(self, lockfile: str | Path = "data/.lock_coleta"):
        self.lockfile = Path(lockfile)

    def acquire(self) -> bool:
        """Tenta adquirir o lock. Retorna True se bem-sucedido."""
        if self.lockfile.exists():
            try:
                content = self.lockfile.read_text(encoding="utf-8").strip()
                logger.warning("Lock já existe (PID %s). Execução concorrente bloqueada.", content)
            except Exception:
                pass
            return False

        try:
            self.lockfile.parent.mkdir(parents=True, exist_ok=True)
            self.lockfile.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except Exception as err:
            logger.error("Falha ao criar lockfile: %s", err)
            return False

    def release(self) -> None:
        """Libera o lock."""
        try:
            if self.lockfile.exists():
                self.lockfile.unlink()
        except Exception as err:
            logger.warning("Falha ao remover lockfile: %s", err)

    def is_locked(self) -> bool:
        return self.lockfile.exists()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Não foi possível adquirir o lock. Outra execução já está em andamento.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

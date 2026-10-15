"""
Motor de Coleta e Catálogo de Planilhas Google Sheets
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo orquestra a leitura da configuração de planilhas públicas,
execução segura via GoogleSheetsConnector e manutenção do catálogo de planilhas.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.connectors.google_sheets_connector import (
    GoogleSheetsConnector,
    GoogleSheetsError,
    extract_sheet_id_and_gid,
)

logger = logging.getLogger(__name__)


class GoogleSheetsHarvester:
    """Motor de coleta e manutenção de catálogo para planilhas públicas do Google Sheets."""

    DEFAULT_DATA_DIR = Path("data/raw/google_sheets")
    DEFAULT_CONFIG_PATH = Path("config/google_sheets.json")

    def __init__(
        self,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        timeout: float = 30.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ):
        self.data_dir = Path(data_dir)
        self.config_path = Path(config_path)
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def _get_catalog_paths(self) -> Tuple[Path, Path]:
        """Retorna caminhos do catálogo CSV e JSON para Google Sheets."""
        return (
            self.data_dir / "catalogo_sheets.csv",
            self.data_dir / "catalogo_sheets.json",
        )

    def load_configuration(self) -> List[Dict[str, Any]]:
        """Carrega lista de planilhas cadastradas a partir do arquivo JSON de configuração."""
        if not self.config_path.exists():
            logger.warning("Arquivo de configuração '%s' não encontrado. Retornando lista vazia.", self.config_path)
            return []

        try:
            with open(self.config_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    logger.info("Carregadas %d planilhas cadastradas em '%s'.", len(data), self.config_path)
                    return data
        except Exception as err:
            logger.error("Erro ao ler configuração de planilhas em '%s': %s", self.config_path, err)

        return []

    def load_existing_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Carrega catálogo existente indexado por 'fonte_id'."""
        _, json_path = self._get_catalog_paths()
        if not json_path.exists():
            return {}

        try:
            with open(json_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {item.get("fonte_id"): item for item in data if item.get("fonte_id")}
                elif isinstance(data, dict):
                    return data
        except Exception as err:
            logger.warning("Falha ao carregar catálogo existente de planilhas: %s", err)

        return {}

    def save_catalog(self, catalog_dict: Dict[str, Dict[str, Any]]) -> None:
        """Salva o catálogo em CSV e JSON com ordenação estável."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        csv_path, json_path = self._get_catalog_paths()

        items = list(catalog_dict.values())
        items.sort(key=lambda x: str(x.get("nome_fonte", "")))

        # Salvar JSON
        with open(json_path, mode="w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

        # Salvar CSV
        fieldnames = [
            "fonte_id",
            "tipo_fonte",
            "nome_fonte",
            "categoria",
            "fonte_primaria",
            "sheet_id",
            "gid",
            "url_original",
            "url_export",
            "data_coleta_utc",
            "status",
            "quantidade_linhas",
            "quantidade_colunas",
            "arquivo_csv",
            "mensagem",
        ]

        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for item in items:
                writer.writerow(item)

        logger.info("Catálogo de planilhas salvo com sucesso: %d registros em '%s'.", len(items), csv_path)

    def run_harvest(self, sheets_config: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Executa a coleta de todas as planilhas configuradas:
        1. Baixa e valida cada planilha pública
        2. Atualiza o catálogo
        3. Registra relatório analítico de execução
        """
        start_time = datetime.now(timezone.utc)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        catalog = self.load_existing_catalog()
        sheets = sheets_config if sheets_config is not None else self.load_configuration()

        stats = {
            "planilhas_cadastradas": len(sheets),
            "planilhas_tentadas": 0,
            "planilhas_sucesso": 0,
            "planilhas_vazias": 0,
            "planilhas_autenticacao": 0,
            "planilhas_falhas": 0,
            "tempo_total_segundos": 0.0,
            "inicio_utc": start_time.isoformat(),
            "fim_utc": None,
        }

        logger.info("Iniciando coleta de %d planilhas públicas do Google Sheets...", len(sheets))

        for idx, cfg in enumerate(sheets, start=1):
            stats["planilhas_tentadas"] += 1
            name = cfg.get("name") or cfg.get("nome", f"Planilha_{idx}")
            slug = cfg.get("id") or cfg.get("slug")
            url = cfg.get("url") or cfg.get("sheet_id")

            logger.info("[%d/%d] Processando planilha '%s'...", idx, len(sheets), name)

            connector = GoogleSheetsConnector(
                spreadsheet_url_or_id=url,
                gid=cfg.get("gid", "0"),
                name=name,
                category=cfg.get("categoria") or cfg.get("category"),
                primary_source=cfg.get("fonte_primaria") or cfg.get("primary_source"),
                timeout=self.timeout,
                max_retries=self.max_retries,
                session=self.session,
            )

            result = connector.collect(output_dir=self.data_dir, filename_slug=slug)
            catalog[result["fonte_id"]] = result

            st = result["status"]
            if st == "SUCESSO":
                stats["planilhas_sucesso"] += 1
            elif st == "VAZIO":
                stats["planilhas_vazias"] += 1
            elif st == "REQUER_AUTENTICACAO":
                stats["planilhas_autenticacao"] += 1
            else:
                stats["planilhas_falhas"] += 1

        self.save_catalog(catalog)

        end_time = datetime.now(timezone.utc)
        stats["fim_utc"] = end_time.isoformat()
        stats["tempo_total_segundos"] = round((end_time - start_time).total_seconds(), 2)

        return stats

"""
Orquestrador Unificado de Coleta de Dados (Unified Harvester)
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo integra e executa a coleta de fontes do Metabase e Google Sheets,
mantendo catálogos específicos e consolidando o Catálogo Geral do projeto.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.engine.metabase_harvester import MetabaseHarvester
from src.engine.sheets_harvester import GoogleSheetsHarvester

logger = logging.getLogger(__name__)


class UnifiedHarvester:
    """Orquestrador unificado para todas as fontes de dados do Observatório."""

    DEFAULT_BASE_DATA_DIR = Path("data/raw")

    def __init__(
        self,
        base_data_dir: str | Path = DEFAULT_BASE_DATA_DIR,
        inventory_path: Optional[str | Path] = None,
        sheets_config_path: Optional[str | Path] = None,
        delay_metabase: float = 0.2,
        timeout: float = 25.0,
    ):
        self.base_data_dir = Path(base_data_dir)
        self.inventory_path = Path(inventory_path) if inventory_path else Path("docs/inventario/inventario_fontes.csv")
        self.sheets_config_path = Path(sheets_config_path) if sheets_config_path else Path("config/google_sheets.json")

        self.metabase_data_dir = self.base_data_dir / "metabase"
        self.sheets_data_dir = self.base_data_dir / "google_sheets"

        self.metabase_harvester = MetabaseHarvester(
            data_dir=self.metabase_data_dir,
            timeout=timeout,
            request_delay=delay_metabase,
        )
        self.sheets_harvester = GoogleSheetsHarvester(
            data_dir=self.sheets_data_dir,
            config_path=self.sheets_config_path,
            timeout=timeout,
        )

    def run_metabase_only(self) -> Dict[str, Any]:
        """Executa apenas a coleta dos dashboards do Metabase."""
        return self.metabase_harvester.run_harvest(
            inventory_csv_path=self.inventory_path if self.inventory_path.exists() else None
        )

    def run_sheets_only(self) -> Dict[str, Any]:
        """Executa apenas a coleta das planilhas Google Sheets."""
        return self.sheets_harvester.run_harvest()

    def run_all(self, skip_metabase: bool = False, skip_sheets: bool = False) -> Dict[str, Any]:
        """
        Executa a coleta unificada: Metabase e/ou Google Sheets,
        e consolida o Catálogo Geral em data/raw/catalogo_geral.csv.
        """
        start_time = datetime.now(timezone.utc)
        results: Dict[str, Any] = {
            "inicio_utc": start_time.isoformat(),
            "fim_utc": None,
            "metabase_stats": None,
            "sheets_stats": None,
            "total_fontes_coletadas": 0,
            "total_sucessos": 0,
            "total_falhas": 0,
        }

        if not skip_metabase:
            logger.info(">>> Iniciando Coleta de Metabase...")
            results["metabase_stats"] = self.run_metabase_only()

        if not skip_sheets:
            logger.info(">>> Iniciando Coleta de Google Sheets...")
            results["sheets_stats"] = self.run_sheets_only()

        # Consolidar Catálogo Geral
        self.build_master_catalog()

        end_time = datetime.now(timezone.utc)
        results["fim_utc"] = end_time.isoformat()
        results["duracao_total_segundos"] = round((end_time - start_time).total_seconds(), 2)

        return results

    def build_master_catalog(self) -> Path:
        """
        Consolida os catálogos específicos (Metabase e Google Sheets)
        em um Catálogo Geral unificado em data/raw/catalogo_geral.csv.
        """
        self.base_data_dir.mkdir(parents=True, exist_ok=True)
        master_csv = self.base_data_dir / "catalogo_geral.csv"
        master_json = self.base_data_dir / "catalogo_geral.json"

        unified_records: List[Dict[str, Any]] = []

        # 1. Integrar registros do Metabase
        metabase_cat = self.metabase_harvester.load_existing_catalog()
        for k, item in metabase_cat.items():
            unified_records.append({
                "fonte_id": f"metabase_{item.get('card_id')}",
                "tipo_fonte": "Metabase Municipal",
                "nome_conjunto": item.get("card_name"),
                "categoria": item.get("dashboard_name"),
                "fonte_primaria": "Prefeitura de Diadema / DTIC (Metabase)",
                "data_coleta_utc": item.get("data_coleta_utc"),
                "status": item.get("status"),
                "quantidade_linhas": item.get("quantidade_linhas", 0),
                "quantidade_colunas": item.get("quantidade_colunas", 0),
                "arquivo_csv": item.get("arquivo_csv"),
                "mensagem": item.get("mensagem"),
            })

        # 2. Integrar registros do Google Sheets
        sheets_cat = self.sheets_harvester.load_existing_catalog()
        for k, item in sheets_cat.items():
            unified_records.append({
                "fonte_id": f"gsheet_{item.get('fonte_id')}",
                "tipo_fonte": "Google Sheets Pública",
                "nome_conjunto": item.get("nome_fonte"),
                "categoria": item.get("categoria"),
                "fonte_primaria": item.get("fonte_primaria"),
                "data_coleta_utc": item.get("data_coleta_utc"),
                "status": item.get("status"),
                "quantidade_linhas": item.get("quantidade_linhas", 0),
                "quantidade_colunas": item.get("quantidade_colunas", 0),
                "arquivo_csv": item.get("arquivo_csv"),
                "mensagem": item.get("mensagem"),
            })

        unified_records.sort(key=lambda x: (x.get("tipo_fonte", ""), x.get("nome_conjunto", "")))

        # Salvar JSON
        with open(master_json, mode="w", encoding="utf-8") as f:
            json.dump(unified_records, f, indent=2, ensure_ascii=False)

        # Salvar CSV
        fieldnames = [
            "fonte_id",
            "tipo_fonte",
            "nome_conjunto",
            "categoria",
            "fonte_primaria",
            "data_coleta_utc",
            "status",
            "quantidade_linhas",
            "quantidade_colunas",
            "arquivo_csv",
            "mensagem",
        ]

        with open(master_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in unified_records:
                writer.writerow(r)

        logger.info("Catálogo Geral consolidado com sucesso: %d fontes em '%s'.", len(unified_records), master_csv)
        return master_csv

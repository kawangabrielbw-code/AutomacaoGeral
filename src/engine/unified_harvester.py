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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.engine.metabase_harvester import MetabaseHarvester
from src.engine.sheets_harvester import GoogleSheetsHarvester
from src.engine.execution_history import ExecutionHistory

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
        only_source_ids: Optional[set[str]] = None,
    ):
        self.base_data_dir = Path(base_data_dir)
        self.inventory_path = Path(inventory_path) if inventory_path else Path("docs/inventario/inventario_fontes.csv")
        self.sheets_config_path = Path(sheets_config_path) if sheets_config_path else Path("config/google_sheets.json")
        self.only_source_ids = only_source_ids
        self.history = ExecutionHistory("data/history")
        self.lock_path = Path("data/.lock_coleta")

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
            inventory_csv_path=self.inventory_path if self.inventory_path.exists() else None,
            source_keys={key for key in self.only_source_ids if ":" in key} if self.only_source_ids is not None else None,
        )

    def run_sheets_only(self) -> Dict[str, Any]:
        """Executa apenas a coleta das planilhas Google Sheets."""
        sheets = self.sheets_harvester.load_configuration()
        if self.only_source_ids is not None:
            sheets = [s for s in sheets if str(s.get("id") or s.get("slug")) in self.only_source_ids]
        return self.sheets_harvester.run_harvest(sheets_config=sheets)

    def _record_catalog_history(self, category: str, catalog_path: Path, started: datetime) -> None:
        try:
            items = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if category == "metabase":
            try:
                frequency_config = json.loads(Path("config/metabase_cards.json").read_text(encoding="utf-8")).get("cards", {})
            except (OSError, ValueError):
                frequency_config = {}
            system_config = {}
        else:
            frequency_config = {}
            try:
                system_config = json.loads(Path("config/sistema.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                system_config = {}
        for item in items:
            stamp = item.get("data_coleta_utc") or ""
            try:
                if datetime.fromisoformat(stamp) < started:
                    continue
            except ValueError:
                continue
            fid = (f"{item.get('dashboard_uuid')}:{item.get('card_id')}" if category == "metabase"
                   else str(item.get("fonte_id") or item.get("card_id")))
            if category == "metabase":
                frequency = frequency_config.get(fid, {}).get("frequencia", "manual")
            else:
                item_key = f"gsheet_{fid}"
                frequency = system_config.get("frequencias_por_fonte", {}).get(item_key, {}).get(
                    "frequencia", system_config.get("fontes", {}).get("google_sheets", {}).get("frequencia", "semanal"))
            file_path = item.get("arquivo_csv")
            status = str(item.get("status", "FALHA"))
            self.history.add_execution(category, fid, status,
                int(item.get("quantidade_linhas") or 0), int(item.get("quantidade_colunas") or 0),
                mensagem=str(item.get("mensagem") or ""), arquivo_csv=file_path, frequencia=frequency)

    def run_all(self, skip_metabase: bool = False, skip_sheets: bool = False) -> Dict[str, Any]:
        """
        Executa a coleta unificada: Metabase e/ou Google Sheets,
        e consolida o Catálogo Geral em data/raw/catalogo_geral.csv.
        """
        start_time = datetime.now(timezone.utc)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {start_time.isoformat()}".encode())
            os.close(fd)
        except FileExistsError as exc:
            raise RuntimeError(f"Já existe uma coleta em andamento (lock: {self.lock_path}).") from exc
        results: Dict[str, Any] = {
            "inicio_utc": start_time.isoformat(),
            "fim_utc": None,
            "metabase_stats": None,
            "sheets_stats": None,
            "total_fontes_coletadas": 0,
            "total_sucessos": 0,
            "total_falhas": 0,
        }

        try:
            if not skip_metabase:
                logger.info(">>> Iniciando Coleta de Metabase...")
                results["metabase_stats"] = self.run_metabase_only()
                self._record_catalog_history("metabase", self.metabase_data_dir / "catalogo_metabase.json", start_time)
            if not skip_sheets:
                logger.info(">>> Iniciando Coleta de Google Sheets...")
                results["sheets_stats"] = self.run_sheets_only()
                self._record_catalog_history("sheets", self.sheets_data_dir / "catalogo_sheets.json", start_time)
            self.build_master_catalog()
            ms, ss = results.get("metabase_stats") or {}, results.get("sheets_stats") or {}
            results["total_sucessos"] = int(ms.get("cards_concluidos", 0)) + int(ss.get("planilhas_sucesso", 0))
            results["total_falhas"] = int(ms.get("cards_falhos", 0)) + int(ss.get("planilhas_falhas", 0)) + int(ss.get("planilhas_autenticacao", 0))
            results["total_fontes_coletadas"] = results["total_sucessos"] + results["total_falhas"] + int(ms.get("cards_vazios", 0)) + int(ss.get("planilhas_vazias", 0))
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

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

"""
Motor de Coleta e Atualização do Metabase (Metabase Harvester)
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo orquestra a descoberta dinâmica, coleta resiliente, exportação segura
e manutenção de catálogo para todos os cards públicos do Metabase municipal.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.connectors.metabase_card_connector import (
    MetabaseCardConnector,
    MetabaseConnectorError,
    MetabaseExportError,
    MetabaseHTTPError,
    MetabaseJSONError,
    MetabaseSchemaError,
    MetabaseTimeoutError,
)
from src.engine.metabase_discovery import (
    DashboardCardSpec,
    MetabaseDashboardDiscovery,
    slugify,
)

logger = logging.getLogger(__name__)


class MetabaseHarvester:
    """Motor de coleta e catálogo de datasets do Metabase municipal."""

    DEFAULT_DATA_DIR = Path("data/raw/metabase")

    def __init__(
        self,
        base_url: str = MetabaseDashboardDiscovery.DEFAULT_BASE_URL,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        timeout: float = 20.0,
        max_retries: int = 3,
        request_delay: float = 0.3,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.data_dir = Path(data_dir)
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = max(0.0, request_delay)
        self.session = session or requests.Session()
        self.discovery = MetabaseDashboardDiscovery(
            base_url=self.base_url,
            session=self.session,
            timeout=self.timeout,
        )

    def _get_catalog_paths(self) -> Tuple[Path, Path]:
        """Retorna os caminhos dos arquivos de catálogo CSV e JSON."""
        return (
            self.data_dir / "catalogo_metabase.csv",
            self.data_dir / "catalogo_metabase.json",
        )

    def load_existing_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Carrega o catálogo existente indexado pela chave composta '{dashboard_uuid}:{card_id}'."""
        _, json_path = self._get_catalog_paths()
        if not json_path.exists():
            return {}

        try:
            with open(json_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    catalog = {}
                    for item in data:
                        k = f"{item.get('dashboard_uuid')}:{item.get('card_id')}"
                        catalog[k] = item
                    return catalog
                elif isinstance(data, dict):
                    return data
        except Exception as err:
            logger.warning("Falha ao ler catálogo existente em '%s': %s", json_path, err)

        return {}

    def save_catalog(self, catalog_dict: Dict[str, Dict[str, Any]]) -> None:
        """Salva o catálogo em formatos CSV e JSON de maneira consistente e sem duplicações."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        csv_path, json_path = self._get_catalog_paths()

        items = list(catalog_dict.values())
        # Ordenar por nome de dashboard e card_id para estabilidade
        items.sort(key=lambda x: (x.get("dashboard_name", ""), int(x.get("card_id", 0)) if str(x.get("card_id", "")).isdigit() else 0))

        # Salvar JSON
        with open(json_path, mode="w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

        # Salvar CSV
        fieldnames = [
            "dashboard_uuid",
            "dashboard_name",
            "dashboard_slug",
            "dashcard_id",
            "card_id",
            "card_name",
            "display_type",
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

        logger.info("Catálogo atualizado com sucesso: %d registros em '%s'.", len(items), csv_path)

    def collect_single_card(self, card_spec: DashboardCardSpec) -> Dict[str, Any]:
        """
        Coleta um card específico com escrita atômica segura.
        Preserva arquivos válidos anteriores caso a nova requisição falhe.
        """
        dash_dir = self.data_dir / card_spec.dashboard_slug
        dash_dir.mkdir(parents=True, exist_ok=True)

        target_csv = dash_dir / f"card_{card_spec.card_id}_{card_spec.card_slug}.csv"
        temp_csv = dash_dir / f".tmp_card_{card_spec.card_id}.csv"

        now_utc = datetime.now(timezone.utc).isoformat()

        record: Dict[str, Any] = {
            "dashboard_uuid": card_spec.dashboard_uuid,
            "dashboard_name": card_spec.dashboard_name,
            "dashboard_slug": card_spec.dashboard_slug,
            "dashcard_id": card_spec.dashcard_id,
            "card_id": card_spec.card_id,
            "card_name": card_spec.card_name,
            "display_type": card_spec.display_type,
            "data_coleta_utc": now_utc,
            "status": "INICIADO",
            "quantidade_linhas": 0,
            "quantidade_colunas": 0,
            "arquivo_csv": str(target_csv) if target_csv.exists() else None,
            "mensagem": "",
        }

        connector = MetabaseCardConnector(
            dashboard_uuid=card_spec.dashboard_uuid,
            dashcard_id=card_spec.dashcard_id,
            card_id=card_spec.card_id,
            base_url=self.base_url,
            card_name=card_spec.card_name,
            timeout=self.timeout,
            max_retries=self.max_retries,
            session=self.session,
        )

        try:
            status_code, payload = connector.fetch_raw_data()
            columns, rows = connector.validate_payload(payload)

            record["quantidade_colunas"] = len(columns)
            record["quantidade_linhas"] = len(rows)

            # Gravar primeiro no arquivo temporário para garantir atomicidade
            connector.export_to_csv(columns, rows, temp_csv)

            # Se gravou com sucesso, substituir o arquivo alvo
            if temp_csv.exists():
                if target_csv.exists():
                    target_csv.unlink()
                temp_csv.rename(target_csv)

            record["arquivo_csv"] = str(target_csv.resolve())

            if len(rows) == 0:
                record["status"] = "VAZIO"
                record["mensagem"] = "Consulta retornou sem registros (zero linhas)."
            else:
                record["status"] = "SUCESSO"
                record["mensagem"] = f"Coleta realizada com sucesso (HTTP {status_code})."

        except Exception as err:
            logger.warning("Falha ao coletar card %s ('%s'): %s", card_spec.card_id, card_spec.card_name, err)
            record["status"] = f"FALHA: {type(err).__name__}"
            record["mensagem"] = str(err)
            # Limpar arquivo temporário se sobrou
            if temp_csv.exists():
                try:
                    temp_csv.unlink()
                except Exception:
                    pass

        return record

    def run_harvest(
        self,
        dashboard_uuids: Optional[List[str]] = None,
        inventory_csv_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """
        Executa a descoberta e coleta completa dos dashboards Metabase.
        Mantém o histórico e atualiza o catálogo sem duplicidade.
        """
        start_time = datetime.now(timezone.utc)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 1. Carregar catálogo existente
        catalog = self.load_existing_catalog()

        # 2. Identificar lista de dashboards
        if dashboard_uuids:
            dashboards_to_process = [{"uuid": u, "name": f"Dashboard_{u[:8]}"} for u in dashboard_uuids]
        elif inventory_csv_path:
            dashboards_to_process = MetabaseDashboardDiscovery.load_dashboards_from_inventory(inventory_csv_path)
        else:
            dashboards_to_process = MetabaseDashboardDiscovery.KNOWN_DASHBOARDS

        stats = {
            "dashboards_descobertos": len(dashboards_to_process),
            "cards_descobertos": 0,
            "cards_tentados": 0,
            "cards_concluidos": 0,
            "cards_vazios": 0,
            "cards_falhos": 0,
            "tempo_total_segundos": 0.0,
            "inicio_utc": start_time.isoformat(),
            "fim_utc": None,
        }

        all_discovered_cards: List[DashboardCardSpec] = []

        # 3. Fase de Descoberta Dinâmica
        logger.info("Iniciando fase de descoberta para %d dashboards...", len(dashboards_to_process))
        for d in dashboards_to_process:
            uuid = d["uuid"]
            dash_name, cards = self.discovery.discover_dashboard_cards(uuid)
            all_discovered_cards.extend(cards)

        stats["cards_descobertos"] = len(all_discovered_cards)
        logger.info("Total de cards descobertos dinamicamente: %d", len(all_discovered_cards))

        # 4. Fase de Coleta Sequencial Resiliente
        for idx, card_spec in enumerate(all_discovered_cards, start=1):
            stats["cards_tentados"] += 1
            logger.info(
                "[%d/%d] Processando Card %s (%s) do dashboard '%s'...",
                idx, len(all_discovered_cards), card_spec.card_id, card_spec.card_name, card_spec.dashboard_name
            )

            result = self.collect_single_card(card_spec)

            # Atualizar catálogo em memória
            key = f"{card_spec.dashboard_uuid}:{card_spec.card_id}"
            catalog[key] = result

            if result["status"] == "SUCESSO":
                stats["cards_concluidos"] += 1
            elif result["status"] == "VAZIO":
                stats["cards_vazios"] += 1
            else:
                stats["cards_falhos"] += 1

            # Respeitar limites razoáveis de requisição (polite rate limiting)
            if self.request_delay > 0 and idx < len(all_discovered_cards):
                time.sleep(self.request_delay)

        # 5. Salvar catálogo consolidado
        self.save_catalog(catalog)

        end_time = datetime.now(timezone.utc)
        stats["fim_utc"] = end_time.isoformat()
        stats["tempo_total_segundos"] = round((end_time - start_time).total_seconds(), 2)

        # 6. Gerar relatório resumido de execução
        self._write_harvest_report(stats, catalog)

        return stats

    def refresh_catalog_from_disk(self) -> int:
        """
        Inspeciona a estrutura existente de arquivos CSV em data/raw/metabase
        e reconstrói/atualiza o catálogo sem efetuar novas consultas HTTP.
        """
        logger.info("Atualizando catálogo a partir dos arquivos locais em '%s'...", self.data_dir)
        catalog = self.load_existing_catalog()

        csv_files = list(self.data_dir.glob("*/*.csv"))
        updated_count = 0

        for f in csv_files:
            # Padrão: card_{card_id}_{card_slug}.csv
            m = re.match(r"card_(\d+)_(.*)\.csv", f.name)
            if not m:
                continue

            card_id = m.group(1)
            dash_slug = f.parent.name

            # Contar linhas do CSV
            try:
                with open(f, mode="r", encoding="utf-8") as fp:
                    reader = list(csv.reader(fp))
                    col_count = len(reader[0]) if reader else 0
                    row_count = max(0, len(reader) - 1)
            except Exception:
                col_count = 0
                row_count = 0

            # Encontrar chave correspondente no catálogo ou criar entrada
            matched_key = None
            for k, item in catalog.items():
                if str(item.get("card_id")) == card_id and item.get("dashboard_slug") == dash_slug:
                    matched_key = k
                    break

            if matched_key:
                catalog[matched_key]["arquivo_csv"] = str(f.resolve())
                catalog[matched_key]["quantidade_linhas"] = row_count
                catalog[matched_key]["quantidade_colunas"] = col_count
            else:
                new_key = f"local:{card_id}"
                catalog[new_key] = {
                    "dashboard_uuid": "desconhecido",
                    "dashboard_name": dash_slug.replace("_", " ").title(),
                    "dashboard_slug": dash_slug,
                    "dashcard_id": "desconhecido",
                    "card_id": card_id,
                    "card_name": m.group(2).replace("_", " ").title(),
                    "display_type": "table",
                    "data_coleta_utc": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "status": "SUCESSO" if row_count > 0 else "VAZIO",
                    "quantidade_linhas": row_count,
                    "quantidade_colunas": col_count,
                    "arquivo_csv": str(f.resolve()),
                    "mensagem": "Catalogado a partir de arquivo local.",
                }
            updated_count += 1

        self.save_catalog(catalog)
        return updated_count

    def _write_harvest_report(self, stats: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> None:
        """Grava relatório em Markdown resumindo o resultado da coleta."""
        report_file = self.data_dir / "relatorio_coleta_metabase.md"

        falhas = [c for c in catalog.values() if "FALHA" in c.get("status", "")]
        sucessos = [c for c in catalog.values() if c.get("status") == "SUCESSO"]
        vazios = [c for c in catalog.values() if c.get("status") == "VAZIO"]

        falhas_md = "\n".join(
            f"- **Card {c.get('card_id')}** ({c.get('card_name')}) [Dashboard: {c.get('dashboard_name')}]: {c.get('mensagem')}"
            for c in falhas
        ) if falhas else "Nenhuma falha registrada."

        md = f"""# Relatório de Coleta do Metabase Municipal
**Data/Hora de Início (UTC):** `{stats['inicio_utc']}`  
**Data/Hora de Conclusão (UTC):** `{stats['fim_utc']}`  
**Duração Total:** `{stats['tempo_total_segundos']}s`  

---

## Estatísticas de Execução

| Indicador | Quantidade |
| :--- | :---: |
| **Dashboards Descobertos** | **{stats['dashboards_descobertos']}** |
| **Cards Descobertos Dinamicamente** | **{stats['cards_descobertos']}** |
| **Cards Tentados** | **{stats['cards_tentados']}** |
| **Cards Concluídos com Sucesso** | **{stats['cards_concluidos']}** |
| **Cards com Zero Registros (Vazio)** | **{stats['cards_vazios']}** |
| **Cards com Falhas/Erros** | **{stats['cards_falhos']}** |

---

## Detalhamento de Falhas e Limitações
{falhas_md}

---
*Relatório gerado automaticamente pelo MetabaseHarvester.*
"""
        report_file.write_text(md, encoding="utf-8")
        logger.info("Relatório de coleta gerado em '%s'.", report_file)

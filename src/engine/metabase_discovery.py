"""
Módulo de Descoberta Dinâmica de Cards do Metabase
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo inspeciona a definição pública de dashboards do Metabase
e descobre dinamicamente os cards analíticos consultáveis, sem necessidade
de codificação manual de IDs.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def slugify(text: str, max_length: int = 60) -> str:
    """Converte uma string em um slug legível e seguro para nomes de arquivo e diretório."""
    if not text:
        return "sem_nome"
    # Normalizar caracteres acentuados (ex: 'São' -> 'Sao')
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    # Substituir caracteres não-alfanuméricos por sublinhado
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_length] or "sem_nome"


@dataclass
class DashboardCardSpec:
    """Metadados de um card analítico descoberto em um dashboard Metabase."""
    dashboard_uuid: str
    dashboard_name: str
    dashboard_slug: str
    dashcard_id: str
    card_id: str
    card_name: str
    card_slug: str
    display_type: str
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetabaseDashboardDiscovery:
    """Descoberta dinâmica de cards disponíveis em dashboards públicos do Metabase."""

    DEFAULT_BASE_URL = "https://analytics.diadema.sp.gov.br"

    # Dashboards públicos identificados no inventário da Fase 1
    KNOWN_DASHBOARDS: List[Dict[str, str]] = [
        {"uuid": "67503054-df15-421c-b610-297d72b48bb5", "name": "BI Diadema (Censo IBGE 2022)"},
        {"uuid": "b28dfb2c-48d3-44bf-afce-05e82ca98294", "name": "BI Execução Orçamentária PPA"},
        {"uuid": "84393b4a-7570-49a0-8a7b-50ca560aa97c", "name": "BI Assistência Social"},
        {"uuid": "b01d1100-309d-4d18-b40d-c71e6416fb77", "name": "BI Atividade Econômica (ICMS)"},
        {"uuid": "38e0c61b-99ee-4711-b76e-3c6b435f5d72", "name": "BI CAGED Diadema"},
        {"uuid": "c536c790-6817-4d19-8065-ce1bb797db21", "name": "BI Orçamento TCESP"},
        {"uuid": "90a93a5d-d83e-4cc5-ba17-43d6a4c058c7", "name": "BI Pesquisa Satisfação Saúde"},
    ]

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    @classmethod
    def load_dashboards_from_inventory(cls, inventory_csv_path: str | Path) -> List[Dict[str, str]]:
        """Carrega os UUIDs de dashboards Metabase a partir do catálogo inventario_fontes.csv."""
        csv_file = Path(inventory_csv_path)
        if not csv_file.exists():
            logger.warning("Arquivo de inventário '%s' não encontrado. Usando dashboards padrão.", csv_file)
            return cls.KNOWN_DASHBOARDS

        dashboards: List[Dict[str, str]] = []
        seen_uuids = set()

        try:
            with open(csv_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("tecnologia_apresentacao") == "Metabase":
                        url_embed = row.get("url_embed_ou_acesso", "")
                        # Extrair UUID da URL (/dashboard/UUID)
                        m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", url_embed)
                        if m:
                            uuid = m.group(0).lower()
                            if uuid not in seen_uuids:
                                seen_uuids.add(uuid)
                                dashboards.append({
                                    "uuid": uuid,
                                    "name": row.get("nome_painel", f"Dashboard_{uuid[:8]}"),
                                })
            if dashboards:
                logger.info("Carregados %d dashboards Metabase do inventário CSV.", len(dashboards))
                return dashboards
        except Exception as err:
            logger.error("Erro ao ler inventário CSV '%s': %s. Usando lista padrão.", csv_file, err)

        return cls.KNOWN_DASHBOARDS

    def discover_dashboard_cards(self, dashboard_uuid: str) -> Tuple[str, List[DashboardCardSpec]]:
        """
        Consulta o endpoint de definição pública do dashboard e extrai a lista de cards queryáveis.
        Retorna (nome_dashboard, lista_de_cards).
        """
        uuid_clean = str(dashboard_uuid).strip()
        url = f"{self.base_url}/api/public/dashboard/{uuid_clean}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "ObservatorioDiadema-DataEngine/1.0",
        }

        logger.info("Descobrindo cards no dashboard %s: %s", uuid_clean, url)

        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            if response.status_code not in (200, 202):
                logger.error("Falha ao obter definição do dashboard %s (HTTP %d)", uuid_clean, response.status_code)
                return f"Dashboard_{uuid_clean[:8]}", []

            data = response.json()
        except Exception as err:
            logger.error("Erro na requisição do dashboard %s: %s", uuid_clean, err)
            return f"Dashboard_{uuid_clean[:8]}", []

        dash_name = data.get("name") or f"Dashboard_{uuid_clean[:8]}"
        dash_slug = slugify(dash_name)
        dashcards = data.get("dashcards", [])

        cards: List[DashboardCardSpec] = []

        for dc in dashcards:
            card_obj = dc.get("card")
            card_id = dc.get("card_id") or (card_obj.get("id") if isinstance(card_obj, dict) else None)
            dashcard_id = dc.get("id")

            # Filtrar cards virtuais / caixas de texto que não possuem dataset_query
            if not card_id or not card_obj or not isinstance(card_obj, dict):
                continue

            card_name = card_obj.get("name")
            if not card_name:
                continue

            card_slug = slugify(card_name)
            display_type = card_obj.get("display") or "table"
            description = card_obj.get("description")

            cards.append(
                DashboardCardSpec(
                    dashboard_uuid=uuid_clean,
                    dashboard_name=dash_name,
                    dashboard_slug=dash_slug,
                    dashcard_id=str(dashcard_id),
                    card_id=str(card_id),
                    card_name=card_name,
                    card_slug=card_slug,
                    display_type=display_type,
                    description=description,
                )
            )

        logger.info("Dashboard '%s' (%s): %d cards identificados.", dash_name, uuid_clean, len(cards))
        return dash_name, cards

    def discover_all(self, dashboard_uuids: Optional[List[str]] = None) -> Dict[str, List[DashboardCardSpec]]:
        """Descobre todos os cards disponíveis nos dashboards especificados ou conhecidos."""
        targets = dashboard_uuids or [d["uuid"] for d in self.KNOWN_DASHBOARDS]
        results: Dict[str, List[DashboardCardSpec]] = {}

        for uuid in targets:
            dash_name, cards = self.discover_dashboard_cards(uuid)
            results[uuid] = cards

        return results

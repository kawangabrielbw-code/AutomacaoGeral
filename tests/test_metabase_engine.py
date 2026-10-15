"""
Testes unitários automatizados para o motor de coleta e catálogo do Metabase.
Testa:
1. Descoberta dinâmica de cards e filtragem de cards virtuais.
2. Escrita segura e preservação de arquivos válidos existentes em caso de falha.
3. Continuidade da coleta quando um card falha.
4. Manutenção de catálogo sem duplicações em múltiplas execuções.
5. Atualização de catálogo a partir de arquivos em disco.
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from src.connectors.metabase_card_connector import MetabaseHTTPError
from src.engine.metabase_discovery import (
    DashboardCardSpec,
    MetabaseDashboardDiscovery,
    slugify,
)
from src.engine.metabase_harvester import MetabaseHarvester


class TestMetabaseEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

        self.mock_dashboard_payload = {
            "id": 100,
            "name": "Censo IBGE 2022 Diadema",
            "dashcards": [
                {
                    "id": 1088,
                    "card_id": 1052,
                    "card": {
                        "id": 1052,
                        "name": "População 2022 por Cor Raça",
                        "display": "pie",
                        "dataset_query": {"type": "query"},
                    },
                },
                {
                    # Card virtual de texto / sem card_id ou dataset_query
                    "id": 1092,
                    "card_id": None,
                    "card": {"dataset_query": None},
                    "visualization_settings": {"text": "Banner"},
                },
                {
                    "id": 1104,
                    "card_id": 1063,
                    "card": {
                        "id": 1063,
                        "name": "Dados dos 11 Bairros Oficiais de Diadema no Censo IBGE 2022",
                        "display": "table",
                        "dataset_query": {"type": "query"},
                    },
                },
            ],
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_slugify(self):
        """Testa a geração de slugs seguros para nomes de arquivos."""
        self.assertEqual(slugify("População 2022 por Cor Raça"), "populacao_2022_por_cor_raca")
        self.assertEqual(slugify("ATENÇÃO: Saúde & Família (PBF)"), "atencao_saude_familia_pbf")
        self.assertEqual(slugify(""), "sem_nome")

    def test_02_discover_dashboard_cards_filters_virtual(self):
        """Testa se a descoberta filtra cards virtuais e descobre cards válidos."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = self.mock_dashboard_payload
        mock_session.get.return_value = mock_response

        discovery = MetabaseDashboardDiscovery(session=mock_session)
        dash_name, cards = discovery.discover_dashboard_cards("67503054-df15-421c-b610-297d72b48bb5")

        self.assertEqual(dash_name, "Censo IBGE 2022 Diadema")
        # Devem ser 2 cards (o virtual com card_id None deve ser ignorado)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].card_id, "1052")
        self.assertEqual(cards[0].card_name, "População 2022 por Cor Raça")
        self.assertEqual(cards[1].card_id, "1063")

    def test_03_safe_write_preserves_valid_file_on_failure(self):
        """Testa se uma falha em nova consulta NÃO sobrescreve nem apaga o CSV válido anterior."""
        card_spec = DashboardCardSpec(
            dashboard_uuid="67503054-df15-421c-b610-297d72b48bb5",
            dashboard_name="Censo IBGE 2022 Diadema",
            dashboard_slug="censo_ibge_2022_diadema",
            dashcard_id="1104",
            card_id="1063",
            card_name="Dados dos 11 Bairros Oficiais",
            card_slug="dados_dos_11_bairros_oficiais",
            display_type="table",
        )

        dash_dir = self.data_dir / card_spec.dashboard_slug
        dash_dir.mkdir(parents=True, exist_ok=True)
        target_csv = dash_dir / f"card_{card_spec.card_id}_{card_spec.card_slug}.csv"
        # Criar CSV válido prévio
        target_csv.write_text("Bairros,Pop\nCentro,50000\n", encoding="utf-8")

        mock_session = MagicMock(spec=requests.Session)
        # Simular falha HTTP 500 no conector
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.get.return_value = mock_response

        harvester = MetabaseHarvester(data_dir=self.data_dir, session=mock_session, max_retries=1)
        res = harvester.collect_single_card(card_spec)

        self.assertIn("FALHA", res["status"])
        # O arquivo original DEVE permanecer intacto
        self.assertTrue(target_csv.exists())
        self.assertEqual(target_csv.read_text(encoding="utf-8"), "Bairros,Pop\nCentro,50000\n")

    def test_04_continuity_when_card_fails(self):
        """Testa se a falha em um card não interrompe a coleta dos demais cards."""
        card1 = DashboardCardSpec(
            dashboard_uuid="uuid-1",
            dashboard_name="Dash 1",
            dashboard_slug="dash_1",
            dashcard_id="101",
            card_id="1",
            card_name="Card Falho",
            card_slug="card_falho",
            display_type="table",
        )
        card2 = DashboardCardSpec(
            dashboard_uuid="uuid-1",
            dashboard_name="Dash 1",
            dashboard_slug="dash_1",
            dashcard_id="102",
            card_id="2",
            card_name="Card Sucesso",
            card_slug="card_sucesso",
            display_type="table",
        )

        harvester = MetabaseHarvester(data_dir=self.data_dir, request_delay=0)

        # Mock discovery para retornar ambos os cards
        harvester.discovery.discover_dashboard_cards = MagicMock(return_value=("Dash 1", [card1, card2]))

        # Mock collect_single_card para falhar no card1 e ter sucesso no card2
        def mock_collect(spec):
            if spec.card_id == "1":
                return {
                    "dashboard_uuid": spec.dashboard_uuid,
                    "card_id": spec.card_id,
                    "card_name": spec.card_name,
                    "status": "FALHA: MetabaseHTTPError",
                    "quantidade_linhas": 0,
                    "quantidade_colunas": 0,
                    "arquivo_csv": None,
                    "mensagem": "HTTP 404",
                }
            return {
                "dashboard_uuid": spec.dashboard_uuid,
                "card_id": spec.card_id,
                "card_name": spec.card_name,
                "status": "SUCESSO",
                "quantidade_linhas": 10,
                "quantidade_colunas": 3,
                "arquivo_csv": "/path/to/card_2.csv",
                "mensagem": "Sucesso",
            }

        harvester.collect_single_card = MagicMock(side_effect=mock_collect)

        stats = harvester.run_harvest(dashboard_uuids=["uuid-1"])

        self.assertEqual(stats["cards_tentados"], 2)
        self.assertEqual(stats["cards_concluidos"], 1)
        self.assertEqual(stats["cards_falhos"], 1)

        # Catálogo deve conter ambos os cards
        catalog = harvester.load_existing_catalog()
        self.assertIn("uuid-1:1", catalog)
        self.assertIn("uuid-1:2", catalog)
        self.assertEqual(catalog["uuid-1:1"]["status"], "FALHA: MetabaseHTTPError")
        self.assertEqual(catalog["uuid-1:2"]["status"], "SUCESSO")

    def test_05_catalog_no_duplication_on_rerun(self):
        """Testa se reexecuções atualizam os registros sem gerar duplicações no CSV de catálogo."""
        harvester = MetabaseHarvester(data_dir=self.data_dir)

        item1 = {
            "dashboard_uuid": "u1",
            "dashboard_name": "D1",
            "dashcard_id": "10",
            "card_id": "1",
            "card_name": "C1",
            "status": "SUCESSO",
            "quantidade_linhas": 5,
        }
        # Salvar primeira vez
        harvester.save_catalog({"u1:1": item1})

        # Atualizar registro na segunda vez
        item1_updated = dict(item1)
        item1_updated["quantidade_linhas"] = 6
        harvester.save_catalog({"u1:1": item1_updated})

        csv_path, _ = harvester._get_catalog_paths()
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            # Deve conter exatamente 1 linha de dados (sem duplicação)
            self.assertEqual(len(reader), 1)
            self.assertEqual(reader[0]["quantidade_linhas"], "6")

    def test_06_refresh_catalog_from_disk(self):
        """Testa reconstrução do catálogo a partir de arquivos CSV existentes em disco."""
        dash_dir = self.data_dir / "censo_ibge_2022"
        dash_dir.mkdir(parents=True, exist_ok=True)
        csv_file = dash_dir / "card_1063_dados_bairros.csv"
        csv_file.write_text("Col1,Col2,Col3\nVal1,Val2,Val3\nVal4,Val5,Val6\n", encoding="utf-8")

        harvester = MetabaseHarvester(data_dir=self.data_dir)
        count = harvester.refresh_catalog_from_disk()

        self.assertEqual(count, 1)
        catalog = harvester.load_existing_catalog()
        self.assertEqual(len(catalog), 1)
        first_entry = list(catalog.values())[0]
        self.assertEqual(first_entry["card_id"], "1063")
        self.assertEqual(first_entry["quantidade_linhas"], 2)
        self.assertEqual(first_entry["quantidade_colunas"], 3)


if __name__ == "__main__":
    unittest.main()

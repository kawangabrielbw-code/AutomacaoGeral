"""
Testes automatizados para o conector Metabase (MetabaseCardConnector).
Cobre os 7 cenários obrigatórios definidos na Fase 2A:
1. Resposta JSON válida com dados.
2. Resposta JSON válida sem registros.
3. Erro HTTP.
4. Timeout.
5. JSON inválido.
6. Estrutura sem as colunas ou linhas esperadas.
7. Falha na gravação do CSV.
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Garantir que a raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


class TestMetabaseCardConnector(unittest.TestCase):

    def setUp(self):
        self.dashboard_uuid = "67503054-df15-421c-b610-297d72b48bb5"
        self.dashcard_id = 1104
        self.card_id = 1063
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

        self.valid_payload = {
            "data": {
                "cols": [
                    {"name": "Bairros", "display_name": "Bairros"},
                    {"name": "pop_2022", "display_name": "População 2022"},
                    {"name": "rend_per_capita", "display_name": "Rendimento Médio Per Capita (R$)"},
                ],
                "rows": [
                    ["Centro", 53748.0, 2807.74],
                    ["Campanário", 29403.0, 1850.20],
                    ["Taboão", 46546.0, 2100.50],
                ],
            },
            "status": "completed",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_valid_json_with_data(self):
        """Cenário 1: Resposta JSON válida com dados."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json; charset=utf-8"}
        mock_response.json.return_value = self.valid_payload
        mock_session.get.return_value = mock_response

        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
            session=mock_session,
        )

        report = connector.run(output_dir=self.output_dir, filename_prefix="teste_valido")

        self.assertEqual(report["resultado_validacao"], "SUCESSO")
        self.assertEqual(report["quantidade_colunas"], 3)
        self.assertEqual(report["quantidade_linhas"], 3)
        self.assertEqual(
            report["nomes_colunas"],
            ["Bairros", "População 2022", "Rendimento Médio Per Capita (R$)"],
        )

        # Verificar se o CSV foi gerado e conferir conteúdo
        csv_path = Path(report["arquivo_csv_gerado"])
        self.assertTrue(csv_path.exists())
        with open(csv_path, encoding="utf-8") as f:
            reader = list(csv.reader(f))
            self.assertEqual(len(reader), 4)  # 1 cabeçalho + 3 linhas
            self.assertEqual(reader[1][0], "Centro")

    def test_02_valid_json_empty_records(self):
        """Cenário 2: Resposta JSON válida sem registros (rows = [])."""
        empty_payload = {
            "data": {
                "cols": [
                    {"name": "col1", "display_name": "Coluna 1"},
                    {"name": "col2", "display_name": "Coluna 2"},
                ],
                "rows": [],
            }
        }
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = empty_payload
        mock_session.get.return_value = mock_response

        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
            session=mock_session,
        )

        report = connector.run(output_dir=self.output_dir, filename_prefix="teste_vazio")

        self.assertEqual(report["resultado_validacao"], "SUCESSO")
        self.assertEqual(report["quantidade_colunas"], 2)
        self.assertEqual(report["quantidade_linhas"], 0)
        self.assertTrue(any("zero linhas" in aviso for aviso in report["avisos"]))

        # Verificar se o CSV foi gerado com apenas o cabeçalho
        csv_path = Path(report["arquivo_csv_gerado"])
        self.assertTrue(csv_path.exists())
        with open(csv_path, encoding="utf-8") as f:
            reader = list(csv.reader(f))
            self.assertEqual(len(reader), 1)  # apenas cabeçalho
            self.assertEqual(reader[0], ["Coluna 1", "Coluna 2"])

    def test_03_http_error(self):
        """Cenário 3: Erro HTTP (ex.: 404 Not Found ou 500 Server Error)."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 404
        mock_response.text = "O endpoint da API não existe."
        mock_session.get.return_value = mock_response

        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
            session=mock_session,
            max_retries=1,
        )

        with self.assertRaises(MetabaseHTTPError) as ctx:
            connector.fetch_raw_data()
        self.assertEqual(ctx.exception.status_code, 404)

        report = connector.run(output_dir=self.output_dir, filename_prefix="teste_404")
        self.assertIn("MetabaseHTTPError", report["resultado_validacao"])
        self.assertTrue(len(report["erros"]) > 0)

    def test_04_timeout(self):
        """Cenário 4: Falha de timeout na requisição."""
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out")

        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
            timeout=2.0,
            max_retries=2,
            session=mock_session,
        )

        with self.assertRaises(MetabaseTimeoutError):
            connector.fetch_raw_data()

        # O run deve capturar o erro e documentar no relatório
        report = connector.run(output_dir=self.output_dir, filename_prefix="teste_timeout")
        self.assertIn("MetabaseTimeoutError", report["resultado_validacao"])
        self.assertTrue(len(report["erros"]) > 0)

    def test_05_invalid_json(self):
        """Cenário 5: Resposta não é um JSON válido ou Content-Type incorreto."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_response.text = "<html><body>502 Bad Gateway</body></html>"
        mock_session.get.return_value = mock_response

        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
            session=mock_session,
            max_retries=1,
        )

        with self.assertRaises(MetabaseJSONError):
            connector.fetch_raw_data()

        report = connector.run(output_dir=self.output_dir, filename_prefix="teste_json_invalido")
        self.assertIn("MetabaseJSONError", report["resultado_validacao"])

    def test_06_missing_expected_structure(self):
        """Cenário 6: Estrutura JSON sem as colunas ou linhas esperadas."""
        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
        )

        # Caso 6A: payload sem chave 'data'
        with self.assertRaises(MetabaseSchemaError) as ctx:
            connector.validate_payload({"status": "failed"})
        self.assertIn("'data'", str(ctx.exception))

        # Caso 6B: 'data' sem 'cols'
        with self.assertRaises(MetabaseSchemaError) as ctx:
            connector.validate_payload({"data": {"rows": []}})
        self.assertIn("'cols'", str(ctx.exception))

        # Caso 6C: 'data' sem 'rows'
        with self.assertRaises(MetabaseSchemaError) as ctx:
            connector.validate_payload({"data": {"cols": [{"name": "col1"}]}})
        self.assertIn("'rows'", str(ctx.exception))

        # Caso 6D: payload não é dict
        with self.assertRaises(MetabaseSchemaError):
            connector.validate_payload(["not", "a", "dict"])

    def test_07_csv_export_failure(self):
        """Cenário 7: Falha na gravação do CSV (ex.: caminho inválido ou permissão)."""
        connector = MetabaseCardConnector(
            dashboard_uuid=self.dashboard_uuid,
            dashcard_id=self.dashcard_id,
            card_id=self.card_id,
        )

        cols = ["Col1", "Col2"]
        rows = [["Val1", "Val2"]]

        # Simular OSError ao abrir o arquivo para gravação
        with patch("builtins.open", side_effect=OSError("Permissão negada (simulado)")):
            with self.assertRaises(MetabaseExportError) as ctx:
                connector.export_to_csv(cols, rows, self.output_dir / "falha.csv")
            self.assertIn("Permissão negada", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

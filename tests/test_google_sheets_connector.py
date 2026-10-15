"""
Testes unitários automatizados para o conector Google Sheets (GoogleSheetsConnector)
e o orquestrador de planilhas (GoogleSheetsHarvester).
Cobre:
1. Extração correta de IDs e GIDs de URLs diversas.
2. Download e validação de CSV válido com preservação de nulos.
3. Tratamento de planilha válida com 0 linhas (apenas cabeçalho).
4. Tratamento de erro HTTP (ex.: 404/500).
5. Detecção de exigência de autenticação Google (redirecionamento para login).
6. Timeout e retentativas controladas.
7. Escrita segura atômica (preserva arquivo prévio em caso de falha).
8. Adição de novas planilhas via configuração dinâmica.
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from src.connectors.google_sheets_connector import (
    GoogleSheetsAuthRequiredError,
    GoogleSheetsConnector,
    GoogleSheetsError,
    GoogleSheetsHTTPError,
    GoogleSheetsTimeoutError,
    GoogleSheetsValidationError,
    extract_sheet_id_and_gid,
)
from src.engine.sheets_harvester import GoogleSheetsHarvester


class TestGoogleSheetsConnector(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.valid_csv_text = (
            "id_sinistro,municipio,tipo_via,vitimas,data_sinistro\n"
            "1001,Diadema,Rodovia,1,2025-01-10\n"
            "1002,Diadema,Municipal,,2025-01-12\n"  # campo vazio preservado
            "1003,Diadema,Avenida,0,2025-01-15\n"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_extract_sheet_id_and_gid(self):
        """Testa a extração de ID e GID de múltiplos formatos de URLs do Google Sheets."""
        url1 = "https://docs.google.com/spreadsheets/d/1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY/edit?usp=sharing"
        sheet_id, gid = extract_sheet_id_and_gid(url1)
        self.assertEqual(sheet_id, "1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY")
        self.assertEqual(gid, "0")

        url2 = "https://docs.google.com/spreadsheets/d/1FRXI-muwyjka7FUK-TG47qJ3dPjJlo-8pIsQDL1a2jw/edit#gid=987654"
        sheet_id2, gid2 = extract_sheet_id_and_gid(url2)
        self.assertEqual(sheet_id2, "1FRXI-muwyjka7FUK-TG47qJ3dPjJlo-8pIsQDL1a2jw")
        self.assertEqual(gid2, "987654")

        raw_id = "1yrDtIFcbxtVgen0OOMcvV_mK0G4c52El"
        sheet_id3, gid3 = extract_sheet_id_and_gid(raw_id)
        self.assertEqual(sheet_id3, raw_id)
        self.assertEqual(gid3, "0")

        with self.assertRaises(ValueError):
            extract_sheet_id_and_gid("http://site-invalido.com/arquivo.csv")

    def test_02_download_valid_csv(self):
        """Testa o download e validação de CSV válido com preservação de nulos."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.url = "https://docs.google.com/spreadsheets/d/test/export?format=csv"
        mock_response.text = self.valid_csv_text
        mock_session.get.return_value = mock_response

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            name="Sinistros de Trânsito",
            session=mock_session,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="teste_sinistros")

        self.assertEqual(record["status"], "SUCESSO")
        self.assertEqual(record["quantidade_colunas"], 5)
        self.assertEqual(record["quantidade_linhas"], 3)
        self.assertIn("id_sinistro", record["nomes_colunas"])

        # Verificar se o arquivo foi gravado e preservou o valor vazio na linha 2
        csv_file = Path(record["arquivo_csv"])
        self.assertTrue(csv_file.exists())
        with open(csv_file, encoding="utf-8") as fp:
            rows = list(csv.reader(fp))
            self.assertEqual(len(rows), 4)  # 1 cabeçalho + 3 linhas
            self.assertEqual(rows[2][3], "")  # campo nulo mantido vazio, sem zero inventado

    def test_03_download_empty_csv(self):
        """Testa planilha válida contendo apenas cabeçalho e zero linhas de dados."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.url = "https://docs.google.com/spreadsheets/d/test/export?format=csv"
        mock_response.text = "col1,col2,col3\n"
        mock_session.get.return_value = mock_response

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            session=mock_session,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="teste_vazio")
        self.assertEqual(record["status"], "VAZIO")
        self.assertEqual(record["quantidade_linhas"], 0)
        self.assertEqual(record["quantidade_colunas"], 3)

    def test_04_http_error(self):
        """Testa tratamento de erro HTTP 404."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 404
        mock_response.url = "https://docs.google.com/spreadsheets/d/invalido/export"
        mock_response.text = "Not Found"
        mock_session.get.return_value = mock_response

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            session=mock_session,
            max_retries=1,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="teste_404")
        self.assertIn("FALHA", record["status"])
        self.assertIn("404", record["mensagem"])

    def test_05_auth_required_detection(self):
        """Testa a detecção de barreira de autenticação (redirecionamento para login do Google)."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        # Simula redirecionamento para o ServiceLogin do Google
        mock_response.url = "https://accounts.google.com/ServiceLogin?service=wise"
        mock_response.text = "<!DOCTYPE html><html><body>Fazer login no Google</body></html>"
        mock_session.get.return_value = mock_response

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            name="Planilha Restrita",
            session=mock_session,
            max_retries=1,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="teste_privado")
        self.assertEqual(record["status"], "REQUER_AUTENTICACAO")
        self.assertIn("login", record["mensagem"].lower())

    def test_06_timeout_handling(self):
        """Testa falha de timeout com retentativas."""
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = requests.exceptions.Timeout("Read timeout")

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            timeout=2.0,
            max_retries=2,
            session=mock_session,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="teste_timeout")
        self.assertIn("FALHA", record["status"])
        self.assertIn("GoogleSheetsTimeoutError", record["status"])

    def test_07_safe_export_preserves_valid_file_on_failure(self):
        """Testa se uma falha em nova tentativa NÃO sobrescreve o CSV válido pré-existente."""
        target_csv = self.output_dir / "planilha_estavel.csv"
        target_csv.write_text("a,b\n1,2\n", encoding="utf-8")

        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.url = "https://docs.google.com/spreadsheets/d/test/export"
        mock_response.text = "Internal Server Error"
        mock_session.get.return_value = mock_response

        connector = GoogleSheetsConnector(
            spreadsheet_url_or_id="1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",
            session=mock_session,
            max_retries=1,
        )

        record = connector.collect(output_dir=self.output_dir, filename_slug="planilha_estavel")
        self.assertIn("FALHA", record["status"])
        # O arquivo original deve permanecer intacto
        self.assertTrue(target_csv.exists())
        self.assertEqual(target_csv.read_text(encoding="utf-8"), "a,b\n1,2\n")

    def test_08_add_new_sheet_by_configuration(self):
        """Testa adição de novas planilhas via configuração dinâmica sem alterar o conector."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.url = "https://docs.google.com/spreadsheets/d/nova/export"
        mock_response.text = "cidade,populacao\nDiadema,393237\n"
        mock_session.get.return_value = mock_response

        custom_config = [
            {
                "id": "nova_planilha_customizada",
                "name": "Nova Planilha Dinâmica",
                "url": "https://docs.google.com/spreadsheets/d/nova_planilha_id/edit",
                "gid": "0",
            }
        ]

        harvester = GoogleSheetsHarvester(data_dir=self.output_dir, session=mock_session)
        stats = harvester.run_harvest(sheets_config=custom_config)

        self.assertEqual(stats["planilhas_cadastradas"], 1)
        self.assertEqual(stats["planilhas_sucesso"], 1)

        catalog = harvester.load_existing_catalog()
        self.assertIn("nova_planilha_customizada", catalog)
        self.assertEqual(catalog["nova_planilha_customizada"]["status"], "SUCESSO")
        self.assertEqual(catalog["nova_planilha_customizada"]["quantidade_linhas"], 1)


if __name__ == "__main__":
    unittest.main()

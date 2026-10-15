"""
Metabase Public Card Connector
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo implementa a consulta controlada, validação estrutural e exportação tabular
de dados provenientes de cards públicos disponibilizados na instância Metabase
da Prefeitura de Diadema (analytics.diadema.sp.gov.br).
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class MetabaseConnectorError(Exception):
    """Exceção base para erros do conector Metabase."""
    pass


class MetabaseHTTPError(MetabaseConnectorError):
    """Erro retornado em falhas de requisição HTTP (ex.: 404, 500)."""
    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class MetabaseTimeoutError(MetabaseConnectorError):
    """Erro lançado quando o tempo limite de requisição é excedido."""
    pass


class MetabaseJSONError(MetabaseConnectorError):
    """Erro lançado quando a resposta não é um JSON válido ou Content-Type incorreto."""
    pass


class MetabaseSchemaError(MetabaseConnectorError):
    """Erro lançado quando o schema retornado não contém as chaves obrigatórias."""
    pass


class MetabaseExportError(MetabaseConnectorError):
    """Erro lançado em falha ao gravar o arquivo CSV ou gerar o relatório."""
    pass


class MetabaseCardConnector:
    """
    Conector robusto para consulta e extração de dados tabulares de um card público do Metabase.

    Padrão de URL consumido:
    {base_url}/api/public/dashboard/{dashboard_uuid}/dashcard/{dashcard_id}/card/{card_id}
    """

    DEFAULT_BASE_URL = "https://analytics.diadema.sp.gov.br"

    def __init__(
        self,
        dashboard_uuid: str,
        dashcard_id: int | str,
        card_id: int | str,
        base_url: str = DEFAULT_BASE_URL,
        card_name: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        session: Optional[requests.Session] = None,
    ):
        if not dashboard_uuid:
            raise ValueError("dashboard_uuid é obrigatório.")
        if not dashcard_id:
            raise ValueError("dashcard_id é obrigatório.")
        if not card_id:
            raise ValueError("card_id é obrigatório.")

        self.dashboard_uuid = str(dashboard_uuid).strip()
        self.dashcard_id = str(dashcard_id).strip()
        self.card_id = str(card_id).strip()
        self.base_url = base_url.rstrip("/")
        self.card_name = card_name or f"Card_{self.card_id}"
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.retry_delay = retry_delay
        self.session = session or requests.Session()

    def get_url(self) -> str:
        """Retorna a URL pública canônica do card."""
        return (
            f"{self.base_url}/api/public/dashboard/"
            f"{self.dashboard_uuid}/dashcard/{self.dashcard_id}/card/{self.card_id}"
        )

    def fetch_raw_data(self) -> Tuple[int, Dict[str, Any]]:
        """
        Executa a requisição HTTP com tentativas controladas para erros transitórios.
        Retorna o código de status HTTP e o dicionário JSON decodificado.
        """
        url = self.get_url()
        headers = {
            "Accept": "application/json",
            "User-Agent": "ObservatorioDiadema-DataConnector/1.0",
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            logger.info("Consultando Metabase [Tentativa %d/%d]: %s", attempt, self.max_retries, url)
            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout)

                # Validar status HTTP
                if response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Status HTTP transitório %d recebido na tentativa %d.",
                        response.status_code, attempt
                    )
                    last_error = MetabaseHTTPError(response.status_code, response.text)
                    if attempt < self.max_retries:
                        continue
                    raise last_error

                if response.status_code not in (200, 202):
                    raise MetabaseHTTPError(response.status_code, response.text)

                # Validar Content-Type
                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type.lower():
                    raise MetabaseJSONError(
                        f"Content-Type inesperado: '{content_type}'. Esperado 'application/json'."
                    )

                try:
                    payload = response.json()
                except Exception as err:
                    raise MetabaseJSONError(f"Falha ao decodificar JSON de resposta: {err}") from err

                return response.status_code, payload

            except requests.exceptions.Timeout as err:
                logger.warning("Timeout na tentativa %d para URL: %s", attempt, url)
                last_error = MetabaseTimeoutError(f"Timeout de {self.timeout}s excedido: {err}")
                if attempt >= self.max_retries:
                    raise last_error
            except requests.exceptions.ConnectionError as err:
                logger.warning("Falha de conexão na tentativa %d para URL: %s", attempt, url)
                last_error = MetabaseConnectorError(f"Falha de conexão: {err}")
                if attempt >= self.max_retries:
                    raise last_error

        if last_error:
            raise last_error
        raise MetabaseConnectorError("Falha desconhecida durante a consulta.")

    def validate_payload(self, payload: Any) -> Tuple[List[str], List[List[Any]]]:
        """
        Valida a estrutura do JSON recebido.
        Verifica a presença das chaves 'data', 'cols' e 'rows'.
        Retorna (lista_colunas, lista_linhas).
        """
        if not isinstance(payload, dict):
            raise MetabaseSchemaError(
                f"Payload de resposta inválido: esperado objeto JSON (dict), recebido {type(payload).__name__}."
            )

        if "data" not in payload or not isinstance(payload["data"], dict):
            raise MetabaseSchemaError(
                "Chave obrigatória 'data' ausente ou não é um objeto no payload do Metabase."
            )

        data_obj = payload["data"]

        if "cols" not in data_obj or not isinstance(data_obj["cols"], list):
            raise MetabaseSchemaError(
                "Chave 'cols' ausente ou inválida dentro de 'data'."
            )

        if "rows" not in data_obj or not isinstance(data_obj["rows"], list):
            raise MetabaseSchemaError(
                "Chave 'rows' ausente ou inválida dentro de 'data'."
            )

        cols_list = data_obj["cols"]
        rows_list = data_obj["rows"]

        # Extrair nomes legíveis de colunas
        columns: List[str] = []
        for idx, col in enumerate(cols_list):
            if isinstance(col, dict):
                col_name = col.get("display_name") or col.get("name") or f"coluna_{idx+1}"
            else:
                col_name = str(col)
            columns.append(str(col_name).strip())

        return columns, rows_list

    def export_to_csv(
        self,
        columns: List[str],
        rows: List[List[Any]],
        output_file: str | Path,
    ) -> Path:
        """
        Exporta os dados validados para um arquivo CSV formatado em UTF-8.
        Não inventa colunas e preserva valores ausentes (None) como vazios.
        """
        out_path = Path(output_file)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(columns)
                for row in rows:
                    # Preservar None como string vazia sem forçar zero
                    clean_row = ["" if v is None else v for v in row]
                    writer.writerow(clean_row)
            logger.info("CSV exportado com sucesso: %s (%d registros)", out_path, len(rows))
            return out_path
        except Exception as err:
            raise MetabaseExportError(f"Erro ao exportar CSV para '{out_path}': {err}") from err

    def run(self, output_dir: str | Path, filename_prefix: Optional[str] = None) -> Dict[str, Any]:
        """
        Executa o fluxo completo do conector:
        1. Consulta o endpoint
        2. Valida o schema e os dados
        3. Exporta para CSV
        4. Gera relatório de execução detalhado
        """
        start_time = datetime.now(timezone.utc)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        prefix = filename_prefix or f"card_{self.card_id}"
        csv_file = out_dir / f"{prefix}.csv"
        report_file = out_dir / f"{prefix}_relatorio.md"

        report: Dict[str, Any] = {
            "card_id": self.card_id,
            "dashcard_id": self.dashcard_id,
            "dashboard_uuid": self.dashboard_uuid,
            "card_name": self.card_name,
            "url_consultada": self.get_url(),
            "data_hora_consulta_utc": start_time.isoformat(),
            "status_http": None,
            "quantidade_colunas": 0,
            "nomes_colunas": [],
            "quantidade_linhas": 0,
            "arquivo_csv_gerado": None,
            "resultado_validacao": "FALHA",
            "avisos": [],
            "erros": [],
        }

        try:
            status_code, payload = self.fetch_raw_data()
            report["status_http"] = status_code

            columns, rows = self.validate_payload(payload)
            report["quantidade_colunas"] = len(columns)
            report["nomes_colunas"] = columns
            report["quantidade_linhas"] = len(rows)

            if len(rows) == 0:
                report["avisos"].append("A consulta retornou um conjunto de dados vazio (zero linhas).")

            csv_path = self.export_to_csv(columns, rows, csv_file)
            report["arquivo_csv_gerado"] = str(csv_path.resolve())
            report["resultado_validacao"] = "SUCESSO"

        except Exception as err:
            logger.error("Erro durante execução do conector: %s", err)
            report["erros"].append(str(err))
            report["resultado_validacao"] = f"ERRO: {type(err).__name__}"

        # Gravar relatório de execução em markdown
        self._write_execution_report(report, report_file)
        report["arquivo_relatorio_gerado"] = str(report_file.resolve())

        return report

    def _write_execution_report(self, report: Dict[str, Any], report_path: Path) -> None:
        """Gera o arquivo markdown do relatório de execução."""
        cols_formatted = ", ".join(f"`{c}`" for c in report["nomes_colunas"]) if report["nomes_colunas"] else "Nenhuma"
        avisos_txt = "\n".join(f"- ⚠️ {a}" for a in report["avisos"]) if report["avisos"] else "Nenhum aviso."
        erros_txt = "\n".join(f"- ❌ {e}" for e in report["erros"]) if report["erros"] else "Nenhum erro registrado."

        md_content = f"""# Relatório de Execução — Conector Metabase
**Card Analisado:** {report['card_name']} (ID: {report['card_id']})  
**Dashboard UUID:** `{report['dashboard_uuid']}`  
**Dashcard ID:** `{report['dashcard_id']}`  
**Data/Hora da Consulta (UTC):** `{report['data_hora_consulta_utc']}`  
**URL Consultada:** `{report['url_consultada']}`  

---

## Resultados da Extração e Validação

| Métrica / Parâmetro | Valor Observado |
| :--- | :--- |
| **Status HTTP** | `{report['status_http']}` |
| **Resultado da Validação** | **{report['resultado_validacao']}** |
| **Quantidade de Colunas** | `{report['quantidade_colunas']}` |
| **Quantidade de Linhas** | `{report['quantidade_linhas']}` |
| **Arquivo CSV Gerado** | `{report['arquivo_csv_gerado']}` |

### Colunas Identificadas
{cols_formatted}

---

## Diagnósticos e Alertas

### Avisos
{avisos_txt}

### Erros
{erros_txt}

---
*Relatório gerado automaticamente pelo conector MetabaseCardConnector.*
"""
        report_path.write_text(md_content, encoding="utf-8")

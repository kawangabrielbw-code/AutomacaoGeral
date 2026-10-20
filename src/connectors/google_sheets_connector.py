"""
Conector para Planilhas Públicas do Google Sheets
Observatório de Políticas Públicas de Diadema (OPPES)

Este módulo implementa a extração e validação de planilhas públicas disponibilizadas
no Google Sheets via exportação CSV direta, com suporte a retentativas, detecção de autenticação
e escrita atômica segura.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class GoogleSheetsError(Exception):
    """Exceção base para erros do conector Google Sheets."""
    pass


class GoogleSheetsAuthRequiredError(GoogleSheetsError):
    """Lançado quando a planilha não é pública e redireciona para login/autenticação Google."""
    pass


class GoogleSheetsHTTPError(GoogleSheetsError):
    """Lançado em erros HTTP (ex.: 404, 500)."""
    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class GoogleSheetsTimeoutError(GoogleSheetsError):
    """Lançado quando o tempo limite de requisição é excedido."""
    pass


class GoogleSheetsValidationError(GoogleSheetsError):
    """Lançado quando o conteúdo baixado não corresponde a um CSV tabular válido."""
    pass


def extract_sheet_id_and_gid(url_or_id: str) -> Tuple[str, str]:
    """
    Extrai o ID da planilha e o gid a partir de uma URL do Google Sheets ou string de ID.
    Exemplos:
      - 'https://docs.google.com/spreadsheets/d/1IbVP_n2rCMDrLiQ.../edit?usp=sharing' -> ('1IbVP...', '0')
      - 'https://docs.google.com/spreadsheets/d/1IbVP.../edit#gid=123456' -> ('1IbVP...', '123456')
      - '1IbVP_n2rCMDrLiQ...' -> ('1IbVP...', '0')
    """
    text = str(url_or_id).strip()
    # Padrão /spreadsheets/d/([a-zA-Z0-9-_]+)
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if m:
        sheet_id = m.group(1)
    else:
        # Se for apenas o ID diretamente
        if re.match(r"^[a-zA-Z0-9-_]{20,}$", text):
            sheet_id = text
        else:
            raise ValueError(f"Não foi possível extrair o ID da planilha a partir de '{text}'.")

    # Extrair gid se presente
    m_gid = re.search(r"[?&#]gid=([0-9]+)", text)
    gid = m_gid.group(1) if m_gid else "0"

    return sheet_id, gid


class GoogleSheetsConnector:
    """Conector para download, validação e catalogação de planilhas públicas do Google Sheets."""

    EXPORT_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    # Leituras verificadas no diagnóstico mostraram bytes UTF-8 apesar do
    # charset ISO-8859-1 declarado para estes dois CSVs do Google Sheets.
    UTF8_EXPORT_SHEET_IDS = frozenset({
        "1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY",  # acidentes_transito
        "1FRXI-muwyjka7FUK-TG47qJ3dPjJlo-8pIsQDL1a2jw",  # saude_atencao_basica_sisab
    })

    def __init__(
        self,
        spreadsheet_url_or_id: str,
        gid: Optional[str] = None,
        name: Optional[str] = None,
        category: Optional[str] = None,
        primary_source: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ):
        raw_id, raw_gid = extract_sheet_id_and_gid(spreadsheet_url_or_id)
        self.sheet_id = raw_id
        self.gid = gid or raw_gid
        self.original_url = spreadsheet_url_or_id
        self.name = name or f"Sheet_{self.sheet_id[:8]}"
        self.category = category or "Google Sheets"
        self.primary_source = primary_source or "Google Sheets Pública"
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.session = session or requests.Session()

    def get_export_url(self, include_gid: bool = True) -> str:
        """Retorna a URL pública canônica para download do arquivo CSV."""
        if include_gid and self.gid is not None and self.gid != "":
            return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={self.gid}"
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv"

    def download_csv_content(self) -> str:
        """
        Executa a requisição HTTP com tentativas limitadas para baixar o conteúdo CSV.
        Detecta e reporta barreiras de autenticação sem tentar contorná-las.
        Se a requisição com GID retornar HTTP 400 (comum em arquivos .xlsx nativos do Drive),
        tenta automaticamente o fallback sem o parâmetro GID.
        """
        export_url = self.get_export_url(include_gid=True)
        headers = {
            "Accept": "text/csv, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ObservatorioDiadema-SheetsConnector/1.0",
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            logger.info("Baixando planilha '%s' [Tentativa %d/%d]: %s", self.name, attempt, self.max_retries, export_url)
            try:
                response = self.session.get(
                    export_url,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                # Fallback para planilhas que não aceitam GID (arquivos XLSX visualizados no Google Drive)
                if response.status_code == 400 and self.gid:
                    fallback_url = self.get_export_url(include_gid=False)
                    logger.info("Requisição com GID retornou 400. Tentando fallback sem GID para '%s': %s", self.name, fallback_url)
                    response = self.session.get(
                        fallback_url,
                        headers=headers,
                        timeout=self.timeout,
                        allow_redirects=True,
                    )

                # Verificar se houve redirecionamento para tela de login do Google (exige autenticação)
                if "accounts.google.com" in response.url or "ServiceLogin" in response.url:
                    logger.warning("Planilha '%s' (%s) exige login/autenticação Google.", self.name, self.sheet_id)
                    raise GoogleSheetsAuthRequiredError(
                        f"Acesso restrito: a planilha '{self.name}' redireciona para login Google."
                    )

                if response.status_code in (401, 403):
                    logger.warning("Planilha '%s' retornou HTTP %d (Não autorizada/Privada).", self.name, response.status_code)
                    raise GoogleSheetsAuthRequiredError(
                        f"Acesso restrito (HTTP {response.status_code}): permissão pública não concedida."
                    )

                if response.status_code in (429, 500, 502, 503, 504):
                    logger.warning("Status HTTP transitório %d recebido na tentativa %d.", response.status_code, attempt)
                    last_error = GoogleSheetsHTTPError(response.status_code, response.text[:200])
                    if attempt < self.max_retries:
                        continue
                    raise last_error

                if response.status_code != 200:
                    raise GoogleSheetsHTTPError(response.status_code, response.text[:200])

                # Validar se o conteúdo é HTML de erro disfarçado
                content_sample = response.text[:500].lower()
                if "<html" in content_sample or "<!doctype html" in content_sample:
                    if "sign in" in content_sample or "fazer login" in content_sample:
                        raise GoogleSheetsAuthRequiredError(
                            f"Planilha '{self.name}' requer autenticação (página de login retornada em HTML)."
                        )
                    raise GoogleSheetsValidationError(
                        f"Resposta inesperada em formato HTML recebida para '{self.name}'."
                    )

                content = getattr(response, "content", None)
                if isinstance(content, bytes):
                    declared_encoding = (getattr(response, "encoding", None) or "").lower().replace("_", "-")
                    # Google Sheets declara ISO-8859-1 para estes CSVs, mas os
                    # bytes observados nas fontes verificadas são UTF-8.
                    if self.sheet_id in self.UTF8_EXPORT_SHEET_IDS:
                        try:
                            return content.decode("utf-8-sig")
                        except UnicodeDecodeError:
                            # Se o formato da resposta mudar, preserva o fallback
                            # definido pelo charset HTTP em vez de perder a coleta.
                            return response.text
                    # Para as demais fontes, respeita o charset do endpoint.
                    # A decodificação explícita também remove BOM quando UTF-8
                    # está declarado corretamente.
                    if declared_encoding in {"utf-8", "utf8", "utf-8-sig"}:
                        return content.decode("utf-8-sig")
                    return response.text
                return response.text

            except requests.exceptions.Timeout as err:
                logger.warning("Timeout na tentativa %d para '%s': %s", attempt, self.name, err)
                last_error = GoogleSheetsTimeoutError(f"Timeout de {self.timeout}s excedido: {err}")
                if attempt >= self.max_retries:
                    raise last_error
            except requests.exceptions.ConnectionError as err:
                logger.warning("Erro de conexão na tentativa %d para '%s': %s", attempt, self.name, err)
                last_error = GoogleSheetsError(f"Falha de conexão: {err}")
                if attempt >= self.max_retries:
                    raise last_error

        if last_error:
            raise last_error
        raise GoogleSheetsError("Falha desconhecida no download da planilha.")

    def validate_csv(self, csv_text: str) -> Tuple[List[str], List[List[str]]]:
        """
        Valida o conteúdo CSV baixado.
        Verifica a presença de cabeçalhos e formatação tabular coerente.
        Preserva valores nulos e strings originais sem conversão arbitrária para zero.
        """
        if not csv_text or not csv_text.strip():
            raise GoogleSheetsValidationError("O conteúdo retornado pela planilha está totalmente vazio.")

        try:
            reader = list(csv.reader(io.StringIO(csv_text)))
        except Exception as err:
            raise GoogleSheetsValidationError(f"Erro ao processar dados CSV: {err}") from err

        if not reader or len(reader) == 0:
            raise GoogleSheetsValidationError("Nenhuma linha de dados encontrada no CSV.")

        headers = [str(h).strip() for h in reader[0]]
        if not any(headers):
            raise GoogleSheetsValidationError("Linha de cabeçalho inválida ou vazia.")

        # Linhas totalmente vazias (presentes na origem) não são registros:
        # ignoradas na contagem/validação; o CSV bruto gravado não é alterado.
        rows = [r for r in reader[1:] if any(str(c).strip() for c in r)]
        return headers, rows

    def export_safe(self, output_file: str | Path, csv_text: str) -> Path:
        """
        Grava o conteúdo CSV no caminho de destino de forma atômica e segura.
        Grava primeiro em arquivo temporário (.tmp) e apenas renomeia após sucesso.
        """
        target_path = Path(output_file)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f".tmp_{target_path.name}"

        try:
            # Preserva as quebras de linha do CSV em Windows e Unix.
            with temp_path.open("w", encoding="utf-8", newline="") as temp_file:
                temp_file.write(csv_text)
            if target_path.exists():
                previous_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                version_dir = Path("data/history/versions")
                version_dir.mkdir(parents=True, exist_ok=True)
                version = version_dir / f"{target_path.stem}_{previous_hash[:12]}.csv"
                if not version.exists():
                    shutil.copy2(target_path, version)
                target_path.unlink()
            temp_path.rename(target_path)
            return target_path
        except Exception as err:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise GoogleSheetsError(f"Falha ao gravar arquivo CSV em '{target_path}': {err}") from err

    def collect(self, output_dir: str | Path, filename_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Executa o fluxo completo de coleta para uma planilha:
        1. Baixa o CSV
        2. Valida cabeçalhos e linhas
        3. Grava de forma segura no diretório especificado
        4. Retorna metadados para catálogo
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        slug = filename_slug or re.sub(r"[^\w\s-]", "", self.name).strip().lower().replace(" ", "_")
        target_csv = out_dir / f"{slug}.csv"

        record: Dict[str, Any] = {
            "fonte_id": slug,
            "tipo_fonte": "Google Sheets",
            "nome_fonte": self.name,
            "categoria": self.category,
            "fonte_primaria": self.primary_source,
            "sheet_id": self.sheet_id,
            "gid": self.gid,
            "url_original": self.original_url,
            "url_export": self.get_export_url(),
            "data_coleta_utc": now_utc,
            "status": "INICIADO",
            "quantidade_linhas": 0,
            "quantidade_colunas": 0,
            "nomes_colunas": [],
            "arquivo_csv": str(target_csv.resolve()) if target_csv.exists() else None,
            "mensagem": "",
        }

        try:
            csv_text = self.download_csv_content()
            headers, rows = self.validate_csv(csv_text)

            record["quantidade_colunas"] = len(headers)
            record["nomes_colunas"] = headers
            record["quantidade_linhas"] = len(rows)

            saved_path = self.export_safe(target_csv, csv_text)
            record["arquivo_csv"] = str(saved_path.resolve())

            if len(rows) == 0:
                record["status"] = "VAZIO"
                record["mensagem"] = "Planilha possui cabeçalho, mas zero linhas de dados."
            else:
                record["status"] = "SUCESSO"
                record["mensagem"] = f"Coleta realizada com sucesso: {len(rows)} linhas e {len(headers)} colunas."

        except GoogleSheetsAuthRequiredError as err:
            logger.warning("Autenticação necessária para '%s': %s", self.name, err)
            record["status"] = "REQUER_AUTENTICACAO"
            record["mensagem"] = str(err)
        except Exception as err:
            logger.error("Erro na coleta da planilha '%s': %s", self.name, err)
            record["status"] = f"FALHA: {type(err).__name__}"
            record["mensagem"] = str(err)

        return record

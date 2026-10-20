"""Reusable public-data ingestion pipeline for configured official resources.

Configured resource URLs must point to publicly authorized files/APIs, not merely landing pages.
Raw downloads are retained; processed CSVs are written atomically.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
import ipaddress
import socket

import requests

from src.engine.public_data_discovery import discover_resources as _discover_resources

LOG = logging.getLogger(__name__)
DEFAULT_CATALOG = Path("config/public_data_sources.json")
DEFAULT_DATA = Path("data")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_public_url(url: str) -> None:
    """Reject non-HTTP(S), credentials, localhost, and private/reserved IP destinations."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A URL deve usar HTTP ou HTTPS e conter um host.")
    if parsed.username or parsed.password:
        raise ValueError("URLs com credenciais embutidas não são permitidas.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Host local não permitido.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
        except socket.gaierror as exc:
            raise ValueError(f"Não foi possível resolver o host: {host}") from exc
    if not addresses or any(not ip.is_global for ip in addresses):
        raise ValueError("A URL resolve para endereço não público; requisição bloqueada.")


@dataclass
class PipelineResult:
    source_id: str
    status: str
    message: str
    raw_files: list[str]
    processed_files: list[str]
    bytes_downloaded: int = 0


class PublicDataPipeline:
    def __init__(
        self,
        catalog_path: str | Path = DEFAULT_CATALOG,
        data_dir: str | Path = DEFAULT_DATA,
        timeout: float = 30,
        max_download_bytes: int = 2 * 1024 * 1024 * 1024,
        retries: int = 2,
        session: requests.Session | None = None,
    ):
        self.catalog_path = Path(catalog_path)
        self.data_dir = Path(data_dir)
        self.timeout = max(1.0, float(timeout))
        self.max_download_bytes = max(1024, int(max_download_bytes))
        self.retries = max(0, min(int(retries), 5))
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "AutomacaoGeral/1.0 (public-data ingestion)")
        self.history_path = self.data_dir / "history" / "public_sources.sqlite3"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.history_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS source_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT, resource_url TEXT,
                raw_files TEXT NOT NULL, processed_files TEXT NOT NULL,
                bytes_downloaded INTEGER NOT NULL DEFAULT 0, sha256 TEXT
            )""")

    def catalog(self) -> dict[str, Any]:
        with self.catalog_path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("sources"), list):
            raise ValueError("Catálogo inválido: esperado um array 'sources'.")
        ids = [item.get("id") for item in data["sources"]]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("O catálogo contém identificadores vazios ou duplicados.")
        return data

    def list_sources(self) -> list[dict[str, Any]]:
        sources = self.catalog()["sources"]
        latest = {}
        with sqlite3.connect(self.history_path) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("""SELECT r.* FROM source_runs r JOIN
                (SELECT source_id, MAX(id) id FROM source_runs GROUP BY source_id) x
                ON x.id=r.id"""):
                latest[row["source_id"]] = dict(row)
        for source in sources:
            source["last_run"] = latest.get(source["id"])
        return sources

    def discover(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """Discover supported resources for one source or every source without downloading them."""
        sources = self.catalog()["sources"]
        if source_id is not None:
            sources = [item for item in sources if item["id"] == source_id]
            if not sources:
                raise KeyError(f"Fonte não cadastrada: {source_id}")
        output = []
        for source in sources:
            configured = str(source.get("resource_url") or "").strip()
            try:
                if configured:
                    validate_public_url(configured)
                    candidates = [{"name": "URL configurada", "url": configured, "format": Path(urlparse(configured).path).suffix.lstrip(".").upper(), "source": "catalog"}]
                else:
                    candidates = _discover_resources(source, self.session, self.timeout, validate_public_url)
                output.append({"source_id": source["id"], "name": source.get("name"), "status": "found" if candidates else "not_found", "resources": candidates, "message": f"{len(candidates)} recurso(s) público(s) encontrado(s)." if candidates else "Nenhum recurso tabular direto encontrado; requer configuração manual ou API específica."})
            except Exception as exc:
                output.append({"source_id": source["id"], "name": source.get("name"), "status": "error", "resources": [], "message": f"{type(exc).__name__}: {exc}"})
        return output

    def run(self, source_id: str, resource_url: str | None = None) -> PipelineResult:
        started = utcnow()
        source = next((s for s in self.catalog()["sources"] if s["id"] == source_id), None)
        if source is None:
            raise KeyError(f"Fonte não cadastrada: {source_id}")
        url = (resource_url or source.get("resource_url") or "").strip()
        raw_files: list[str] = []
        processed_files: list[str] = []
        total_bytes = 0
        digest = None
        status, message = "failed", ""
        try:
            if not url:
                discovery = _discover_resources(source, self.session, self.timeout, validate_public_url)
                if not discovery:
                    raise ValueError("Nenhum recurso tabular público foi descoberto. Configure resource_url ou a estratégia de descoberta oficial.")
                url = str(discovery[0]["url"])
            validate_public_url(url)
            raw_dir = self.data_dir / "raw" / source_id
            processed_dir = self.data_dir / "processed" / source_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            processed_dir.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".download-", dir=raw_dir)
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                response = None
                for attempt in range(self.retries + 1):
                    try:
                        validate_public_url(url)
                        response = self.session.get(url, stream=True, timeout=(self.timeout, self.timeout), allow_redirects=False)
                        if response.is_redirect:
                            target = response.headers.get("Location")
                            response.close()
                            if not target:
                                raise ValueError("Redirecionamento sem destino.")
                            from urllib.parse import urljoin
                            url = urljoin(url, target)
                            validate_public_url(url)
                            response = self.session.get(url, stream=True, timeout=(self.timeout, self.timeout), allow_redirects=False)
                        response.raise_for_status()
                        break
                    except (requests.RequestException, ValueError):
                        if response is not None:
                            response.close()
                        if attempt >= self.retries:
                            raise
                        time.sleep(min(2 ** attempt, 4))
                length = response.headers.get("Content-Length")
                if length and int(length) > self.max_download_bytes:
                    response.close()
                    raise ValueError("Download excede o limite configurado.")
                h = hashlib.sha256()
                with response, temp_path.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > self.max_download_bytes:
                            raise ValueError("Download excedeu o limite configurado.")
                        h.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if total_bytes == 0:
                    raise ValueError("O recurso retornou conteúdo vazio.")
                digest = h.hexdigest()
                suffix = self._detect_suffix(temp_path, response.headers.get("Content-Type", ""))
                raw_path = raw_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{digest[:12]}{suffix}"
                if raw_path.exists():
                    temp_path.unlink()
                else:
                    os.replace(temp_path, raw_path)
                raw_files.append(str(raw_path))
                outputs = self._convert_resource(raw_path, processed_dir, source)
                processed_files.extend(str(p) for p in outputs)
                if not outputs:
                    raise ValueError("Arquivo baixado, mas nenhum dado tabular suportado foi encontrado.")
                status, message = "success", f"{len(outputs)} arquivo(s) tabular(es) convertido(s)/validado(s)."
            finally:
                if temp_path.exists():
                    temp_path.unlink()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            LOG.exception("Falha na coleta da fonte %s", source_id)
        finished = utcnow()
        with sqlite3.connect(self.history_path) as db:
            db.execute("""INSERT INTO source_runs
                (source_id,started_at,finished_at,status,message,resource_url,raw_files,processed_files,bytes_downloaded,sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (source_id, started, finished, status, message, url or None,
                 json.dumps(raw_files), json.dumps(processed_files), total_bytes, digest))
        return PipelineResult(source_id, status, message, raw_files, processed_files, total_bytes)

    @staticmethod
    def _detect_suffix(path: Path, content_type: str) -> str:
        with path.open("rb") as f:
            head = f.read(8192)
        if head.startswith(b"PK\x03\x04"):
            return ".zip" if zipfile.is_zipfile(path) else ".xlsx"
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            return ".xls"
        if head.lstrip().startswith((b"{", b"[")):
            try:
                json.loads(head.decode("utf-8"))
                return ".json"
            except (ValueError, UnicodeDecodeError):
                pass
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else None
        if guessed in {".csv", ".txt", ".json", ".xlsx", ".xls", ".ods", ".zip"}:
            return guessed
        try:
            head.decode("utf-8-sig")
            return ".csv"
        except UnicodeDecodeError:
            return ".bin"

    def _convert_resource(self, raw_path: Path, out_dir: Path, source: dict[str, Any]) -> list[Path]:
        if raw_path.suffix.lower() == ".zip":
            extracted = []
            with zipfile.ZipFile(raw_path) as archive:
                total = 0
                for member in archive.infolist():
                    name = PurePosixPath(member.filename)
                    if name.is_absolute() or ".." in name.parts or member.is_dir():
                        continue
                    if member.file_size > self.max_download_bytes or total + member.file_size > self.max_download_bytes:
                        raise ValueError("Conteúdo compactado excede o limite de extração.")
                    if Path(member.filename).suffix.lower() not in {".csv", ".txt", ".xlsx", ".xls", ".ods", ".json"}:
                        continue
                    total += member.file_size
                    target = out_dir / (Path(member.filename).stem + ".csv")
                    with archive.open(member) as inp, tempfile.NamedTemporaryFile(dir=out_dir, suffix=Path(member.filename).suffix.lower(), delete=False) as tmp:
                        shutil.copyfileobj(inp, tmp, length=1024 * 1024)
                        temp = Path(tmp.name)
                    extracted.append((temp, target))
            results = []
            try:
                for temp, target in extracted:
                    results.extend(self._convert_file(temp, target, source))
            finally:
                for temp, _ in extracted:
                    temp.unlink(missing_ok=True)
            return results
        return self._convert_file(raw_path, out_dir / f"{raw_path.stem}.csv", source)

    def _convert_file(self, input_path: Path, output_path: Path, source: dict[str, Any]) -> list[Path]:
        suffix = input_path.suffix.lower()
        if suffix == ".json":
            import pandas as pd
            frame = pd.read_json(input_path)
            return [self._write_frame(frame, output_path)]
        if suffix in {".xlsx", ".xls", ".ods"}:
            try:
                import pandas as pd
            except ImportError as exc:
                raise RuntimeError("Instale pandas e o leitor do formato (openpyxl para XLSX).") from exc
            sheets = pd.read_excel(input_path, sheet_name=None, dtype=str)
            outputs = []
            for sheet, frame in sheets.items():
                target = output_path if len(sheets) == 1 else output_path.with_name(f"{output_path.stem}_{self._safe_name(sheet)}.csv")
                outputs.append(self._write_frame(frame, target))
            return outputs
        if suffix not in {".csv", ".txt", ".bin"}:
            raise ValueError(f"Formato não suportado: {suffix}")
        encoding = source.get("encoding", "utf-8-sig")
        delimiter = source.get("delimiter")
        with input_path.open("r", encoding=encoding, newline="") as f:
            sample = f.read(65536)
            f.seek(0)
            if not sample.strip():
                raise ValueError("Arquivo tabular vazio.")
            if not delimiter:
                try:
                    delimiter = csv.Sniffer().sniff(sample[:8192], delimiters=",;\\t|").delimiter
                except csv.Error:
                    delimiter = ","
            reader = csv.reader(f, delimiter=delimiter)
            header = next(reader, None)
            if not header or not any(str(v).strip() for v in header):
                raise ValueError("CSV/TXT sem cabeçalho válido.")
            width = len(header)
            fd, temp_name = tempfile.mkstemp(prefix=".csv-", suffix=".tmp", dir=output_path.parent)
            os.close(fd)
            temp = Path(temp_name)
            try:
                with temp.open("w", encoding="utf-8", newline="") as out:
                    writer = csv.writer(out, delimiter=source.get("output_delimiter", ","), lineterminator="\n")
                    writer.writerow(header)
                    for row in reader:
                        if not row or not any(str(v).strip() for v in row):
                            continue
                        if len(row) != width:
                            raise ValueError(f"Linha com {len(row)} campos; cabeçalho tem {width}.")
                        writer.writerow(row)
                os.replace(temp, output_path)
            finally:
                temp.unlink(missing_ok=True)
        return [output_path]

    @staticmethod
    def _write_frame(frame, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".csv-", suffix=".tmp", dir=output_path.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            frame.to_csv(temp, index=False, encoding="utf-8", lineterminator="\n")
            if temp.stat().st_size == 0:
                raise ValueError("Conversão gerou CSV vazio.")
            os.replace(temp, output_path)
        finally:
            temp.unlink(missing_ok=True)
        return output_path

    @staticmethod
    def _safe_name(value: str) -> str:
        import re
        return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")[:80] or "sheet"

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.history_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM source_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [dict(row) for row in rows]

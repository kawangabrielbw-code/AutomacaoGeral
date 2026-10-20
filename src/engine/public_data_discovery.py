"""Discover public file resources from configured CKAN APIs and official landing pages.

Only metadata and links are inspected here; this module never downloads datasets itself.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xls", ".ods", ".zip", ".json"}
TABULAR_FORMATS = {"CSV", "TXT", "XLSX", "XLS", "ODS", "ZIP", "JSON"}


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        for key, value in attrs:
            if key.lower() in {"href", "data-url"} and value:
                self.hrefs.append(value.strip())


def _allowed_link(url: str, source: dict[str, Any], validate_url) -> bool:
    try:
        validate_url(url)
    except (ValueError, OSError):
        return False
    host = (urlparse(url).hostname or "").lower()
    origin_host = (urlparse(str(source.get("url", ""))).hostname or "").lower()
    allowed_hosts = {str(item).lower() for item in source.get("allowed_hosts", [])}
    return host == origin_host or host in allowed_hosts


def discover_resources(source: dict[str, Any], session: requests.Session, timeout: float, validate_url) -> list[dict[str, Any]]:
    """Return supported public resources, preferring configured CKAN metadata when present."""
    discovery = source.get("discovery") or {}
    results: list[dict[str, Any]] = []
    ckan_base = str(discovery.get("ckan_api_base") or "").rstrip("/")
    package_id = str(discovery.get("package_id") or "").strip()
    resource_filter = str(discovery.get("resource_name_contains") or "").casefold()
    if ckan_base and package_id:
        api_url = f"{ckan_base}/api/3/action/package_show?id={package_id}"
        if not _allowed_link(api_url, source, validate_url):
            raise ValueError("Endpoint CKAN não está em domínio público autorizado no catálogo.")
        response = session.get(api_url, timeout=(timeout, timeout), allow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success") or not isinstance(payload.get("result"), dict):
            raise ValueError("API CKAN retornou resposta inválida.")
        for item in payload["result"].get("resources", []):
            url = str(item.get("url") or "").strip()
            name = str(item.get("name") or item.get("description") or item.get("id") or "Recurso")
            fmt = str(item.get("format") or "").upper().lstrip(".")
            path_ext = "." + urlparse(url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url).path.rsplit("/", 1)[-1] else ""
            ext = "." + fmt.lower() if "." + fmt.lower() in SUPPORTED_EXTENSIONS else path_ext
            if resource_filter and resource_filter not in name.casefold():
                continue
            if ext not in SUPPORTED_EXTENSIONS or not _allowed_link(url, source, validate_url):
                continue
            results.append({"name": name, "url": url, "format": ext.lstrip(".").upper(),
                            "size": item.get("size"), "resource_id": item.get("id"), "source": "ckan"})
        if results:
            return results

    landing_url = str(source.get("url") or "").strip()
    if not landing_url:
        return results
    validate_url(landing_url)
    response = session.get(landing_url, timeout=(timeout, timeout), allow_redirects=False)
    if response.is_redirect:
        raise ValueError("A página de origem redirecionou; configure a URL oficial final para descoberta.")
    response.raise_for_status()
    parser = _Links()
    parser.feed(response.text)
    seen: set[str] = set()
    for href in parser.hrefs:
        candidate = urljoin(landing_url, href)
        parsed = urlparse(candidate)
        filename = parsed.path.rsplit("/", 1)[-1]
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SUPPORTED_EXTENSIONS or candidate in seen:
            continue
        if not _allowed_link(candidate, source, validate_url):
            continue
        seen.add(candidate)
        results.append({"name": filename, "url": candidate, "format": ext.lstrip(".").upper(), "source": "html"})
    return results

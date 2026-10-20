"""One-time live smoke test for the official Infosiga CSV publication.

Downloads one small historical month into a temporary directory, converts it to CSV,
checks the persistent pipeline history, and removes all downloaded data on exit.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.public_data_pipeline import PublicDataPipeline


def main() -> int:
    logging.disable(logging.CRITICAL)
    original = json.loads((ROOT / "config/public_data_sources.json").read_text(encoding="utf-8"))
    source = next(item for item in original["sources"] if item["id"] == "infosiga_detran_sp")
    # The live smoke test deliberately selects one small monthly CSV, not the cumulative ZIP.
    source["allowed_hosts"] = ["dadosabertos.sp.gov.br", "infosiga.detran.sp.gov.br"]
    source["discovery"] = {
        "ckan_api_base": "https://dadosabertos.sp.gov.br",
        "package_id": "eventos-de-sinistro",
        "resource_name_contains": "Janeiro de 2015",
    }
    with tempfile.TemporaryDirectory(prefix="automacaogeral-infosiga-smoke-") as temp:
        temp_root = Path(temp)
        catalog_path = temp_root / "catalog.json"
        catalog_path.write_text(json.dumps({"version": original.get("version", 1), "sources": [source]}),
                                encoding="utf-8")
        pipeline = PublicDataPipeline(catalog_path, temp_root / "data",
                                      timeout=20, max_download_bytes=50 * 1024 * 1024, retries=1)
        discovery = pipeline.discover("infosiga_detran_sp")
        if not discovery or discovery[0]["status"] != "found" or not discovery[0]["resources"]:
            print(json.dumps({"status": "failed", "stage": "discovery",
                              "message": discovery[0]["message"] if discovery else "Nenhum resultado."},
                             ensure_ascii=False))
            return 1
        # Do not print the URL: the official resource link may contain a time-limited signature.
        resource = discovery[0]["resources"][0]
        result = pipeline.run("infosiga_detran_sp", resource["url"])
        summary = {
            "status": result.status,
            "source_id": result.source_id,
            "stage": "download_convert_history",
            "bytes_downloaded": result.bytes_downloaded,
            "raw_files": len(result.raw_files),
            "processed_files": len(result.processed_files),
            "message": result.message,
            "history_rows": len(pipeline.history()),
        }
        print(json.dumps(summary, ensure_ascii=False))
        if result.status != "success" or not result.processed_files or not pipeline.history():
            return 1
        for output in result.processed_files:
            path = Path(output)
            if not path.is_file() or path.suffix.lower() != ".csv" or path.stat().st_size == 0:
                print(json.dumps({"status": "failed", "stage": "output_validation"}, ensure_ascii=False))
                return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

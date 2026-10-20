"""CLI for the configured public-data pipeline."""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.public_data_pipeline import PublicDataPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Catálogo e coleta de recursos públicos oficiais.")
    parser.add_argument("--catalog", default=str(ROOT / "config" / "public_data_sources.json"))
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-download-mb", type=int, default=2048)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Lista fontes e último resultado registrado.")
    collect = sub.add_parser("collect", help="Coleta um recurso configurado ou uma URL direta autorizada.")
    collect.add_argument("source_id")
    collect.add_argument("--url", help="URL direta pública do arquivo/API; não use URL de página de apresentação.")
    hist = sub.add_parser("history", help="Exibe o histórico de execuções.")
    hist.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pipeline = PublicDataPipeline(args.catalog, args.data_dir, timeout=args.timeout,
                                  max_download_bytes=args.max_download_mb * 1024 * 1024)
    if args.command == "list":
        print(json.dumps(pipeline.list_sources(), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "history":
        print(json.dumps(pipeline.history(args.limit), ensure_ascii=False, indent=2))
        return 0
    result = pipeline.run(args.source_id, args.url)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

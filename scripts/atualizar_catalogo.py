"""
Script para sincronização e atualização de todos os catálogos (Metabase, Google Sheets e Catálogo Geral).
Examina os arquivos CSV existentes na pasta de dados brutos e reconstrói/atualiza
os metadados nos catálogos CSV/JSON sem refazer as requisições HTTP.
Uso:
    py scripts/atualizar_catalogo.py
    py scripts/atualizar_catalogo.py --base-dir data/raw
"""

import argparse
import csv
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Garantir inclusão da raiz do projeto no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.unified_harvester import UnifiedHarvester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AtualizarCatalogo")


def parse_args():
    parser = argparse.ArgumentParser(description="Atualiza todos os catálogos de metadados a partir dos arquivos locais.")
    parser.add_argument(
        "--base-dir",
        default=str(PROJECT_ROOT / "data" / "raw"),
        help="Diretório base onde os dados brutos e catálogos estão armazenados.",
    )
    return parser.parse_args()


def refresh_sheets_catalog(data_dir: Path, harvester) -> int:
    """Atualiza o catálogo de planilhas a partir dos arquivos CSV locais."""
    catalog = harvester.sheets_harvester.load_existing_catalog()
    csv_files = list(data_dir.glob("*.csv"))
    updated = 0

    for f in csv_files:
        if f.name.startswith("catalogo_"):
            continue
        slug = f.stem
        try:
            with open(f, mode="r", encoding="utf-8") as fp:
                reader = list(csv.reader(fp))
                col_count = len(reader[0]) if reader else 0
                row_count = max(0, len(reader) - 1)
        except Exception:
            col_count = 0
            row_count = 0

        if slug in catalog:
            catalog[slug]["quantidade_linhas"] = row_count
            catalog[slug]["quantidade_colunas"] = col_count
            catalog[slug]["arquivo_csv"] = str(f.resolve())
        else:
            catalog[slug] = {
                "fonte_id": slug,
                "tipo_fonte": "Google Sheets",
                "nome_fonte": slug.replace("_", " ").title(),
                "categoria": "Google Sheets",
                "fonte_primaria": "Google Sheets Pública",
                "sheet_id": "local",
                "gid": "0",
                "url_original": "local",
                "url_export": "local",
                "data_coleta_utc": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                "status": "SUCESSO" if row_count > 0 else "VAZIO",
                "quantidade_linhas": row_count,
                "quantidade_colunas": col_count,
                "nomes_colunas": [],
                "arquivo_csv": str(f.resolve()),
                "mensagem": "Catalogado a partir de arquivo local.",
            }
        updated += 1

    harvester.sheets_harvester.save_catalog(catalog)
    return updated


def main():
    args = parse_args()
    base_dir = Path(args.base_dir)

    print("\n" + "=" * 65)
    print("ATUALIZADOR DE CATÁLOGOS UNIFICADOS — OBSERVATÓRIO DE DIADEMA")
    print("=" * 65)
    print(f"Diretório Alvo: {base_dir}")
    print("=" * 65 + "\n")

    unified = UnifiedHarvester(base_data_dir=base_dir)

    # 1. Atualizar Metabase
    mb_count = unified.metabase_harvester.refresh_catalog_from_disk()
    logger.info("Metabase: %d arquivos CSV sincronizados.", mb_count)

    # 2. Atualizar Google Sheets
    sheets_dir = base_dir / "google_sheets"
    sh_count = refresh_sheets_catalog(sheets_dir, unified)
    logger.info("Google Sheets: %d arquivos CSV sincronizados.", sh_count)

    # 3. Consolidar Catálogo Geral
    master_csv = unified.build_master_catalog()

    print("\n" + "=" * 65)
    print("SITUAÇÃO DOS CATÁLOGOS ATUALIZADOS")
    print("=" * 65)
    print(f"Metabase CSVs Sincronizados:     {mb_count}")
    print(f"Google Sheets Sincronizados:     {sh_count}")
    print(f"Catálogo Metabase:               {base_dir / 'metabase' / 'catalogo_metabase.csv'}")
    print(f"Catálogo Google Sheets:          {base_dir / 'google_sheets' / 'catalogo_sheets.csv'}")
    print(f"Catálogo Geral Consolidado:      {master_csv}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()

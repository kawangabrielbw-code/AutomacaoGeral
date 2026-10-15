"""
Comando Único de Coleta Unificada — Observatório de Diadema
Coleta dados tanto do Metabase quanto do Google Sheets, atualizando o Catálogo Geral.

Uso:
    py scripts/coletar_dados.py                 # Coleta completa (Metabase + Google Sheets)
    py scripts/coletar_dados.py --fonte sheets   # Coleta apenas planilhas Google Sheets
    py scripts/coletar_dados.py --fonte metabase # Coleta apenas Metabase
"""

import argparse
import logging
import sys
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
logger = logging.getLogger("ColetarDados")


def parse_args():
    parser = argparse.ArgumentParser(description="Comando único de coleta de dados do Observatório de Diadema.")
    parser.add_argument(
        "--fonte",
        choices=["todas", "metabase", "sheets"],
        default="todas",
        help="Fontes a coletar: 'todas' (padrão), 'metabase' ou 'sheets'.",
    )
    parser.add_argument(
        "--base-dir",
        default=str(PROJECT_ROOT / "data" / "raw"),
        help="Diretório base onde os dados brutos e catálogo geral serão gravados.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Intervalo de pausa (em segundos) entre requisições ao Metabase.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout para as requisições HTTP.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    base_dir = Path(args.base_dir)

    print("\n" + "=" * 65)
    print("SISTEMA DE COLETA DE DADOS UNIFICADO — OBSERVATÓRIO DE DIADEMA")
    print("=" * 65)
    print(f"Modo de Coleta:       {args.fonte.upper()}")
    print(f"Diretório Base:       {base_dir}")
    print(f"Timeout Padrão:       {args.timeout}s")
    print("=" * 65 + "\n")

    harvester = UnifiedHarvester(
        base_data_dir=base_dir,
        delay_metabase=args.delay,
        timeout=args.timeout,
    )

    skip_metabase = args.fonte == "sheets"
    skip_sheets = args.fonte == "metabase"

    results = harvester.run_all(skip_metabase=skip_metabase, skip_sheets=skip_sheets)

    print("\n" + "=" * 65)
    print("RESUMO DA EXECUÇÃO UNIFICADA")
    print("=" * 65)
    if results.get("metabase_stats"):
        ms = results["metabase_stats"]
        print(f"Metabase:      {ms['cards_concluidos']} concluídos, {ms['cards_falhos']} falhas ({ms['tempo_total_segundos']}s)")
    if results.get("sheets_stats"):
        ss = results["sheets_stats"]
        print(f"Google Sheets: {ss['planilhas_sucesso']} concluídas, {ss['planilhas_falhas']} falhas, {ss['planilhas_autenticacao']} restritas ({ss['tempo_total_segundos']}s)")

    print(f"Duração Total: {results.get('duracao_total_segundos')}s")
    print(f"Catálogo Geral: {base_dir / 'catalogo_geral.csv'}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()

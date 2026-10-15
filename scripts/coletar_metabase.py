"""
Script principal para execução da coleta de cards do Metabase.
Uso:
    py scripts/coletar_metabase.py
    py scripts/coletar_metabase.py --delay 0.4 --timeout 25
    py scripts/coletar_metabase.py --dashboard-uuid 67503054-df15-421c-b610-297d72b48bb5
"""

import argparse
import logging
import sys
from pathlib import Path

# Garantir inclusão da raiz do projeto no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.metabase_harvester import MetabaseHarvester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ColetarMetabase")


def parse_args():
    parser = argparse.ArgumentParser(description="Executa o motor de coleta dos dashboards públicos do Metabase.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "raw" / "metabase"),
        help="Diretório onde os CSVs e o catálogo serão gravados.",
    )
    parser.add_argument(
        "--inventory",
        default=str(PROJECT_ROOT / "docs" / "inventario" / "inventario_fontes.csv"),
        help="Caminho do inventário CSV para descoberta de dashboards.",
    )
    parser.add_argument(
        "--dashboard-uuid",
        default=None,
        help="UUID de um único dashboard específico para coleta pontual.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Intervalo de pausa (em segundos) entre consultas de cards para rate limiting.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Tempo limite (em segundos) para cada requisição HTTP.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Quantidade de retentativas para erros transitórios.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    inventory_path = Path(args.inventory)

    print("\n" + "=" * 65)
    print("MOTOR DE COLETA DE DADOS — METABASE DIADEMA (FASE 3)")
    print("=" * 65)
    print(f"Diretório de Destino: {output_dir}")
    print(f"Inventário Fonte:     {inventory_path}")
    print(f"Delay entre Cards:    {args.delay}s")
    print(f"Timeout por Card:     {args.timeout}s")
    if args.dashboard_uuid:
        print(f"Filtro Dashboard:     {args.dashboard_uuid}")
    print("=" * 65 + "\n")

    harvester = MetabaseHarvester(
        data_dir=output_dir,
        timeout=args.timeout,
        max_retries=args.retries,
        request_delay=args.delay,
    )

    dashboard_filter = [args.dashboard_uuid] if args.dashboard_uuid else None
    stats = harvester.run_harvest(
        dashboard_uuids=dashboard_filter,
        inventory_csv_path=inventory_path if inventory_path.exists() else None,
    )

    print("\n" + "=" * 65)
    print("RESULTADO FINAL DA COLETA METABASE")
    print("=" * 65)
    print(f"Dashboards Descobertos: {stats['dashboards_descobertos']}")
    print(f"Cards Descobertos:      {stats['cards_descobertos']}")
    print(f"Cards Tentados:         {stats['cards_tentados']}")
    print(f"Cards com Sucesso:      {stats['cards_concluidos']}")
    print(f"Cards Vazios:           {stats['cards_vazios']}")
    print(f"Cards com Falha:        {stats['cards_falhos']}")
    print(f"Tempo Total:            {stats['tempo_total_segundos']}s")
    print(f"Catálogo Gerado:        {output_dir / 'catalogo_metabase.csv'}")
    print(f"Relatório Markdown:     {output_dir / 'relatorio_coleta_metabase.md'}")
    print("=" * 65 + "\n")

    return stats


if __name__ == "__main__":
    main()

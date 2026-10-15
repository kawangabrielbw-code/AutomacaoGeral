"""
Script de execução do teste real de leitura do card público selecionado.
Card Selecionado: Card 1063 (Dashcard 1104) — Dados dos 11 Bairros Oficiais de Diadema no Censo IBGE 2022
Dashboard UUID: 67503054-df15-421c-b610-297d72b48bb5
"""

import json
import logging
import sys
from pathlib import Path

# Garantir que a raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.metabase_card_connector import MetabaseCardConnector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("RealTestRunner")


def main():
    dashboard_uuid = "67503054-df15-421c-b610-297d72b48bb5"
    dashcard_id = 1104
    card_id = 1063
    card_name = "Dados dos 11 Bairros Oficiais de Diadema no Censo IBGE 2022"

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Iniciando teste real para o Card %d (%s)...", card_id, card_name)

    connector = MetabaseCardConnector(
        dashboard_uuid=dashboard_uuid,
        dashcard_id=dashcard_id,
        card_id=card_id,
        card_name=card_name,
        timeout=20.0,
        max_retries=3,
    )

    report = connector.run(
        output_dir=output_dir,
        filename_prefix="card_1063_bairros_censo_2022",
    )

    print("\n" + "=" * 60)
    print("RESUMO DA EXECUÇÃO REAL DO CONECTOR METABASE")
    print("=" * 60)
    print(f"Card: {report['card_name']} (ID: {report['card_id']})")
    print(f"Dashboard UUID: {report['dashboard_uuid']}")
    print(f"URL: {report['url_consultada']}")
    print(f"Status HTTP: {report['status_http']}")
    print(f"Resultado Validação: {report['resultado_validacao']}")
    print(f"Colunas Extraídas ({report['quantidade_colunas']}): {report['nomes_colunas']}")
    print(f"Linhas Extraídas: {report['quantidade_linhas']}")
    print(f"Arquivo CSV: {report['arquivo_csv_gerado']}")
    print(f"Relatório Markdown: {report['arquivo_relatorio_gerado']}")
    if report["avisos"]:
        print(f"Avisos: {report['avisos']}")
    if report["erros"]:
        print(f"Erros: {report['erros']}")
    print("=" * 60 + "\n")

    return report


if __name__ == "__main__":
    main()

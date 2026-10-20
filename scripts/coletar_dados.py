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
import json
from pathlib import Path

# Garantir inclusão da raiz do projeto no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.unified_harvester import UnifiedHarvester
from src.engine.execution_history import ExecutionHistory
from src.engine.collection_operations import due_ids, failed_ids

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "coleta.log", encoding="utf-8")],
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
    parser.add_argument("--status", action="store_true", help="Exibe o último status por fonte e sai.")
    parser.add_argument("--vencidas", action="store_true", help="Coleta somente fontes configuradas e vencidas.")
    parser.add_argument("--vencidas-metabase", action="store_true", help="Coleta somente cards Metabase configurados e vencidos.")
    parser.add_argument("--falhas", action="store_true", help="Repete fontes com falha na última tentativa.")
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

    hist = ExecutionHistory(PROJECT_ROOT / "data" / "history")
    if args.status:
        records = hist.get_records()
        schedule = {row["fonte_id"]: row for row in hist.get_schedule_states()}
        latest = {}
        for row in records:
            latest[row["fonte_id"]] = row
        result = []
        for source_id, row in latest.items():
            row = dict(row)
            row.update({k: v for k, v in schedule.get(source_id, {}).items()
                        if k in {"frequencia", "ultima_atualizacao_sucesso_utc", "proxima_execucao_utc"}})
            result.append(row)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("\n" + "=" * 65)
    print("SISTEMA DE COLETA DE DADOS UNIFICADO — OBSERVATÓRIO DE DIADEMA")
    print("=" * 65)
    print(f"Modo de Coleta:       {args.fonte.upper()}")
    print(f"Diretório Base:       {base_dir}")
    print(f"Timeout Padrão:       {args.timeout}s")
    print("=" * 65 + "\n")

    if sum((args.vencidas, args.vencidas_metabase, args.falhas)) > 1:
        raise SystemExit("Escolha apenas um modo entre --vencidas, --vencidas-metabase e --falhas.")
    only_ids = None
    if args.falhas:
        only_ids = failed_ids(PROJECT_ROOT, hist)
        if not only_ids:
            print("Nenhuma fonte com falha registrada.")
            return
    if args.vencidas:
        only_ids = due_ids(PROJECT_ROOT, hist)
        if not only_ids:
            print("Nenhuma fonte configurada está vencida; cards sem frequência permanecem manuais.")
            return
    if args.vencidas_metabase:
        due_cards = due_ids(PROJECT_ROOT, hist, sheets=False)
        if not due_cards:
            print("Nenhum card Metabase configurado está vencido; cards sem frequência permanecem manuais.")
            return
        only_ids = due_cards
        args.fonte = "metabase"

    harvester = UnifiedHarvester(
        base_data_dir=base_dir,
        delay_metabase=args.delay,
        timeout=args.timeout,
        only_source_ids=only_ids,
    )

    sheet_ids = {str(item.get("id") or item.get("slug")) for item in json.loads((PROJECT_ROOT / "config" / "google_sheets.json").read_text(encoding="utf-8"))}
    skip_metabase = args.fonte == "sheets" or (only_ids is not None and not any(":" in key for key in only_ids))
    skip_sheets = args.fonte == "metabase" or (only_ids is not None and not bool(sheet_ids & only_ids))

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

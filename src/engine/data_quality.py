"""
Módulo de Qualidade de Dados
Observatório de Políticas Públicas de Diadema (OPPES)

Implementa validações de qualidade, detecção de duplicatas,
padronização de tipos e comparação entre versões de dados.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DataQualityChecker:
    """Verifica qualidade, integridade e alterações em conjuntos de dados CSV."""

    def __init__(self, reports_dir: str | Path = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def file_hash(filepath: str | Path) -> str:
        """Calcula hash SHA-256 de um arquivo para detecção de mudanças."""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def read_csv_stats(filepath: str | Path) -> Dict[str, Any]:
        """Lê estatísticas básicas de um arquivo CSV."""
        fp = Path(filepath)
        if not fp.exists():
            return {"existe": False}

        try:
            with open(fp, "r", encoding="utf-8") as f:
                reader = list(csv.reader(f))
                if not reader:
                    return {"existe": True, "vazio": True, "linhas": 0, "colunas": 0}

                headers = reader[0]
                rows = [r for r in reader[1:] if any(c.strip() for c in r)]

                # Estatísticas por coluna
                col_stats = {}
                for i, h in enumerate(headers):
                    values = [r[i] if i < len(r) else "" for r in rows]
                    non_empty = [v for v in values if v.strip()]
                    col_stats[h] = {
                        "total": len(values),
                        "preenchidos": len(non_empty),
                        "vazios": len(values) - len(non_empty),
                        "taxa_preenchimento": round(len(non_empty) / max(1, len(values)) * 100, 1),
                        "valores_unicos": len(set(non_empty)),
                    }

                return {
                    "existe": True,
                    "vazio": len(rows) == 0,
                    "linhas": len(rows),
                    "colunas": len(headers),
                    "colunas_nomes": headers,
                    "tamanho_bytes": fp.stat().st_size,
                    "hash_sha256": DataQualityChecker.file_hash(fp),
                    "stats_colunas": col_stats,
                }
        except Exception as err:
            logger.error("Erro ao ler CSV '%s': %s", fp, err)
            return {"existe": True, "erro": str(err)}

    def check_duplicates(self, filepath: str | Path, key_columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Verifica duplicatas com base em colunas-chave ou na linha completa."""
        fp = Path(filepath)
        if not fp.exists():
            return {"total": 0, "duplicatas": 0}

        try:
            with open(fp, "r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))

            if not reader:
                return {"total": 0, "duplicatas": 0}

            if key_columns:
                keys = [tuple(row.get(k, "") for k in key_columns) for row in reader]
            else:
                keys = [tuple(row.values()) for row in reader]

            seen = set()
            dupes = 0
            for k in keys:
                if k in seen:
                    dupes += 1
                seen.add(k)

            return {
                "total": len(keys),
                "duplicatas": dupes,
                "taxa_duplicatas": round(dupes / max(1, len(keys)) * 100, 2),
                "colunas_chave": key_columns or ["todas"],
            }
        except Exception as err:
            logger.error("Erro ao verificar duplicatas em '%s': %s", fp, err)
            return {"total": 0, "duplicatas": 0, "erro": str(err)}

    def detect_changes(self, old_file: str | Path, new_file: str | Path) -> Dict[str, Any]:
        """Compara duas versões de um mesmo CSV e detecta mudanças."""
        old_p, new_p = Path(old_file), Path(new_file)

        if not old_p.exists():
            return {"status": "arquivo_anterior_inexistente", "novo_hash": self.file_hash(new_p) if new_p.exists() else None}
        if not new_p.exists():
            return {"status": "arquivo_novo_inexistente"}

        old_hash = self.file_hash(old_p)
        new_hash = self.file_hash(new_p)

        if old_hash == new_hash:
            return {"status": "sem_alteracao", "hash": old_hash}

        old_stats = self.read_csv_stats(old_p)
        new_stats = self.read_csv_stats(new_p)

        return {
            "status": "alterado",
            "hash_anterior": old_hash,
            "hash_novo": new_hash,
            "linhas_anterior": old_stats.get("linhas", 0),
            "linhas_novo": new_stats.get("linhas", 0),
            "diferenca_linhas": new_stats.get("linhas", 0) - old_stats.get("linhas", 0),
            "colunas_anterior": old_stats.get("colunas", 0),
            "colunas_novo": new_stats.get("colunas", 0),
        }

    def generate_quality_report(self, data_dir: str | Path) -> Dict[str, Any]:
        """Gera um relatório de qualidade de todos os CSVs em um diretório."""
        data_path = Path(data_dir)
        all_csvs = list(data_path.rglob("*.csv"))
        # Excluir catálogos
        data_csvs = [f for f in all_csvs if not f.name.startswith("catalogo_")]

        report = {
            "data_geracao_utc": datetime.now(timezone.utc).isoformat(),
            "total_csvs": len(data_csvs),
            "total_linhas": 0,
            "csvs_vazios": 0,
            "csvs_com_erro": 0,
            "detalhes": [],
        }

        for csv_file in sorted(data_csvs):
            stats = self.read_csv_stats(csv_file)
            entry = {
                "arquivo": str(csv_file.relative_to(data_path)),
                "linhas": stats.get("linhas", 0),
                "colunas": stats.get("colunas", 0),
                "tamanho_bytes": stats.get("tamanho_bytes", 0),
                "taxa_preenchimento_media": 0.0,
            }

            if stats.get("stats_colunas"):
                taxas = [c["taxa_preenchimento"] for c in stats["stats_colunas"].values()]
                entry["taxa_preenchimento_media"] = round(sum(taxas) / max(1, len(taxas)), 1)

            report["total_linhas"] += stats.get("linhas", 0)
            if stats.get("vazio"):
                report["csvs_vazios"] += 1
            if stats.get("erro"):
                report["csvs_com_erro"] += 1

            report["detalhes"].append(entry)

        # Salvar relatório
        report_path = self.reports_dir / "relatorio_qualidade.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("Relatório de qualidade gerado: %d CSVs, %d linhas totais.", report["total_csvs"], report["total_linhas"])
        return report

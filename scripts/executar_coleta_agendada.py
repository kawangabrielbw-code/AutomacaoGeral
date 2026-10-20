"""Ponto de entrada do Agendador: fixa o diretório de trabalho do projeto."""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.argv = [str(ROOT / "scripts" / "coletar_dados.py"), "--vencidas"]
runpy.run_path(str(ROOT / "scripts" / "coletar_dados.py"), run_name="__main__")

"""Gerencia uma tarefa do Agendador do Windows; não instala nada por importação."""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "ObservatorioDiademaColeta"
ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "scripts" / "executar_coleta_agendada.py"


def build_command(action: str, frequency: str = "daily", at: str = "06:00", python_exe: str | None = None) -> list[str]:
    exe = python_exe or sys.executable
    base = ["schtasks.exe"]
    if action == "install":
        if frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("Frequência deve ser daily, weekly ou monthly.")
        if len(at) != 5 or at[2] != ":":
            raise ValueError("Horário inválido; use HH:MM.")
        hour, minute = map(int, at.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Horário inválido; use HH:MM.")
        task_action = f'"{exe}" "{ENTRYPOINT}"'
        user = os.environ.get("USERDOMAIN", "")
        account = f"{user}\\{getpass.getuser()}" if user else getpass.getuser()
        return base + ["/Create", "/TN", TASK_NAME, "/SC", frequency.upper(), "/ST", at,
                       "/TR", task_action, "/F", "/RL", "LIMITED", "/RU", account, "/IT"]
    if action == "query":
        return base + ["/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"]
    if action == "pause":
        return base + ["/Change", "/TN", TASK_NAME, "/Disable"]
    if action == "resume":
        return base + ["/Change", "/TN", TASK_NAME, "/Enable"]
    if action == "remove":
        return base + ["/Delete", "/TN", TASK_NAME, "/F"]
    raise ValueError(f"Ação desconhecida: {action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerencia o agendamento de coleta no Windows.")
    parser.add_argument("action", choices=["install", "query", "pause", "resume", "remove"])
    parser.add_argument("--frequency", choices=["daily", "weekly", "monthly"], default="daily")
    parser.add_argument("--time", default="06:00", help="Horário local em HH:MM.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o comando sem alterar tarefas do Windows.")
    args = parser.parse_args(argv)
    try:
        command = build_command(args.action, args.frequency, args.time)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0
    if sys.platform != "win32":
        print("O Agendador de Tarefas só está disponível no Windows.", file=sys.stderr)
        return 2
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    print(result.stdout or result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

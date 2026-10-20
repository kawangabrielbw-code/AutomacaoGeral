import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.engine.execution_history import ExecutionHistory
from src.engine.metabase_discovery import DashboardCardSpec
from src.engine.metabase_harvester import MetabaseHarvester
from src.engine.source_schedule import select_due_metabase_cards, select_failed_metabase_cards
from scripts.agendamento_windows import TASK_NAME, build_command, main


class TestOperations(unittest.TestCase):
    def test_metabase_cards_are_selected_by_stable_dashboard_card_key(self):
        with tempfile.TemporaryDirectory() as temp:
            harvester = MetabaseHarvester(data_dir=temp, request_delay=0)
            first = DashboardCardSpec("dash-a", "A", "a", "1", "10", "First", "first", "table")
            second = DashboardCardSpec("dash-b", "B", "b", "2", "10", "Second", "second", "table")
            harvester.discovery.discover_dashboard_cards = MagicMock(side_effect=[("A", [first]), ("B", [second])])
            harvester.collect_single_card = MagicMock(side_effect=lambda card: {
                "dashboard_uuid": card.dashboard_uuid, "card_id": card.card_id, "card_name": card.card_name,
                "status": "FALHA: Network", "quantidade_linhas": 0, "quantidade_colunas": 0,
                "arquivo_csv": None, "mensagem": "network"})
            stats = harvester.run_harvest(dashboard_uuids=["dash-a", "dash-b"], source_keys={"dash-b:10"})
            self.assertEqual(stats["cards_tentados"], 1)
            self.assertEqual(harvester.collect_single_card.call_args.args[0].dashboard_uuid, "dash-b")

    def test_sqlite_records_card_failure_and_manual_frequency_never_due(self):
        with tempfile.TemporaryDirectory() as temp:
            history = ExecutionHistory(temp)
            history.add_execution("metabase", "dashboard-uuid:123", "FALHA: HTTP", mensagem="503")
            self.assertEqual(history.get_failed_sources(), ["dashboard-uuid:123"])
            self.assertFalse(history.is_due_for_update("dashboard-uuid:123", "manual")[0])
            state = next(row for row in history.get_schedule_states() if row["fonte_id"] == "dashboard-uuid:123")
            self.assertIsNotNone(state["ultima_tentativa_utc"])
            self.assertIsNone(state["ultima_atualizacao_sucesso_utc"])
            self.assertEqual(state["frequencia"], "manual")

    def test_due_and_failed_selection_uses_each_cards_frequency_and_stable_key(self):
        with tempfile.TemporaryDirectory() as temp:
            history = ExecutionHistory(temp)
            history.add_execution("metabase", "dash-a:10", "SUCESSO")
            catalog = [
                {"dashboard_uuid": "dash-a", "card_id": "10"},
                {"dashboard_uuid": "dash-b", "card_id": "20"},
                {"dashboard_uuid": "dash-c", "card_id": "30"},
            ]
            config = {"dash-a:10": {"frequencia": "mensal"},
                      "dash-b:20": {"frequencia": "semanal"}}
            self.assertEqual(select_due_metabase_cards(catalog, config, history), {"dash-b:20"})
            self.assertEqual(select_failed_metabase_cards(catalog, {"dash-c:30"}), {"dash-c:30"})

    def test_scheduler_commands_are_buildable_without_registering_task(self):
        command = build_command("install", "weekly", "06:30", r"C:\Python\python.exe")
        self.assertIn(TASK_NAME, command)
        self.assertIn("WEEKLY", command)
        self.assertIn("executar_coleta_agendada.py", " ".join(command))
        with patch("scripts.agendamento_windows.subprocess.run") as run:
            self.assertEqual(main(["install", "--frequency", "daily", "--dry-run"]), 0)
            run.assert_not_called()
        with self.assertRaises(ValueError):
            build_command("install", "hourly", "06:00")
        for action in ("query", "pause", "resume", "remove"):
            self.assertEqual(build_command(action)[0], "schtasks.exe")


if __name__ == "__main__":
    unittest.main()

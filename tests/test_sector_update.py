import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import pipeline_tasks
import update_data


class SectorUpdateTests(unittest.TestCase):
    def test_cli_default_and_explicit_sector(self):
        self.assertEqual(update_data.parse_args([]).sector, "saude")
        self.assertEqual(update_data.parse_args(["--sector", "construcao_civil"]).sector, "construcao_civil")

    def test_construction_operational_runs_only_operational_commands(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashboard.run_update_command", return_value={"status": "ok"}) as command:
            dashboard.run_update(Path(tmp), [2026], sector="construcao_civil", scope="operational")
            flat = [part for call in command.call_args_list for part in call.args[1]]
            self.assertIn(str(Path(dashboard.BASE_DIR) / "app_parser_operacional.py"), flat)
            self.assertNotIn(str(Path(dashboard.BASE_DIR) / "app_balancos.py"), flat)

    def test_construction_all_runs_financial_and_operational(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashboard.run_update_command", return_value={"status": "ok"}) as command, patch("dashboard.find_balanco_json", return_value=Path(tmp) / "x.json"):
            result = dashboard.run_update(Path(tmp), [2026], sector="construcao_civil", scope="all")
        flat = [part for call in command.call_args_list for part in call.args[1]]
        self.assertIn(str(Path(dashboard.BASE_DIR) / "app_parser_operacional.py"), flat)
        self.assertFalse(result["warnings"])

    def test_retail_all_runs_financial_without_operational_commands(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashboard.run_update_command", return_value={"status": "ok"}) as command, patch("dashboard.find_balanco_json", return_value=Path(tmp) / "x.json"):
            result = dashboard.run_update(Path(tmp), [2026], sector="varejo", scope="all")
        flat = [part for call in command.call_args_list for part in call.args[1]]
        self.assertIn(str(Path(dashboard.BASE_DIR) / "app_balancos.py"), flat)
        self.assertNotIn(str(Path(dashboard.BASE_DIR) / "app_parser_operacional.py"), flat)
        self.assertEqual(result["companies"]["operational"], [])

    def test_retail_first_deploy_does_not_require_published_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = pipeline_tasks.hydrate_existing_data(root / "data-repo", root / "resultados", "varejo", "dashboard")
        self.assertEqual(result["sectors"]["varejo"]["status"], "bootstrap_without_published_data")

    def test_retail_operational_scope_is_a_safe_noop(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashboard.run_update_command", return_value={"status": "ok"}) as command:
            result = dashboard.run_update(Path(tmp), [2026], sector="varejo", scope="operational")
        command.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["companies"]["operational"], [])

    def test_all_financial_expands_to_three_sector_pipelines(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashboard.run_update_command", return_value={"status": "ok"}) as command, patch("dashboard.find_balanco_json", return_value=Path(tmp) / "x.json"):
            result = dashboard.run_update(Path(tmp), [2026], sector="all", scope="financial")
        commands = [call.args[1] for call in command.call_args_list]
        balance_commands = [item for item in commands if any("app_balancos.py" in part for part in item)]
        self.assertEqual(len(balance_commands), 3)
        self.assertEqual({item[item.index("--sector") + 1] for item in balance_commands}, {"saude", "construcao_civil", "varejo"})
        self.assertEqual(result["sector"], "all")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
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

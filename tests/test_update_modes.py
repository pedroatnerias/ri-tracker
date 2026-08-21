import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import update_data


def command_for(commands: list[list[str]], script_name: str) -> list[str]:
    for command in commands:
        if any(script_name in part for part in command):
            return command
    raise AssertionError(f"Comando nao encontrado para {script_name}")


class UpdateModeTests(unittest.TestCase):
    def capture_commands(self, mode: str = "incremental", diagnostico_ri: bool = False) -> tuple[list[str], list[list[str]]]:
        labels: list[str] = []
        commands: list[list[str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            resultados = Path(tmp)

            def fake_run(label: str, command: list[str], critical: bool = True) -> dict[str, object]:
                labels.append(label)
                commands.append(command)
                return {"label": label, "status": "ok", "critical": critical, "returncode": 0}

            with (
                patch("dashboard.run_update_command", side_effect=fake_run),
                patch("dashboard.find_balanco_json", return_value=resultados / "balancos_itr_cvm_2026.json"),
            ):
                dashboard.run_update(resultados, anos=[2026], mode=mode, diagnostico_ri=diagnostico_ri)
        return labels, commands

    def test_incremental_does_not_force_downloads(self):
        labels, commands = self.capture_commands(mode="incremental")

        self.assertFalse(any("[FULL]" in label for label in labels))
        self.assertNotIn("--force-download", command_for(commands, "app_balancos.py"))
        self.assertNotIn("--sobrescrever-zips", command_for(commands, "app_dre.py"))
        self.assertNotIn("--sobrescrever-downloads", command_for(commands, "app_dfc.py"))
        self.assertNotIn("--sobrescrever-downloads", command_for(commands, "app_parser_operacional.py"))

    def test_full_forces_supported_downloads(self):
        labels, commands = self.capture_commands(mode="full")

        self.assertTrue(any("[FULL]" in label for label in labels))
        self.assertIn("--force-download", command_for(commands, "app_balancos.py"))
        self.assertIn("--sobrescrever-zips", command_for(commands, "app_dre.py"))
        self.assertIn("--sobrescrever-downloads", command_for(commands, "app_dfc.py"))
        self.assertIn("--sobrescrever-downloads", command_for(commands, "app_parser_operacional.py"))

    def test_diagnostico_ri_is_only_passed_when_requested(self):
        _, commands = self.capture_commands(mode="incremental", diagnostico_ri=False)
        self.assertNotIn("--diagnostico-ri", command_for(commands, "app_parser_operacional.py"))

        _, commands = self.capture_commands(mode="incremental", diagnostico_ri=True)
        self.assertIn("--diagnostico-ri", command_for(commands, "app_parser_operacional.py"))

    def test_run_full_update_delegates_to_full_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            resultados = Path(tmp)
            with patch("dashboard.run_update") as run_update:
                dashboard.run_full_update(resultados, [2026], diagnostico_ri=True)

        run_update.assert_called_once_with(resultados, [2026], mode="full", diagnostico_ri=True)

    def test_cli_mode_defaults_to_incremental(self):
        args = update_data.parse_args([])

        self.assertEqual(args.mode, "incremental")

    def test_cli_accepts_full_mode(self):
        args = update_data.parse_args(["--mode", "full"])

        self.assertEqual(args.mode, "full")

    def test_cli_rejects_invalid_mode(self):
        with self.assertRaises(SystemExit):
            update_data.parse_args(["--mode", "invalid"])


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import data_publication
import update_data


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_required_financial_outputs(base: Path) -> None:
    write_json(base / "balancos_itr_cvm_2026.json", {"companies": {}})
    for name in data_publication.REQUIRED_ROOT_JSONS:
        write_json(base / name, {"ok": True, "name": name})


class OperationalResilienceTests(unittest.TestCase):
    def run_with_fake_steps(self, fake_run):
        labels: list[str] = []

        def wrapper(label: str, command: list[str], critical: bool = True):
            labels.append(label)
            return fake_run(label, command, critical)

        with tempfile.TemporaryDirectory() as tmp:
            resultados = Path(tmp)
            with (
                patch("dashboard.run_update_command", side_effect=wrapper),
                patch("dashboard.find_balanco_json", return_value=resultados / "balancos_itr_cvm_2026.json"),
            ):
                result = dashboard.run_update(resultados, anos=[2026], mode="incremental")
        return result, labels

    def test_parser_failure_is_non_blocking_and_skips_extractor(self):
        def fake_run(label: str, command: list[str], critical: bool = True):
            if "Releases e relatorios operacionais" in label:
                return {"label": label, "status": "failed", "critical": critical, "returncode": 1}
            return {"label": label, "status": "ok", "critical": critical, "returncode": 0}

        result, labels = self.run_with_fake_steps(fake_run)

        self.assertEqual(result["status"], "success_with_warnings")
        self.assertTrue(any(step["status"] == "skipped" and step["label"] == "Dados operacionais" for step in result["steps"]))
        self.assertFalse(any(label == "Dados operacionais" for label in labels))
        self.assertTrue(any("Divida liquida" in label for label in labels))
        self.assertTrue(any("Ciclo financeiro" in label for label in labels))
        self.assertTrue(any("Market cap atual" in label for label in labels))
        self.assertTrue(any("Market cap historico" in label for label in labels))
        self.assertTrue(any("Indicadores financeiros" in label for label in labels))
        self.assertTrue(any("Relatorio de reconciliacao" in label for label in labels))

    def test_extractor_failure_is_non_blocking(self):
        def fake_run(label: str, command: list[str], critical: bool = True):
            if label == "Dados operacionais":
                return {"label": label, "status": "failed", "critical": critical, "returncode": 1}
            return {"label": label, "status": "ok", "critical": critical, "returncode": 0}

        result, labels = self.run_with_fake_steps(fake_run)

        self.assertEqual(result["status"], "success_with_warnings")
        self.assertIn("Dados operacionais", labels)
        self.assertTrue(any("Relatorio de reconciliacao" in label for label in labels))

    def test_critical_failure_remains_blocking(self):
        def fake_run(label: str, command: list[str], critical: bool = True):
            if "DRE CVM" in label:
                raise RuntimeError("DRE CVM falhou com codigo 1")
            return {"label": label, "status": "ok", "critical": critical, "returncode": 0}

        with self.assertRaises(RuntimeError):
            self.run_with_fake_steps(fake_run)

    def test_publication_preserves_old_operational_when_no_new_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "data-repo" / "data"
            write_required_financial_outputs(source)
            write_json(target / "dados_operacionais" / "AALR3.json", {"ticker": "AALR3", "old": True})

            manifest = data_publication.validate_results(source)
            metadata = data_publication.publish_validated_data(source, target, "commit", "run")

            self.assertEqual(manifest["operational_jsons"], [])
            self.assertEqual(metadata["status"], "success_with_warnings")
            self.assertEqual(metadata["components"]["operational"]["status"], "skipped_no_change")
            self.assertEqual(json.loads((target / "dados_operacionais" / "AALR3.json").read_text()), {"ticker": "AALR3", "old": True})
            data_manifest = json.loads((target / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data_manifest["files"]["balanco"], "balancos_itr_cvm_2026.json")
            self.assertEqual(data_manifest["files"]["dre"], "DRE_ITR_CVM_ultimos_5_anos.json")
            self.assertEqual(data_manifest["operational_jsons"], [])

    def test_financial_publication_preserves_existing_operational_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "data-repo" / "data"
            write_required_financial_outputs(source)
            write_json(target / "dados_operacionais" / "AALR3.json", {"ticker": "AALR3", "old": True})
            write_json(
                target / "data_manifest.json",
                {
                    "files": {"balanco": "old_balanco.json"},
                    "operational_jsons": ["dados_operacionais/AALR3.json"],
                    "charts": {"comparison": {"margem_bruta": "charts/comparison/margem_bruta.png"}},
                },
            )
            write_json(
                target / "update_metadata.json",
                {
                    "components": {
                        "operational": {"last_update": "2026-08-24T10:00:00+00:00", "status": "success", "updated": True}
                    }
                },
            )

            data_publication.validate_results(source, scope="financial")
            metadata = data_publication.publish_validated_data(source, target, "commit", "run", scope="financial")

            self.assertEqual(json.loads((target / "dados_operacionais" / "AALR3.json").read_text()), {"ticker": "AALR3", "old": True})
            data_manifest = json.loads((target / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data_manifest["operational_jsons"], ["dados_operacionais/AALR3.json"])
            self.assertEqual(metadata["components"]["financial"]["status"], "success")
            self.assertEqual(metadata["components"]["operational"]["status"], "skipped_by_scope")
            self.assertEqual(metadata["components"]["operational"]["last_update"], "2026-08-24T10:00:00+00:00")

    def test_operational_publication_preserves_existing_financial_manifest_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "data-repo" / "data"
            write_json(source / "dados_operacionais" / "AALR3.json", {"ticker": "AALR3", "new": True})
            write_json(target / "DRE_ITR_CVM_ultimos_5_anos.json", {"old_financial": True})
            write_json(
                target / "data_manifest.json",
                {
                    "files": {"dre": "DRE_ITR_CVM_ultimos_5_anos.json"},
                    "operational_jsons": ["dados_operacionais/OLD.json"],
                    "charts": {"comparison": {"margem_bruta": "charts/comparison/margem_bruta.png"}},
                },
            )
            write_json(
                target / "update_metadata.json",
                {
                    "components": {
                        "financial": {"last_update": "2026-08-24T09:00:00+00:00", "status": "success", "updated": True}
                    }
                },
            )

            manifest = data_publication.validate_results(source, scope="operational")
            metadata = data_publication.publish_validated_data(source, target, "commit", "run", scope="operational")

            self.assertEqual(manifest["root_jsons"], [])
            self.assertEqual(json.loads((target / "DRE_ITR_CVM_ultimos_5_anos.json").read_text()), {"old_financial": True})
            self.assertEqual(json.loads((target / "dados_operacionais" / "AALR3.json").read_text()), {"ticker": "AALR3", "new": True})
            data_manifest = json.loads((target / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data_manifest["files"], {"dre": "DRE_ITR_CVM_ultimos_5_anos.json"})
            self.assertEqual(data_manifest["charts"], {"comparison": {"margem_bruta": "charts/comparison/margem_bruta.png"}})
            self.assertEqual(data_manifest["operational_jsons"], ["dados_operacionais/AALR3.json"])
            self.assertEqual(metadata["components"]["financial"]["status"], "skipped_by_scope")
            self.assertEqual(metadata["components"]["financial"]["last_update"], "2026-08-24T09:00:00+00:00")
            self.assertEqual(metadata["components"]["operational"]["status"], "success")

    def test_publication_replaces_operational_when_new_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "data-repo" / "data"
            write_required_financial_outputs(source)
            write_json(source / "dados_operacionais" / "AALR3.json", {"ticker": "AALR3", "new": True})
            write_json(target / "dados_operacionais" / "AALR3.json", {"ticker": "AALR3", "old": True})

            manifest = data_publication.validate_results(source)
            metadata = data_publication.publish_validated_data(source, target, "commit", "run")

            self.assertEqual(manifest["operational_jsons"], ["dados_operacionais/AALR3.json"])
            self.assertEqual(metadata["status"], "success")
            self.assertEqual(metadata["components"]["operational"]["status"], "success")
            self.assertEqual(json.loads((target / "dados_operacionais" / "AALR3.json").read_text()), {"ticker": "AALR3", "new": True})

    def test_publication_sanitizes_runner_paths_without_changing_original_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resultados"
            target = Path(tmp) / "data-repo" / "data"
            write_required_financial_outputs(source)
            original_payload = {
                "arquivo": "/home/runner/work/ri-tracker/ri-tracker/resultados/teste.json",
                "ticker": "AALR3",
                "valor": 12345,
            }
            write_json(source / "balancos_itr_cvm_2026.json", original_payload)

            data_publication.validate_results(source)
            data_publication.publish_validated_data(source, target, "commit", "run")

            original = json.loads((source / "balancos_itr_cvm_2026.json").read_text(encoding="utf-8"))
            published = json.loads((target / "balancos_itr_cvm_2026.json").read_text(encoding="utf-8"))
            self.assertEqual(original, original_payload)
            self.assertNotIn("/home/runner/work", json.dumps(published))
            self.assertEqual(published["arquivo"], "resultados/teste.json")
            self.assertEqual(published["ticker"], "AALR3")
            self.assertEqual(published["valor"], 12345)

    def test_publication_staging_still_blocks_secret_like_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resultados"
            write_required_financial_outputs(source)
            write_json(source / "balancos_itr_cvm_2026.json", {"token": "github_pat_EXAMPLE", "ticker": "AALR3"})

            with self.assertRaises(SystemExit):
                data_publication.validate_results(source)

    def test_update_data_returns_zero_with_operational_warning(self):
        with patch("update_data.resolve_app_path", side_effect=lambda path: path), patch(
            "update_data.run_update",
            return_value={"status": "success_with_warnings"},
        ):
            self.assertEqual(update_data.main(["--resultados", "resultados"]), 0)

    def test_update_data_raises_on_critical_failure(self):
        with patch("update_data.resolve_app_path", side_effect=lambda path: path), patch(
            "update_data.run_update",
            side_effect=RuntimeError("DRE CVM falhou com codigo 1"),
        ):
            with self.assertRaises(RuntimeError):
                update_data.main(["--resultados", "resultados"])


if __name__ == "__main__":
    unittest.main()

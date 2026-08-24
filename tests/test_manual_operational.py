import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import data_publication
from manual_operational import (
    MANUAL_OVERRIDES_FILENAME,
    resolve_operational_data_with_manual,
    upsert_manual_override,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ManualOperationalTests(unittest.TestCase):
    def manual_payload(self, value=82575):
        return upsert_manual_override(
            {"overrides": []},
            {"ticker": "MATD3", "metric": "N. Pacientes", "period": "2T26", "value": value},
        )

    def test_manual_wins_when_auto_low_or_not_found(self):
        operational = {
            "companies": {
                "MATD3": {
                    "ticker": "MATD3",
                    "metricas": {
                        "N. Pacientes": [{"confidence": "low", "serie": {"2T26": 1}}],
                    },
                }
            }
        }
        resolved, manual = resolve_operational_data_with_manual(operational, self.manual_payload())
        item = resolved["companies"]["MATD3"]["metricas"]["N. Pacientes"][-1]

        self.assertEqual(item["confidence"], "MANUAL")
        self.assertEqual(item["serie"], {"2T26": 82575.0})
        self.assertEqual(manual["overrides"][-1]["status"], "active")

    def test_auto_medium_supersedes_manual(self):
        operational = {
            "companies": {
                "MATD3": {
                    "ticker": "MATD3",
                    "metricas": {
                        "N. Pacientes": [{"confidence": "medium", "serie": {"2T26": 91250}}],
                    },
                }
            }
        }
        resolved, manual = resolve_operational_data_with_manual(operational, self.manual_payload())

        self.assertEqual(len(resolved["companies"]["MATD3"]["metricas"]["N. Pacientes"]), 1)
        override = manual["overrides"][-1]
        self.assertEqual(override["status"], "superseded")
        self.assertEqual(override["automatic_confidence"], "medium")
        self.assertEqual(override["automatic_value"], 91250)

    def test_api_write_requires_admin_token_and_valid_metric(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            app = dashboard.create_app(Path(tmp))
            client = app.test_client()
            denied = client.post("/api/operational/manual", json={"ticker": "MATD3", "metric": "N. Pacientes", "period": "2T26", "value": "82.575"})
            self.assertEqual(denied.status_code, 403)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"NERIAS_DATA_SOURCE": "local", "NERIAS_MANUAL_ADMIN_TOKEN": "test-token"},
            clear=False,
        ):
            app = dashboard.create_app(Path(tmp))
            client = app.test_client()
            invalid = client.post(
                "/api/operational/manual",
                headers={"X-Nerias-Admin-Token": "test-token"},
                json={"ticker": "MATD3", "metric": "Indicador Antigo", "period": "2T26", "value": "82.575"},
            )
            self.assertEqual(invalid.status_code, 400)
            saved = client.post(
                "/api/operational/manual",
                headers={"X-Nerias-Admin-Token": "test-token"},
                json={"ticker": "MATD3", "metric": "N. Pacientes", "period": "2T26", "value": "82.575"},
            )
            self.assertEqual(saved.status_code, 200)
            self.assertTrue((Path(tmp) / MANUAL_OVERRIDES_FILENAME).exists())

    def test_publication_preserves_manual_and_supersedes_on_operational_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "data-repo" / "data"
            write_json(
                source / "dados_operacionais" / "MATD3.json",
                {
                    "ticker": "MATD3",
                    "metricas": {
                        "N. Pacientes": [{"confidence": "medium", "serie": {"2T26": 91250}}],
                    },
                },
            )
            write_json(target / MANUAL_OVERRIDES_FILENAME, self.manual_payload())
            write_json(target / "data_manifest.json", {"files": {"manual_operational_overrides": MANUAL_OVERRIDES_FILENAME}})

            data_publication.validate_results(source, scope="operational")
            data_publication.publish_validated_data(source, target, "commit", "run", scope="operational")

            published = json.loads((target / MANUAL_OVERRIDES_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(published["overrides"][-1]["status"], "superseded")
            manifest = json.loads((target / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"]["manual_operational_overrides"], MANUAL_OVERRIDES_FILENAME)

    def test_dashboard_html_contains_manual_controls_without_secret_names(self):
        self.assertIn("Adicionar dado manual", dashboard.HTML)
        self.assertIn("manual-badge", dashboard.HTML)
        self.assertNotIn("DATA_REPO_TOKEN", dashboard.HTML)


if __name__ == "__main__":
    unittest.main()

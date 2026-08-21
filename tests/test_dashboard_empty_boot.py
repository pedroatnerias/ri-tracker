import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class DashboardEmptyBootTests(unittest.TestCase):
    def test_empty_results_directory_returns_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            resultados = Path(tmp)
            app = dashboard.create_app(resultados)

            self.assertEqual(app.test_client().get("/").status_code, 200)
            response = app.test_client().get("/api/data")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertFalse(payload["has_data"])
            self.assertEqual(payload["statements"]["balanco"], {})
            self.assertEqual(payload["statements"]["dre"], {})
            self.assertEqual(payload["statements"]["dfc"], {})
            self.assertFalse(payload["files"]["balanco"]["exists"])

    def test_minimal_valid_files_are_returned(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            resultados = Path(tmp)
            write_json(resultados / "balancos_itr_cvm_2026.json", {"companies": {"AALR3": {"periods": []}}})
            write_json(resultados / "DRE_ITR_CVM_ultimos_5_anos.json", {"companies": {"AALR3": {"periods": []}}})
            write_json(resultados / "DFC_ITR_CVM.json", {"companies": {"AALR3": {"periods": []}}})
            app = dashboard.create_app(resultados)

            response = app.test_client().get("/api/data")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["has_data"])
            self.assertIn("AALR3", payload["statements"]["balanco"]["companies"])
            self.assertTrue(payload["files"]["balanco"]["exists"])

    def test_existing_invalid_statement_json_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            resultados = Path(tmp)
            (resultados / "DRE_ITR_CVM_ultimos_5_anos.json").write_text("{invalid", encoding="utf-8")
            app = dashboard.create_app(resultados)

            response = app.test_client().get("/api/data")

            self.assertEqual(response.status_code, 500)
            self.assertIn("error", response.get_json())

    def test_missing_results_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            resultados = Path(tmp) / "nao_existe"
            app = dashboard.create_app(resultados)

            response = app.test_client().get("/api/data")

            self.assertTrue(resultados.exists())
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.get_json()["has_data"])


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import data_publication


def statement_payload() -> dict:
    return {"companies": {"AALR3": {"periods": [], "rows": []}}}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_local_financials(base: Path) -> None:
    write_json(base / "balancos_itr_cvm_2022_2026.json", statement_payload())
    write_json(base / "DRE_ITR_CVM_ultimos_5_anos.json", statement_payload())
    write_json(base / "DFC_ITR_CVM.json", statement_payload())


def remote_mapping() -> dict[str, dict]:
    metadata = {
        "updated_at_utc": "2026-08-21T00:00:00+00:00",
        "status": "success",
        "files": {
            "balanco": "balancos_itr_cvm_2022_2026.json",
            "dre": "DRE_ITR_CVM_ultimos_5_anos.json",
            "dfc": "DFC_ITR_CVM.json",
            "indicadores": "indicadores.json",
            "divida_liquida": "divida_liquida.json",
            "ciclo_financeiro": "ciclo_financeiro.json",
            "market_cap": "market_cap.json",
        },
        "operational_jsons": ["dados_operacionais/AALR3.json"],
    }
    data = {
        "update_metadata.json": metadata,
        "data_manifest.json": {
            "files": metadata["files"],
            "operational_jsons": metadata["operational_jsons"],
        },
        "balancos_itr_cvm_2022_2026.json": statement_payload(),
        "DRE_ITR_CVM_ultimos_5_anos.json": statement_payload(),
        "DFC_ITR_CVM.json": statement_payload(),
        "indicadores.json": {"companies": {"AALR3": {"periodos": []}}},
        "divida_liquida.json": {"companies": {}},
        "ciclo_financeiro.json": {"companies": {}},
        "market_cap.json": {"companies": {}},
        "dados_operacionais/AALR3.json": {"ticker": "AALR3", "metricas": {}},
    }
    return data


class RemoteDataSourceTests(unittest.TestCase):
    def setUp(self):
        dashboard.clear_remote_cache()

    def test_remote_success_returns_valid_payload(self):
        mapping = remote_mapping()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: mapping[relative],
        ):
            payload = dashboard.dashboard_payload(Path(tmp))

        self.assertTrue(payload["has_data"])
        self.assertEqual(payload["data_source_mode"], "remote")
        self.assertIn("AALR3", payload["statements"]["balanco"]["companies"])

    def test_cache_hit_does_not_call_http_again_inside_ttl(self):
        calls = []
        with patch.dict("os.environ", {"NERIAS_REMOTE_CACHE_TTL_SECONDS": "600"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: calls.append(relative) or {"ok": True},
        ):
            dashboard.cached_remote_json("indicadores.json")
            dashboard.cached_remote_json("indicadores.json")

        self.assertEqual(calls, ["indicadores.json"])

    def test_cache_refresh_after_expiration_calls_remote_again(self):
        calls = []
        with patch.dict("os.environ", {"NERIAS_REMOTE_CACHE_TTL_SECONDS": "0"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: calls.append(relative) or {"ok": True},
        ):
            dashboard.cached_remote_json("indicadores.json")
            dashboard.cached_remote_json("indicadores.json")

        self.assertEqual(calls, ["indicadores.json", "indicadores.json"])

    def test_stale_cache_is_returned_when_refresh_fails(self):
        with patch("dashboard.remote_http_get_json", return_value={"ok": True}):
            dashboard.cached_remote_json("indicadores.json")
        with patch("dashboard.remote_http_get_json", side_effect=dashboard.RemoteDataError("offline")):
            data, meta = dashboard.cached_remote_json("indicadores.json", force_refresh=True)

        self.assertEqual(data, {"ok": True})
        self.assertEqual(meta["source"], "remote_cache_stale")

    def test_auto_falls_back_to_local_when_remote_fails(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "auto"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=dashboard.RemoteDataError("offline"),
        ):
            resultados = Path(tmp)
            write_local_financials(resultados)
            payload = dashboard.dashboard_payload(resultados)

        self.assertTrue(payload["has_data"])
        self.assertEqual(payload["data_source"], "local")

    def test_remote_failure_without_fallback_returns_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=dashboard.RemoteDataError("offline"),
        ):
            payload = dashboard.dashboard_payload(Path(tmp))

        self.assertFalse(payload["has_data"])
        self.assertEqual(payload["statements"]["balanco"], {})

    def test_invalid_remote_json_uses_local_fallback_in_auto(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "auto"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=dashboard.RemoteDataError("json invalido"),
        ):
            resultados = Path(tmp)
            write_local_financials(resultados)
            payload = dashboard.dashboard_payload(resultados)

        self.assertTrue(payload["has_data"])
        self.assertEqual(payload["data_source"], "local")

    def test_dynamic_balance_filename_is_resolved_from_metadata(self):
        mapping = remote_mapping()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: mapping[relative],
        ):
            payload = dashboard.dashboard_payload(Path(tmp))

        self.assertTrue(payload["files"]["balanco"]["path"].endswith("balancos_itr_cvm_2022_2026.json"))

    def test_operational_files_listed_in_metadata_are_loaded(self):
        mapping = remote_mapping()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: mapping[relative],
        ):
            payload = dashboard.dashboard_payload(Path(tmp))

        self.assertIn("AALR3", payload["operational"]["companies"])

    def test_api_update_is_disabled_in_remote_mode(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.run_full_update",
        ) as run_full_update:
            app = dashboard.create_app(Path(tmp))
            response = app.test_client().post("/api/update")

        self.assertEqual(response.status_code, 409)
        run_full_update.assert_not_called()

    def test_refresh_data_invalidates_cache_without_running_etl(self):
        mapping = remote_mapping()
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "remote"}, clear=False), patch(
            "dashboard.remote_http_get_json",
            side_effect=lambda relative: mapping[relative],
        ), patch("dashboard.run_full_update") as run_full_update:
            dashboard.cached_remote_json("indicadores.json")
            app = dashboard.create_app(Path(tmp))
            response = app.test_client().post("/api/refresh-data")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["has_data"])
        run_full_update.assert_not_called()

    def test_local_mode_preserves_update_endpoint_behavior(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False), patch(
            "dashboard.run_full_update",
            return_value={"status": "success", "warnings": [], "steps": []},
        ) as run_full_update:
            app = dashboard.create_app(Path(tmp))
            response = app.test_client().post("/api/update")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["started"])
        self.assertTrue(run_full_update.called)


if __name__ == "__main__":
    unittest.main()

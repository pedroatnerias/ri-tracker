import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
import chart_generation
import data_publication


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 600


def write_required_financial_outputs(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "balancos_itr_cvm_2022_2026.json").write_text(
        json.dumps({"fonte": "teste", "companies": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    for name in [
        "DRE_ITR_CVM_ultimos_5_anos.json",
        "DFC_ITR_CVM.json",
        "divida_liquida.json",
        "ciclo_financeiro.json",
        "market_cap.json",
        "market_cap_historico.json",
        "indicadores.json",
        "relatorio_reconciliacao.json",
    ]:
        (base / name).write_text(
            json.dumps({"fonte": "teste", "companies": {}}, ensure_ascii=False),
            encoding="utf-8",
        )


class ChartAssetTests(unittest.TestCase):
    def test_chart_manifest_publishes_only_allowed_pngs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resultados"
            write_required_financial_outputs(source)
            chart = source / "charts" / "comparison" / "margem_ebitda.png"
            chart.parent.mkdir(parents=True, exist_ok=True)
            chart.write_bytes(PNG_BYTES)
            old = source / "charts" / "comparison" / "ev_ebitda_ltm.png"
            old.write_bytes(PNG_BYTES)

            manifest = data_publication.validate_results(source)
            data_manifest = json.loads((source / "data_manifest.json").read_text(encoding="utf-8"))

            self.assertIn("charts/comparison/margem_ebitda.png", manifest["chart_pngs"])
            self.assertNotIn("charts/comparison/ev_ebitda_ltm.png", manifest["chart_pngs"])
            self.assertEqual(data_manifest["charts"]["comparison"], {"margem_ebitda": "charts/comparison/margem_ebitda.png"})

    def test_publish_copies_charts_outside_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resultados"
            target = Path(tmp) / "data-repo" / "data"
            write_required_financial_outputs(source)
            chart = source / "charts" / "comparison" / "margem_bruta.png"
            chart.parent.mkdir(parents=True, exist_ok=True)
            chart.write_bytes(PNG_BYTES)

            data_publication.validate_results(source)
            metadata = data_publication.publish_validated_data(source, target, "commit123", "run")

            self.assertTrue((target.parent / "charts" / "comparison" / "margem_bruta.png").exists())
            self.assertEqual(metadata["chart_pngs_published"], 1)
            self.assertEqual(metadata["data_version"], "commit123")

    def test_chart_url_uses_stable_version(self):
        manifest = {"charts": {"comparison": {"margem_bruta": "charts/comparison/margem_bruta.png"}}, "data_version": "v1"}
        with patch.object(dashboard.DashboardDataSource, "chart_manifest", return_value=manifest["charts"]), patch.object(
            dashboard.DashboardDataSource, "data_version", return_value="v1"
        ):
            source = dashboard.DashboardDataSource(Path("."))
            assets = dashboard.build_chart_assets(source)
            first = assets["comparison"]["margem_bruta"]["url"]
            second = dashboard.build_chart_assets(source)["comparison"]["margem_bruta"]["url"]
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("?v=v1"))

    def test_logo_route_has_long_cache(self):
        app = dashboard.create_app(Path("resultados"))
        response = app.test_client().get("/logos/Nerias.png")
        self.assertIn("max-age=31536000", response.headers.get("Cache-Control", ""))

    def test_frontend_uses_lazy_loading_and_no_date_now(self):
        self.assertIn('loading="lazy"', dashboard.HTML)
        self.assertNotIn("Date.now()", dashboard.HTML)

    def test_comparison_chart_catalog_has_five_pngs_and_y_axis_labels(self):
        self.assertEqual(
            list(chart_generation.COMPARISON_CHARTS),
            ["ciclo_financeiro", "margem_bruta", "margem_operacional", "margem_ebitda", "margem_liquida"],
        )
        self.assertNotIn("ev_ebitda_ltm", chart_generation.COMPARISON_CHARTS)
        self.assertTrue(all(config.get("ylabel") for config in chart_generation.COMPARISON_CHARTS.values()))

    def test_comparison_table_has_no_unit_column(self):
        self.assertIn("...tickers", dashboard.HTML)
        self.assertNotIn('"Unidade", ...tickers', dashboard.HTML)
        self.assertIn("predominantPeriod", dashboard.HTML)


if __name__ == "__main__":
    unittest.main()

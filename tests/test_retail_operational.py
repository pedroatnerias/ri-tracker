import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

import app_extrator_operacional
import data_publication
import dashboard
import pipeline_tasks
from company_registry import operational_companies
from operational_dictionary import all_metric_names
from operational_sources import operational_sources_for_sector
from retail_operational import (
    build_snapshot,
    dedupe_observations,
    derive_metrics,
    extract_markdown_observations,
    extract_workbook_observations,
)


class RetailOperationalTests(unittest.TestCase):
    def make_workbook(self, path: Path) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dados Operacionais"
        sheet.append(["Indicador", "1T26", "2T26"])
        sheet.append(["Número de lojas", 100, 104])
        sheet.append(["Lojas próprias", 80, 82])
        sheet.append(["Lojas franqueadas", 20, 22])
        sheet.append(["Área total de vendas (mil m²)", 250, 260])
        sheet.append(["Receita física (R$ milhões)", 900, 950])
        sheet.append(["Receita digital (R$ milhões)", 100, 120])
        sheet.append(["Receita total comparável (R$ milhões)", 1000, 1070])
        sheet.append(["GMV digital (R$ milhões)", 300, 350])
        workbook.save(path)

    def test_excel_normalizes_units_derives_ratios_and_preserves_breakdowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MGLU3_2T26_PLANILHA_RESULTADOS.xlsx"
            self.make_workbook(path)
            observations = extract_workbook_observations(path, ticker="MGLU3", source_url="https://ri.example/oficial.xlsx")

        area = next(item for item in observations if item["indicator_id"] == "sales_area_sqm" and item["period"] == "2T26")
        self.assertEqual(area["value"], 260_000)
        self.assertIn("mil m²", area["raw_unit"])
        stores = [item for item in observations if item["indicator_id"] == "stores_count" and item["period"] == "2T26"]
        self.assertEqual(len(stores), 3)
        self.assertEqual(sum(item["consolidated_or_breakdown"] == "consolidated" for item in stores), 1)
        self.assertFalse(any(item["row_label"].startswith("GMV") for item in observations))

        derived, diagnostics = derive_metrics(observations)
        share = next(item for item in derived if item["indicator_id"] == "digital_revenue_share" and item["period"] == "2T26")
        productivity = next(item for item in derived if item["indicator_id"] == "physical_revenue_per_sqm" and item["period"] == "2T26")
        self.assertAlmostEqual(share["value"], 120 / 1070)
        self.assertAlmostEqual(productivity["value"], 950_000_000 / 260_000)
        self.assertEqual(productivity["confidence"], "medium")
        self.assertTrue(any(item["indicator_id"] == "physical_revenue_per_sqm" for item in derived))
        self.assertIsInstance(diagnostics, list)

    def test_markdown_is_pdf_fallback_and_excel_wins_duplicate(self):
        markdown = """
        Página 4
        | Indicador | 2T26 |
        | --- | ---: |
        | Receita digital (R$ milhões) | 999 |
        | Número de lojas | 104 |
        """
        pdf_rows = extract_markdown_observations(markdown, ticker="MGLU3", source_document="MGLU3_2T26_RELEASE_RESULTADOS.md")
        excel = dict(next(item for item in pdf_rows if item["indicator_id"] == "digital_revenue_brl"))
        excel.update({"value": 120_000_000, "source_type": "official_spreadsheet", "source_document": "oficial.xlsx"})
        selected = dedupe_observations([*pdf_rows, excel])
        digital = next(item for item in selected if item["indicator_id"] == "digital_revenue_brl")
        self.assertEqual(digital["value"], 120_000_000)
        self.assertEqual(digital["source_type"], "official_spreadsheet")
        self.assertEqual(next(item for item in pdf_rows if item["indicator_id"] == "stores_count")["page"], 4)

    def test_missing_or_incompatible_revenue_does_not_become_zero_or_ratio(self):
        markdown = """
        | Indicador | 1T26 |
        | --- | ---: |
        | Receita digital (R$ milhões) | - |
        | GMV digital (R$ milhões) | 500 |
        | Número de lojas | 100 |
        """
        observations = extract_markdown_observations(markdown, ticker="MGLU3", source_document="MGLU3_1T26_RELEASE.md")
        self.assertFalse(any(item["indicator_id"] == "digital_revenue_brl" for item in observations))
        derived, diagnostics = derive_metrics(observations)
        self.assertFalse(any(item["indicator_id"] == "digital_revenue_share" for item in derived))
        self.assertTrue(any(item["reason"] == "missing_or_incompatible_comparable_revenue_base" for item in diagnostics))

    def test_failed_collection_preserves_previous_snapshot(self):
        previous = {
            "schema_version": "retail_operational_v1", "sector": "varejo", "ticker": "MGLU3",
            "observations": [{"indicator_id": "stores_count", "period": "1T26", "value": 100}],
            "metricas": {"Número de lojas": []}, "warnings": [],
        }
        snapshot = build_snapshot(
            ticker="MGLU3", company_name="Magazine Luiza", observations=[], companies_requested=1,
            documents_processed=[], previous_payload=previous,
        )
        self.assertEqual(snapshot["status"], "preserved_existing_data")
        self.assertEqual(snapshot["observations"], previous["observations"])

    def test_end_to_end_extractor_validation_and_dashboard_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documentos"
            output = root / "resultados" / "varejo" / "dados_operacionais"
            documents.mkdir(parents=True)
            workbook_path = documents / "MGLU3_2T26_PLANILHA_RESULTADOS.xlsx"
            self.make_workbook(workbook_path)
            args = app_extrator_operacional.build_parser().parse_args([
                "--sector", "varejo", "--only", "MGLU3", "--md-dir", str(documents), "--output-dir", str(output),
            ])
            self.assertEqual(asyncio.run(app_extrator_operacional.run(args)), 0)
            snapshot_path = output / "MGLU3.json"
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "retail_operational_v1")
            self.assertIn("Receita digital / receita total", payload["metricas"])
            data_publication.validate_operational_snapshot(snapshot_path, "varejo")
            loaded, _metadata = dashboard.load_operational_data(root / "resultados" / "varejo", "varejo")
            self.assertIn("MGLU3", loaded["companies"])
            self.assertEqual(
                loaded["companies"]["MGLU3"]["metricas"]["Número de lojas"][0]["series"]["2T26"],
                104,
            )

    def test_retail_registry_and_dashboard_metrics_share_one_universe(self):
        tickers = {company.ticker for company in operational_companies("varejo")}
        self.assertEqual(len(tickers), 16)
        self.assertEqual(set(operational_sources_for_sector("varejo")), tickers)
        self.assertEqual(
            all_metric_names("varejo"),
            (
                "Número de lojas", "Área total de vendas", "Receita física", "Receita digital",
                "Receita digital / receita total", "Receita física / área total de vendas",
            ),
        )

    def test_no_fetch_recalculation_rebuilds_derived_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "varejo" / "dados_operacionais"
            base.mkdir(parents=True)
            observations = [
                {
                    "sector": "varejo", "ticker": "MGLU3", "indicator_id": metric,
                    "indicator_name": metric, "value": value, "unit": "R$", "period": "2T26",
                    "period_type": "quarter", "scope": "retail_channels", "segment": "consolidado",
                    "consolidated_or_breakdown": "consolidated", "reported_or_derived": "reported",
                    "confidence": "high", "validation_status": "valid", "source_document": "oficial.xlsx",
                }
                for metric, value in (("digital_revenue_brl", 120), ("comparable_total_revenue_brl", 1000))
            ]
            (base / "MGLU3.json").write_text(json.dumps({
                "ticker": "MGLU3", "sector": "varejo", "observations": observations,
                "discovery": {"documents_processed": ["oficial.xlsx"]},
            }), encoding="utf-8")
            result = pipeline_tasks.recalculate_retail_operational(root)
            rebuilt = json.loads((base / "MGLU3.json").read_text(encoding="utf-8"))
        self.assertEqual(result["updated"], ["MGLU3.json"])
        self.assertIn("Receita digital / receita total", rebuilt["metricas"])


if __name__ == "__main__":
    unittest.main()

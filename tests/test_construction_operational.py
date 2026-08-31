import unittest

from construction_operational import (
    CONSTRUCTION_OPERATIONAL_DICTIONARY,
    calculate_credit_loss_proxy,
    calculate_roe,
    calculate_vso,
    align_periods_and_values,
    extract_markdown_observations,
    extract_workbook_observations,
    extract_table_observations,
    identify_metric,
    parse_composite_header,
    parse_brazilian_financial_value,
)
from openpyxl import Workbook
import tempfile
from pathlib import Path
from dashboard import normalize_operational_metric_item


class ConstructionOperationalTests(unittest.TestCase):
    def test_dictionary_has_exact_final_scope(self):
        self.assertEqual(len(CONSTRUCTION_OPERATIONAL_DICTIONARY), 10)
        self.assertEqual(CONSTRUCTION_OPERATIONAL_DICTIONARY["units_under_construction"]["unit"], "units")
        self.assertIn("proxy", CONSTRUCTION_OPERATIONAL_DICTIONARY["credit_loss_allowance_to_receivables"]["display_name"].lower())

    def test_context_rejections(self):
        self.assertEqual(identify_metric("Número de obras", "empreendimentos", "unidades")[0], None)
        self.assertEqual(identify_metric("Estoque imobiliário contábil", "balanço patrimonial", "R$ milhões")[0], None)
        self.assertEqual(identify_metric("VGV em estoque", "estoque disponível a valor de mercado", "R$ milhões")[0], "ending_inventory_vgv")

    def test_markdown_table_is_auditable_and_normalizes_scale(self):
        text = """# Prévia operacional
Página 3
| Indicador (R$ mil) - 100% | 1T26 |
|---|---:|
| VGV lançado | 250.000 |
"""
        rows = extract_markdown_observations(text, ticker="INNT3", source_document="INNT3_previa_1T26.pdf")
        self.assertEqual(rows[0]["ticker"], "INNC3")
        self.assertEqual(rows[0]["indicator_id"], "launches_vgv")
        self.assertEqual(rows[0]["value"], 250)
        self.assertEqual(rows[0]["ownership_basis"], "one_hundred_percent")
        self.assertEqual(rows[0]["page"], 3)

    def test_roe_uses_average_equity_and_rejects_nonpositive(self):
        self.assertAlmostEqual(calculate_roe(120, 900, 1100)["value"], .12)
        self.assertEqual(calculate_roe(10, -20, 0)["calculation_status"], "invalid_denominator")
        self.assertEqual(calculate_roe(10, 100, 120, scopes_match=False)["calculation_status"], "incompatible_basis")

    def test_credit_proxy_reconstructs_gross_and_uses_absolute_allowance(self):
        result = calculate_credit_loss_proxy(-20, receivables_net=180)
        self.assertEqual(result["receivables_gross"], 200)
        self.assertAlmostEqual(result["value"], .1)
        self.assertTrue(result["gross_receivables_reconstructed"])
        self.assertEqual(calculate_credit_loss_proxy(None, receivables_net=180)["value"], None)

    def test_vso_checks_basis_components_and_reconciliation(self):
        result = calculate_vso(300, 700, 300, ending_inventory_vgv=700, ownership_bases=("company_share",) * 3)
        self.assertAlmostEqual(result["value"], .3)
        self.assertEqual(result["reconciliation_status"], "reconciled")
        mismatch = calculate_vso(300, 700, 300, ownership_bases=("company_share", "one_hundred_percent"))
        self.assertEqual(mismatch["calculation_status"], "incompatible_basis")
        self.assertEqual(calculate_vso(None, 700, 300)["calculation_status"], "missing_components")

    def test_brazilian_financial_scale_is_applied_once(self):
        self.assertEqual(parse_brazilian_financial_value("7.395", "R$ MM")["normalized_value"], 7395.0)
        self.assertEqual(parse_brazilian_financial_value("814.000", "R$ mil")["normalized_value"], 814.0)
        self.assertEqual(parse_brazilian_financial_value("24,15", "R$ milhões")["normalized_value"], 24.15)
        self.assertFalse(parse_brazilian_financial_value(7395, "R$ MM")["scale_conversion_applied"])

    def test_billion_scale_and_composite_table_parser(self):
        self.assertEqual(parse_brazilian_financial_value("24,15", "R$ bilhoes")["normalized_value"], 24150.0)
        header = parse_composite_header("VGV Lancado (R$ MM)<br>6M26 6M25 Var%")
        self.assertEqual(header["periods"], ["6M26", "6M25", "VAR%"])
        aligned = align_periods_and_values(["VGV Lancado (R$ MM)<br>6M26 6M25 Var%"], ["5.154<br>6.302<br>-18%"])
        self.assertEqual(aligned, [("6M26", "5.154"), ("6M25", "6.302")])
        rows = extract_table_observations(
            [["Indicador", "VGV Lancado (R$ MM)<br>6M26 6M25 Var%"], ["VGV lancado", "5.154<br>6.302<br>-18%"]],
            {"ticker": "CYRE3", "source_document": "CYRE3.xlsx", "table_title": "Previa operacional"},
        )
        self.assertEqual([row["period"] for row in rows], ["6M26", "6M25"])
        self.assertEqual(rows[0]["indicator_id"], "launches_vgv")
        self.assertEqual(rows[0]["unit"], "BRL_million")

    def test_markdown_extraction_uses_composite_table_parser(self):
        text = """# Previa operacional
Pagina 2
| Indicador | VGV Lancado (R$ MM)<br>6M26 6M25 Var% |
|---|---:|
| VGV lancado | 5.154<br>6.302<br>-18% |
"""
        rows = extract_markdown_observations(text, ticker="CYRE3", source_document="CYRE3_release.md")
        self.assertEqual([(row["period"], row["value"]) for row in rows], [("6M26", 5154.0), ("6M25", 6302.0)])
        self.assertTrue(all(row["extraction_method"] == "markdown_composite_table" for row in rows))

    def test_workbook_extraction_preserves_sheet_and_cell_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cyre_operacional.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Operacional"
            sheet["A1"] = "Indicador"
            sheet["B1"] = "VGV Lancado (R$ MM)<br>1T26 1T25 Var%"
            sheet["A2"] = "VGV lancado"
            sheet["B2"] = "7.395<br>6.302<br>17%"
            workbook.save(path)
            rows = extract_workbook_observations(path, ticker="CYRE3", source_document=path.name)
        self.assertEqual([(row["period"], row["value"]) for row in rows], [("1T26", 7395.0), ("1T25", 6302.0)])
        self.assertEqual(rows[0]["sheet"], "Operacional")
        self.assertIn("B2", rows[0]["source_cell"])

    def test_canonical_item_and_annual_rules(self):
        flow = normalize_operational_metric_item({
            "indicator_id": "launches_vgv", "unit": "BRL_million", "calculated": False,
            "source_document": "release.pdf", "series": {"1T25": 1, "2T25": 2, "3T25": 3, "4T25": 4},
        }, "construcao_civil")
        self.assertEqual(flow["series"]["2025"], 10)
        self.assertEqual(flow["source"], "release.pdf")
        self.assertEqual(flow["unit"], "BRL_million")
        incomplete = normalize_operational_metric_item({"indicator_id": "launches_vgv", "series": {"1T25": 1}}, "construcao_civil")
        self.assertNotIn("2025", incomplete["series"])
        stock = normalize_operational_metric_item({"indicator_id": "ending_inventory_vgv", "series": {"4T25": 9}}, "construcao_civil")
        self.assertEqual(stock["series"]["2025"], 9)
        percent = normalize_operational_metric_item({"indicator_id": "net_vso", "series": {"1T25": .1, "2T25": .2, "3T25": .3, "4T25": .4}}, "construcao_civil")
        self.assertNotIn("2025", percent["series"])

    def test_historical_breakdown_value_is_quarantined(self):
        item = normalize_operational_metric_item({
            "indicator_id": "launches_vgv", "series": {"1T26": .626625},
            "observations": [{
                "period": "1T26", "value": .626625, "row_label": "Por Região",
                "unit": "BRL_million", "source_document": "CYRE3_1T26.md",
                "evidence_text": "| Total | **7.395** | R$ MM |",
            }],
        }, "construcao_civil")
        self.assertNotIn("1T26", item["series"])
        self.assertEqual(item["unit"], "BRL_million")
        self.assertEqual(item["source"], "CYRE3_1T26.md")
        self.assertEqual(item["rejected_observations"][0]["dashboard_rejection_reason"], "breakdown_as_total")

    def test_historical_scale_mismatch_is_quarantined(self):
        item = normalize_operational_metric_item({
            "indicator_id": "launches_vgv", "series": {"2T25": .000814},
            "observations": [{
                "period": "2T25", "value": .000814, "row_label": "Total consolidado",
                "raw_unit": "R$ mil", "evidence_text": "| Total consolidado | **814.000** |",
            }],
        }, "construcao_civil")
        self.assertNotIn("2T25", item["series"])
        self.assertEqual(item["rejected_observations"][0]["dashboard_rejection_reason"], "scale_incompatible_with_evidence")


if __name__ == "__main__":
    unittest.main()

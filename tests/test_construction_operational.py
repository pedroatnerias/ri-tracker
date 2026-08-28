import unittest

from construction_operational import (
    CONSTRUCTION_OPERATIONAL_DICTIONARY,
    calculate_credit_loss_proxy,
    calculate_roe,
    calculate_vso,
    extract_markdown_observations,
    identify_metric,
)


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


if __name__ == "__main__":
    unittest.main()

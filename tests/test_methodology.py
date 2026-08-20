import unittest

from app_divida_liquida import calculate_net_debt
from app_indicadores import _build_isolated_quarter_metrics, calcular_periodo_dre


def period(year, quarter, is_ytd, ebitda):
    end_month = quarter * 3
    end_day = "31" if end_month in (3, 12) else "30"
    return {
        "periodo": f"{year}-01-01 a {year}-{end_month:02d}-{end_day}",
        "metadata": {
            "start_date": f"{year}-01-01" if is_ytd else f"{year}-{end_month-2:02d}-01",
            "end_date": f"{year}-{end_month:02d}-{end_day}",
            "year": year,
            "quarter": quarter,
            "is_ytd": is_ytd,
        },
        "receita_contabil_cvm": 1000,
        "resultado_bruto": 100,
        "ebit": ebitda - 10,
        "lucro_liquido": 50,
        "depreciacao_amortizacao": 10,
        "ebitda_contabil": ebitda,
    }


class MethodologyTests(unittest.TestCase):
    def test_net_debt_deducts_financial_investments_when_configured(self):
        result = calculate_net_debt(
            {
                "company": "TEST3",
                "date": "2026-06-30",
                "accounts": [
                    {"cd_conta": "1.01.01", "ds_conta": "Caixa", "vl_conta": 100},
                    {"cd_conta": "1.01.02", "ds_conta": "Aplicacoes financeiras", "vl_conta": 50},
                    {"cd_conta": "2.01.04", "ds_conta": "Emprestimos CP", "vl_conta": 300},
                    {"cd_conta": "2.02.01", "ds_conta": "Emprestimos LP", "vl_conta": 500},
                ],
                "options": {"deduct_financial_investments": True},
            }
        )
        self.assertEqual(result["divida_liquida_padronizada"], 650)
        self.assertEqual(result["aplicacoes_financeiras_deduzidas"], 50)
        self.assertIsNone(result["divida_liquida_divulgada"])

    def test_accounting_ebitda_is_ebit_plus_da_and_adjusted_is_not_imputed(self):
        item = calcular_periodo_dre(
            {
                "periodo": "2026-01-01 a 2026-03-31",
                "metadata": {"start_date": "2026-01-01", "end_date": "2026-03-31", "year": 2026, "quarter": 1, "is_ytd": True},
                "dre": [
                    {"CD_CONTA": "3.01", "DS_CONTA": "Receita", "VL_CONTA": 1000},
                    {"CD_CONTA": "3.05", "DS_CONTA": "EBIT", "VL_CONTA": 100},
                ],
            },
            {("2026-01-01", "2026-03-31"): 25},
            {},
            "DASA3",
        )
        self.assertEqual(item["ebitda_contabil"], 125)
        self.assertEqual(item["ebitda"], 125)
        self.assertIsNone(item["ebitda_ajustado_divulgado"])

    def test_ltm_uses_four_isolated_quarters(self):
        items = [
            period(2025, 3, False, 30),
            period(2025, 4, False, 40),
            period(2026, 1, True, 10),
            period(2026, 2, True, 30),
        ]
        _build_isolated_quarter_metrics(items)
        self.assertEqual(items[-1]["periodo_individual"]["metrics"]["ebitda_contabil"], 20)
        self.assertEqual(items[-1]["ebitda_contabil_ltm"], 100)

    def test_ltm_stays_null_without_four_quarters(self):
        items = [period(2026, 1, True, 10), period(2026, 2, True, 30)]
        _build_isolated_quarter_metrics(items)
        self.assertIsNone(items[-1]["ebitda_contabil_ltm"])


if __name__ == "__main__":
    unittest.main()

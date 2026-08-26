import unittest

from sector_aggregates import aggregate_ev_ebitda, market_cap_share, sector_price_returns


class SectorAggregateTests(unittest.TestCase):
    def test_market_cap_share_sums_to_100_and_excludes_invalid_values(self):
        payload = {
            "companies": {
                "A": {"market_cap": 100, "data_preco": "2026-06-30"},
                "B": {"market_cap": 300, "data_preco": "2026-06-30"},
                "C": {"market_cap": None},
                "D": {"market_cap": -1},
            }
        }
        result = market_cap_share(payload, ("A", "B", "C", "D"))
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["share_sum_pct"], 100.0)
        self.assertEqual([item["ticker"] for item in result["items"]], ["B", "A"])
        self.assertEqual(result["companies_included"], 2)
        self.assertEqual(len(result["companies_excluded"]), 2)

    def test_market_cap_share_unavailable_without_valid_data(self):
        result = market_cap_share({"companies": {"A": {"market_cap": None}}}, ("A",))
        self.assertFalse(result["available"])
        self.assertEqual(result["items"], [])

    def test_ev_ebitda_uses_aggregate_ratio_not_average(self):
        indicators = {
            "companies": {
                "A": {"periodos": [{"metadata": {"end_date": "2026-06-30"}, "enterprise_value": 1000, "ebitda_ltm": 100, "market_cap_historico": 900}]},
                "B": {"periodos": [{"metadata": {"end_date": "2026-06-30"}, "enterprise_value": 500, "ebitda_ltm": -20, "market_cap_historico": 450}]},
                "C": {"periodos": [{"metadata": {"end_date": "2026-06-30"}, "enterprise_value": 100, "ebitda_ltm": None}]},
            }
        }
        result = aggregate_ev_ebitda(indicators, ("A", "B", "C"))
        row = result["series"][0]
        self.assertAlmostEqual(row["enterprise_value_sum"], 1500)
        self.assertAlmostEqual(row["ebitda_ltm_sum"], 80)
        self.assertAlmostEqual(row["value"], 18.75)
        self.assertEqual(row["companies_included"], 2)

    def test_ev_ebitda_null_when_aggregate_ebitda_non_positive(self):
        indicators = {
            "companies": {
                "A": {"periodos": [{"metadata": {"end_date": "2026-06-30"}, "enterprise_value": 1000, "ebitda_ltm": 0}]},
                "B": {"periodos": [{"metadata": {"end_date": "2026-06-30"}, "enterprise_value": 500, "ebitda_ltm": -20}]},
            }
        }
        row = aggregate_ev_ebitda(indicators, ("A", "B"))["series"][0]
        self.assertIsNone(row["value"])
        self.assertIn("EBITDA LTM agregado", row["diagnostics"][0])

    def test_sector_return_uses_initial_market_cap_weights_and_threshold(self):
        payload = {
            "empresas": {
                "A": {
                    "periodos": [
                        {"data_referencia": "2025-06-30", "preco_acao": 10, "data_preco": "2025-06-30", "quantidade_acoes_total": 10},
                        {"data_referencia": "2026-06-30", "preco_acao": 20, "data_preco": "2026-06-30", "quantidade_acoes_total": 10},
                    ]
                },
                "B": {
                    "periodos": [
                        {"data_referencia": "2025-06-30", "preco_acao": 10, "data_preco": "2025-06-30", "quantidade_acoes_total": 30},
                        {"data_referencia": "2026-06-30", "preco_acao": 5, "data_preco": "2026-06-30", "quantidade_acoes_total": 30},
                    ]
                },
            }
        }
        rows = sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["360d"]
        row = next(item for item in rows if item["date"] == "2026-06-30")
        self.assertAlmostEqual(row["value"], -0.125)
        self.assertAlmostEqual(row["total_initial_market_cap"], 400)
        self.assertEqual(row["companies_included"], 2)

    def test_sector_return_null_below_coverage(self):
        payload = {"empresas": {"A": {"periodos": [{"data_referencia": "2026-06-30", "preco_acao": 10, "quantidade_acoes_total": 1}]}}}
        row = sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["30d"][0]
        self.assertIsNone(row["value"])
        self.assertLess(row["coverage_count"], 0.70)


if __name__ == "__main__":
    unittest.main()

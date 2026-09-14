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
                        {"data_referencia": "2025-06-30", "market_cap": 100, "status_validacao_acoes": "validated"},
                        {"data_referencia": "2026-06-30", "market_cap": 200, "status_validacao_acoes": "validated"},
                    ],
                    "precos_diarios_ajustados": [{"data": "2025-06-30", "preco_ajustado": 10}, {"data": "2026-06-25", "preco_ajustado": 20}],
                },
                "B": {
                    "periodos": [
                        {"data_referencia": "2025-06-30", "market_cap": 300, "status_validacao_acoes": "validated"},
                        {"data_referencia": "2026-06-30", "market_cap": 150, "status_validacao_acoes": "validated"},
                    ],
                    "precos_diarios_ajustados": [{"data": "2025-06-30", "preco_ajustado": 10}, {"data": "2026-06-25", "preco_ajustado": 5}],
                },
            }
        }
        rows = sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["360d"]
        row = next(item for item in rows if item["date"] == "2026-06-30")
        self.assertAlmostEqual(row["value"], -0.125)
        self.assertAlmostEqual(row["total_initial_market_cap"], 400)
        self.assertEqual(row["companies_included"], 2)
        self.assertIn("90d", sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"])

    def test_sector_return_90d_uses_90_day_horizon_and_weights(self):
        payload = {
            "empresas": {
                "A": {
                    "periodos": [
                        {"data_referencia": "2026-03-30", "market_cap": 100, "status_validacao_acoes": "validated"},
                        {"data_referencia": "2026-06-28", "market_cap": 120, "status_validacao_acoes": "validated"},
                    ],
                    "precos_diarios_ajustados": [{"data": "2026-03-30", "preco_ajustado": 10}, {"data": "2026-06-28", "preco_ajustado": 12}],
                },
                "B": {
                    "periodos": [
                        {"data_referencia": "2026-03-30", "market_cap": 200, "status_validacao_acoes": "validated"},
                        {"data_referencia": "2026-06-28", "market_cap": 100, "status_validacao_acoes": "validated"},
                    ],
                    "precos_diarios_ajustados": [{"data": "2026-03-30", "preco_ajustado": 20}, {"data": "2026-06-28", "preco_ajustado": 10}],
                },
            }
        }
        row = next(item for item in sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["90d"] if item["date"] == "2026-06-28")
        self.assertEqual(row["included_companies"][0]["target_initial_date"], "2026-03-30")
        self.assertAlmostEqual(row["value"], -0.2666666667)

    def test_sector_return_null_below_coverage(self):
        payload = {"empresas": {"A": {"periodos": [{"data_referencia": "2026-05-31", "market_cap": 10}], "precos_diarios_ajustados": [{"data": "2026-05-31", "preco_ajustado": 9}, {"data": "2026-06-30", "preco_ajustado": 10}]}}}
        row = sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["30d"][0]
        self.assertIsNone(row["value"])
        self.assertLess(row["coverage_count"], 0.70)
        self.assertIsNone(row["coverage_market_cap"])
        self.assertIsNone(sector_price_returns(payload, ("A", "B"), coverage_threshold=0.70)["series"]["90d"][0]["value"])

    def test_sector_return_uses_split_adjusted_price(self):
        payload = {"empresas": {"TOKY3": {"periodos": [
            {"data_referencia": "2026-06-30", "preco_acao": 0.50, "quantidade_acoes_total": 54_000_000, "market_cap": 27_000_000, "status_validacao_acoes": "validated"},
            {"data_referencia": "2026-09-30", "preco_acao": 10.40, "quantidade_acoes_total": 2_700_000, "market_cap": 28_080_000, "status_validacao_acoes": "validated"},
        ], "precos_diarios_ajustados": [{"data": "2026-07-02", "preco_ajustado": 10.0}, {"data": "2026-09-30", "preco_ajustado": 10.4}]}}}
        row = next(item for item in sector_price_returns(payload, ("TOKY3",), 0.70)["series"]["90d"] if item["date"] == "2026-09-30")
        self.assertAlmostEqual(row["return_pct"], 4.0)
        self.assertEqual(row["included_companies"][0]["initial_market_cap"], 27_000_000)
        self.assertNotEqual(row["included_companies"][0]["initial_market_cap"], 10.0 * 54_000_000)

    def test_ifcm_adjusted_price_is_never_used_to_rebuild_weight(self):
        payload = {"empresas": {"IFCM3": {
            "periodos": [{"data_referencia": "2022-03-31", "preco_acao": 10.869645, "quantidade_acoes_total": 281_636_000, "market_cap": 3_061_283_339.22, "status_validacao_acoes": "validated"}, {"data_referencia": "2023-03-26", "market_cap": 3_200_000_000, "status_validacao_acoes": "validated"}],
            "precos_diarios_ajustados": [{"data": "2022-03-31", "preco_ajustado": 21_739.289062}, {"data": "2023-03-26", "preco_ajustado": 22_608.86062448}],
        }}}
        row = next(item for item in sector_price_returns(payload, ("IFCM3",))["series"]["360d"] if item["date"] == "2022-03-31")
        self.assertIsNone(row["value"])
        final_row = sector_price_returns(payload, ("IFCM3",))["series"]["360d"][-1]
        item = final_row["included_companies"][0]
        self.assertAlmostEqual(item["return_pct"] if "return_pct" in item else item["return"] * 100, 4.0)
        self.assertAlmostEqual(item["initial_market_cap"], 3_061_283_339.22)
        self.assertNotAlmostEqual(item["initial_market_cap"], 21_739.289062 * 281_636_000)

    def test_daily_prices_distinguish_30d_from_90d(self):
        payload = {"empresas": {"A": {
            "periodos": [{"data_referencia": "2026-03-31", "market_cap": 100}, {"data_referencia": "2026-06-30", "market_cap": 120}],
            "precos_diarios_ajustados": [{"data": "2026-04-01", "preco_ajustado": 8}, {"data": "2026-05-31", "preco_ajustado": 10}, {"data": "2026-06-30", "preco_ajustado": 12}],
        }}}
        result = sector_price_returns(payload, ("A",))["series"]
        row_30 = next(row for row in result["30d"] if row["date"] == "2026-06-30")
        row_90 = next(row for row in result["90d"] if row["date"] == "2026-06-30")
        self.assertAlmostEqual(row_30["return_pct"], 20.0)
        self.assertAlmostEqual(row_90["return_pct"], 50.0)
        self.assertEqual(row_30["included_companies"][0]["price_initial_date"], "2026-05-31")
        self.assertEqual(row_90["included_companies"][0]["price_initial_date"], "2026-04-01")

    def test_market_cap_coverage_uses_economic_denominator(self):
        empresas = {}
        for ticker in ("A", "B", "C", "D"):
            empresas[ticker] = {"periodos": [{"data_referencia": "2026-03-31", "market_cap": 7.5}, {"data_referencia": "2026-06-29", "market_cap": 8}], "precos_diarios_ajustados": [{"data": "2026-03-31", "preco_ajustado": 10}, {"data": "2026-06-29", "preco_ajustado": 11}]}
        empresas["E"] = {"periodos": [{"data_referencia": "2026-03-31", "market_cap": 70}, {"data_referencia": "2026-06-29", "market_cap": 70}], "precos_diarios_ajustados": [{"data": "2026-03-31", "preco_ajustado": 10}]}
        row = sector_price_returns({"empresas": empresas}, tuple(empresas))["series"]["90d"][-1]
        self.assertAlmostEqual(row["coverage_count"], 0.8)
        self.assertAlmostEqual(row["coverage_market_cap"], 0.3)
        self.assertIsNone(row["value"])
        self.assertTrue(any("market cap abaixo" in message for message in row["diagnostics"]))

    def test_legacy_quarterly_schema_without_daily_prices_fails_closed(self):
        payload = {"metadata": {"schema_version": "market_cap_historico_v2"}, "empresas": {"A": {"periodos": [
            {"data_referencia": "2026-03-31", "preco_acao_raw": 1, "preco_acao": 10, "market_cap": 100, "status_market_cap": "validated"},
            {"data_referencia": "2026-06-30", "preco_acao_raw": 10, "preco_acao": 10.4, "market_cap": 104, "status_market_cap": "validated"},
        ]}}}
        row = sector_price_returns(payload, ("A",))["series"]["90d"][-1]
        self.assertIsNone(row["value"])
        self.assertEqual(row["coverage_market_cap"], 0.0)
        self.assertIn("serie diaria", row["companies_excluded"][0]["reason"])


if __name__ == "__main__":
    unittest.main()

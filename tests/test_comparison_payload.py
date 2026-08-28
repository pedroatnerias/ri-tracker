import unittest

from company_registry import tickers_for_sector
from dashboard import build_comparison_payload
from company_registry import tickers_for_sector

TICKERS = tickers_for_sector("saude")


def indicator_record(year, quarter, is_ytd, **values):
    return {
        "metadata": {"year": year, "quarter": quarter, "is_ytd": is_ytd},
        "receita_liquida": values.get("receita", 100),
        "lucro_liquido": values.get("lucro", 10),
        "margens_percentual": {
            "margem_bruta": values.get("margem_bruta", 20),
            "margem_operacional": values.get("margem_operacional", 10),
            "margem_ebitda": values.get("margem_ebitda", 15),
            "margem_liquida": values.get("margem_liquida", 5),
        },
        "ev_ebitda_ltm": values.get("ev_ebitda_ltm"),
        "enterprise_value": values.get("enterprise_value"),
        "ebitda_ltm": values.get("ebitda_ltm"),
        "data_market_cap": values.get("data_market_cap"),
        "data_divida_liquida": values.get("data_divida_liquida"),
        "data_ebitda_ltm": values.get("data_ebitda_ltm"),
    }


class ComparisonPayloadTests(unittest.TestCase):
    def payload(self):
        companies = {ticker: {"periodos": []} for ticker in TICKERS}
        companies["AALR3"]["periodos"] = [
            indicator_record(2024, 4, True, receita=100, lucro=10, margem_bruta=25),
            indicator_record(2025, 4, True, receita=121, lucro=12.1, margem_bruta=30),
            indicator_record(2026, 1, True, ev_ebitda_ltm=None),
            indicator_record(
                2026,
                2,
                True,
                ev_ebitda_ltm=7.8,
                enterprise_value=780,
                ebitda_ltm=100,
                data_market_cap="2026-06-30",
                data_divida_liquida="2026-06-30",
                data_ebitda_ltm="2026-06-30",
            ),
        ]
        indicators = {
            "indicadores": {"companies": companies},
            "ciclo_financeiro": {
                "companies": {
                    "AALR3": [
                        {"periodo": {"inicio": "2025-01-01", "fim": "2025-12-31"}, "indicadores_dias": {"ciclo_financeiro": -18.7}},
                        {"periodo": {"inicio": "2026-01-01", "fim": "2026-03-31"}, "indicadores_dias": {"ciclo_financeiro": 10}},
                    ]
                }
            },
            "market_cap": {"companies": {"AALR3": {"variacao_30d_pct": 12.4, "variacao_90d_pct": 4.2, "variacao_360d_pct": -8.7}}},
        }
        operational = {
            "companies": {
                "AALR3": {
                    "metricas": {
                        "N. Unidades": [
                            {"confidence": "low", "serie": {"2T26": 999}},
                            {"confidence": "medium", "fonte_linha": "Hospitais", "serie": {"1T26": 570}},
                        ]
                    }
                }
            }
        }
        return build_comparison_payload(indicators, operational, TICKERS)

    def test_comparison_has_seven_companies_and_twelve_metrics(self):
        payload = self.payload()
        self.assertEqual(payload["companies_order"], list(TICKERS))
        self.assertEqual(len(payload["metrics"]), 12)

    def test_table_uses_requested_temporal_rules(self):
        aalr = self.payload()["companies"]["AALR3"]
        self.assertEqual(aalr["cagr_receita"]["period"], "2024–2025")
        self.assertAlmostEqual(aalr["cagr_receita"]["value"], 21.0)
        self.assertEqual(aalr["ciclo_financeiro"]["period"], "FY2025")
        self.assertEqual(aalr["ciclo_financeiro"]["value"], -18.7)
        self.assertEqual(aalr["margem_bruta"]["period"], "FY2025")
        self.assertEqual(aalr["ev_ebitda"]["period"], "LTM 2T26")
        self.assertEqual(aalr["delta_preco_30d"]["value"], 12.4)
        self.assertEqual(aalr["delta_preco_90d"]["value"], 4.2)
        self.assertEqual(aalr["delta_preco_360d"]["value"], -8.7)

    def test_legacy_market_payload_without_90d_does_not_break_comparison(self):
        aalr = build_comparison_payload(
            {"indicadores": {"companies": {"AALR3": {"periodos": []}}}, "market_cap": {"companies": {"AALR3": {"variacao_30d_pct": 1.0, "variacao_360d_pct": 2.0}}}},
            {"companies": {}},
            ("AALR3",),
        )["companies"]["AALR3"]
        self.assertIsNone(aalr["delta_preco_90d"]["value"])

    def test_latest_operational_units_ignores_low_confidence(self):
        units = self.payload()["companies"]["AALR3"]["n_unidades"]
        self.assertEqual(units["value"], 570)
        self.assertEqual(units["period"], "1T26")
        self.assertEqual(units["confidence"], "medium")

    def test_ev_ebitda_remains_in_table_but_not_as_chart(self):
        payload = self.payload()
        self.assertEqual(payload["companies"]["AALR3"]["ev_ebitda"]["period"], "LTM 2T26")
        self.assertNotIn("ev_ebitda", payload["charts"])

    def test_chart_set_has_exactly_five_charts(self):
        self.assertEqual(len(self.payload()["charts"]), 5)

    def test_companies_order_is_sector_scoped(self):
        construction = tickers_for_sector("construcao_civil")
        payload = build_comparison_payload({"indicadores": {"companies": {}}}, {"companies": {}}, construction)
        self.assertEqual(payload["companies_order"], list(construction))
        self.assertNotIn("AALR3", payload["companies_order"])
        self.assertIn("CURY3", payload["companies_order"])


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from app_market_cap import obter_variacoes_preco


class FakeTicker:
    def __init__(self, history: pd.DataFrame):
        self._history = history

    def history(self, period: str, auto_adjust: bool = False) -> pd.DataFrame:
        self.period = period
        self.auto_adjust = auto_adjust
        return self._history


class MarketCapVariationTests(unittest.TestCase):
    def test_obter_variacoes_preco_returns_30_90_and_360_days(self):
        now = pd.Timestamp.now(tz="UTC").normalize()
        history = pd.DataFrame(
            {
                "Close": [80.0, 100.0, 110.0, 120.0],
            },
            index=[now - pd.Timedelta(days=360), now - pd.Timedelta(days=90), now - pd.Timedelta(days=30), now],
        )

        result = obter_variacoes_preco(FakeTicker(history), 120.0)

        self.assertEqual(result["preco_30d"], 110.0)
        self.assertEqual(result["preco_90d"], 100.0)
        self.assertEqual(result["preco_360d"], 80.0)
        self.assertAlmostEqual(result["variacao_90d_pct"], 20.0)

    def test_obter_variacoes_preco_error_payload_keeps_90d_schema(self):
        result = obter_variacoes_preco(FakeTicker(pd.DataFrame()), 120.0)

        for key in ("preco_30d", "data_30d", "variacao_30d_pct", "preco_90d", "data_90d", "variacao_90d_pct", "preco_360d", "data_360d", "variacao_360d_pct"):
            self.assertIn(key, result)
            self.assertIsNone(result[key])


if __name__ == "__main__":
    unittest.main()

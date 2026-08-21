import unittest

import dashboard


def cagr_label(base: str, first_year: int | None, last_year: int | None) -> str:
    if first_year is None or last_year is None:
        return f"{base} (%)"
    return f"{base} {first_year}–{last_year} (%)"


class CagrPeriodLabelTests(unittest.TestCase):
    def test_dashboard_uses_dynamic_cagr_period_suffix(self):
        html = dashboard.HTML

        self.assertIn("function cagrPeriodSuffix(firstInfo, lastInfo)", html)
        self.assertIn("const cagrPeriod = cagrPeriodSuffix(firstInfo, lastInfo);", html)
        self.assertIn("`CAGR receitas${cagrPeriod} (%)`", html)
        self.assertIn("`CAGR lucros${cagrPeriod} (%)`", html)

    def test_cagr_labels_show_2022_to_2025(self):
        self.assertEqual(cagr_label("CAGR receitas", 2022, 2025), "CAGR receitas 2022–2025 (%)")
        self.assertEqual(cagr_label("CAGR lucros", 2022, 2025), "CAGR lucros 2022–2025 (%)")

    def test_cagr_labels_show_2023_to_2025(self):
        self.assertEqual(cagr_label("CAGR receitas", 2023, 2025), "CAGR receitas 2023–2025 (%)")
        self.assertEqual(cagr_label("CAGR lucros", 2023, 2025), "CAGR lucros 2023–2025 (%)")

    def test_cagr_labels_fall_back_to_generic_without_period(self):
        self.assertEqual(cagr_label("CAGR receitas", None, 2025), "CAGR receitas (%)")
        self.assertEqual(cagr_label("CAGR lucros", 2022, None), "CAGR lucros (%)")


if __name__ == "__main__":
    unittest.main()

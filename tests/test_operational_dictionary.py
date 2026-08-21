import unittest

from app_extrator_operacional import (
    COMPANIES,
    SheetSnapshot,
    WorkbookSnapshot,
    build_operational_warnings,
    classify_operational_observation,
    extract_metric,
)
from operational_dictionary import CONFIDENCE_MEDIUM, all_metric_names


class OperationalDictionaryTests(unittest.TestCase):
    def test_target_metrics_are_limited_to_agreed_scope(self):
        self.assertEqual(
            all_metric_names(),
            (
                "Ticket Médio",
                "N. Atendimentos",
                "N. Unidades",
                "N. Pacientes",
                "Receita Bruta",
                "Glosa/PCLD",
            ),
        )

    def test_materdei_rent_clause_is_not_units_kpi(self):
        obs = classify_operational_observation(
            COMPANIES["MATD3"],
            "N. Unidades",
            label="unidades operacionais",
            value=40000,
            context="unidades operacionais com aluguel anual de R$ 40.000",
            extraction_method="markdown_contextual",
        )
        self.assertEqual(obs["confidence"], "low")
        self.assertTrue(obs["requires_review"])
        self.assertIsNotNone(obs["rejection_reason"])

    def test_aalr_gross_revenue_adjusted_and_construction_are_rejected(self):
        for label in ("Receita Bruta Ajustada", "Receitas de Construção"):
            obs = classify_operational_observation(
                COMPANIES["AALR3"],
                "Receita Bruta",
                label=label,
                value=100,
                unit="R$ milhões",
                extraction_method="spreadsheet_labeled_row",
            )
            self.assertEqual(obs["confidence"], "low")
            self.assertTrue(obs["requires_review"])

    def test_aalr_tiny_gross_revenue_is_rejected(self):
        obs = classify_operational_observation(
            COMPANIES["AALR3"],
            "Receita Bruta",
            label="Receita Bruta",
            value=1,
            unit="R$ milhões",
            extraction_method="spreadsheet_labeled_row",
        )
        self.assertEqual(obs["confidence"], "low")
        self.assertEqual(obs["rejection_reason"], "gross_revenue_value_incompatible_with_unit")

    def test_not_found_warning_is_created_for_empty_metric(self):
        warnings = build_operational_warnings(COMPANIES["AALR3"], {metric: [] for metric in all_metric_names()})
        self.assertTrue(any(item["metric"] == "N. Pacientes" and item["status"] == "not_found" for item in warnings))

    def test_rdor_sulamerica_context_does_not_feed_hospital_revenue(self):
        obs = classify_operational_observation(
            COMPANIES["RDOR3"],
            "Receita Bruta",
            label="Receita Bruta",
            value=100,
            context="SulAmérica seguros e previdência",
            extraction_method="markdown_contextual",
        )
        self.assertEqual(obs["confidence"], "low")
        self.assertTrue(obs["requires_review"])

    def test_explicit_proxy_keeps_nature_and_medium_confidence(self):
        obs = classify_operational_observation(
            COMPANIES["MATD3"],
            "N. Pacientes",
            label="pacientes-dia",
            value=1234,
            context="Valores Consolidados - pacientes-dia",
            extraction_method="markdown_contextual",
        )
        self.assertEqual(obs["nature"], "proxy")
        self.assertGreaterEqual(obs["confidence_score"], CONFIDENCE_MEDIUM)
        self.assertFalse(obs["requires_review"])

    def test_dasa_exams_total_feeds_attendance_as_medium_proxy(self):
        workbook = WorkbookSnapshot(
            [
                SheetSnapshot(
                    "2",
                    [
                        ("", "1T26", "2T26"),
                        ("Exames - Total (000s)", 1000, 1200),
                    ],
                )
            ]
        )
        items = extract_metric(COMPANIES["DASA3"], workbook, "N. Atendimentos")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["nature"], "proxy")
        self.assertEqual(items[0]["confidence"], "medium")
        self.assertGreaterEqual(items[0]["confidence_score"], 80)

    def test_fleury_attendance_feeds_patients_as_medium_proxy(self):
        workbook = WorkbookSnapshot(
            [
                SheetSnapshot(
                    "Combinada Outras Informações",
                    [
                        ("", "2025", "2026"),
                        ("Atendimentos", 100, 110),
                    ],
                )
            ]
        )
        items = extract_metric(COMPANIES["FLRY3"], workbook, "N. Pacientes")
        self.assertEqual(items[0]["nature"], "proxy")
        self.assertEqual(items[0]["confidence"], "medium")

    def test_onco_procedures_feed_attendance_as_medium_proxy(self):
        workbook = WorkbookSnapshot(
            [
                SheetSnapshot(
                    "DRE Trimestral",
                    [
                        ("", "1T26", "2T26"),
                        ("Total de Procedimentos", 10, 12),
                    ],
                )
            ]
        )
        items = extract_metric(COMPANIES["ONCO3"], workbook, "N. Atendimentos")
        self.assertEqual(items[0]["nature"], "proxy")
        self.assertEqual(items[0]["confidence"], "medium")

    def test_materdei_broad_tax_deduction_glosa_is_rejected(self):
        workbook = WorkbookSnapshot(
            [
                SheetSnapshot(
                    "Português",
                    [
                        ("", "2025", "2026"),
                        ("Impostos, deduções e glosas", 10, 12),
                    ],
                )
            ]
        )
        self.assertEqual(extract_metric(COMPANIES["MATD3"], workbook, "Glosa/PCLD"), [])


if __name__ == "__main__":
    unittest.main()

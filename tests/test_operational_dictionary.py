import unittest
import tempfile
from pathlib import Path

from app_extrator_operacional import (
    COMPANIES,
    SheetSnapshot,
    WorkbookSnapshot,
    build_operational_warnings,
    classify_operational_observation,
    extract_metric,
    extract_metric_from_markdown,
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

    def test_matd_markdown_table_extracts_patient_days_by_period_as_medium_proxies(self):
        markdown = """
        Rede Mater Dei Release de Resultados
        Página 2
        | Indicador | 1T 26 | 2Q26 |
        | --- | ---: | ---: |
        | Pacientes-Dia | 82.575 | 91.250 |
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MATD3_release_2T26.md"
            path.write_text(markdown, encoding="utf-8")

            atendimentos = extract_metric_from_markdown(COMPANIES["MATD3"], [path], "N. Atendimentos")
            pacientes = extract_metric_from_markdown(COMPANIES["MATD3"], [path], "N. Pacientes")

        for items, metric, warning in (
            (atendimentos, "N. Atendimentos", "Pacientes-dia utilizado como proxy de atendimentos."),
            (pacientes, "N. Pacientes", "Pacientes-dia utilizado como proxy de pacientes; não representa pacientes únicos."),
        ):
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["serie"], {"1T26": 82575, "2T26": 91250})
            self.assertEqual(items[0]["nature"], "proxy")
            self.assertEqual(items[0]["confidence"], "medium")
            self.assertEqual(items[0]["observations"][0]["metric"], metric)
            self.assertEqual(items[0]["observations"][0]["page"], 2)
            self.assertEqual(items[0]["observations"][0]["source_confidence"], "high")
            self.assertEqual(items[0]["observations"][0]["confidence"], "medium")
            self.assertEqual(items[0]["observations"][0]["source_type"], "release_table")
            self.assertEqual(items[0]["observations"][0]["warning"], warning)

    def test_matd_markdown_table_rejects_quarter_or_page_as_patient_day_value(self):
        markdown = """
        Mater Dei
        Page 2
        | Indicador | 1T26 | 2T26 |
        | Pacientes-Dia | 1 | 2 |
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MATD3_release_2T26.md"
            path.write_text(markdown, encoding="utf-8")
            self.assertEqual(extract_metric_from_markdown(COMPANIES["MATD3"], [path], "N. Atendimentos"), [])

    def test_rdor_spreadsheet_patient_days_preserves_hospital_scope_and_all_periods(self):
        workbook = WorkbookSnapshot(
            [
                SheetSnapshot(
                    "Português",
                    [
                        ("Hospitais, oncologia e outros", None, None, None, None, None, None),
                        ("", "1T25", "2T25", "3T25", "4T25", "1T26", "2T26"),
                        ("Pacientes-Dia", 701000, 722000, 735000, 748000, 760000, 777000),
                        ("SulAmérica", None, None, None, None, None, None),
                        ("", "1T25", "2T25", "3T25", "4T25", "1T26", "2T26"),
                        ("Pacientes-Dia", 1, 2, 3, 4, 5, 6),
                    ],
                )
            ]
        )

        atendimentos = extract_metric(COMPANIES["RDOR3"], workbook, "N. Atendimentos")
        pacientes = extract_metric(COMPANIES["RDOR3"], workbook, "N. Pacientes")

        for items in (atendimentos, pacientes):
            self.assertEqual(len(items), 1)
            self.assertEqual(
                items[0]["serie"],
                {
                    "1T25": 701000,
                    "2T25": 722000,
                    "3T25": 735000,
                    "4T25": 748000,
                    "1T26": 760000,
                    "2T26": 777000,
                },
            )
            self.assertEqual(items[0]["escopo"], "Hospitais, oncologia e outros")
            self.assertEqual(items[0]["confidence"], "medium")
            self.assertEqual(items[0]["nature"], "proxy")
            self.assertEqual(items[0]["observations"][0]["source_confidence"], "high")
            self.assertEqual(items[0]["observations"][0]["confidence"], "medium")
            self.assertEqual(items[0]["observations"][0]["sheet"], "Português")


if __name__ == "__main__":
    unittest.main()

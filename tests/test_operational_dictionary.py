import unittest

from app_extrator_operacional import COMPANIES, classify_operational_observation
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


if __name__ == "__main__":
    unittest.main()

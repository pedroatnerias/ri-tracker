import unittest

import app_ciclo_financeiro as ciclo


def bp_payload(values_by_period):
    rows = []
    for code, description, values in values_by_period:
        rows.append({"code": code, "description": description, "values": values})
    return {
        "kind": "balanco_patrimonial_itr_cvm",
        "companies": {
            "TEST3": {
                "scope": "consolidado",
                "periods": ["2024-12-31", "2025-12-31"],
                "rows": rows,
            }
        },
    }


def dre_payload():
    return {
        "kind": "dre_itr_cvm",
        "companies": {
            "TEST3": {
                "tipo_dre": "consolidado",
                "periods": ["2025"],
                "period_metadata": {"2025": {"start_date": "2025-01-01", "end_date": "2025-12-31"}},
                "rows": [
                    {"code": "3.01", "description": "Receita Liquida", "values": {"2025": 1000}},
                    {"code": "3.02", "description": "Custo dos Imoveis Vendidos", "values": {"2025": -400}},
                ],
            }
        },
    }


class CicloFinanceiroSetorialTests(unittest.TestCase):
    def test_saude_preserva_formula_agregada_atual(self):
        payload = bp_payload(
            [
                ("1.01.03", "Contas a receber", {"2024-12-31": 100, "2025-12-31": 200}),
                ("1.02.01.08.01", "Recebiveis imobiliarios", {"2024-12-31": 50, "2025-12-31": 80}),
                ("1.01.04", "Estoques", {"2024-12-31": 300, "2025-12-31": 500}),
                ("2.01.02", "Fornecedores", {"2024-12-31": 50, "2025-12-31": 70}),
            ]
        )
        result = ciclo.calculate(payload, dre_payload=dre_payload(), sector="saude")
        record = result["companies"]["TEST3"][0]
        self.assertNotIn("metodologia", record)
        self.assertAlmostEqual(record["bases_calculo"]["contas_a_receber_medio"], 150)
        self.assertAlmostEqual(record["indicadores_dias"]["PMR"], 54.75)

    def test_construcao_inclui_parcelas_nao_circulantes_sem_dupla_contagem(self):
        payload = bp_payload(
            [
                ("1.01.03", "Contas a receber", {"2024-12-31": 100, "2025-12-31": 200}),
                ("1.02.01.08", "Recebiveis imobiliarios", {"2024-12-31": 999, "2025-12-31": 999}),
                ("1.02.01.08.01", "Recebiveis imobiliarios - curto a longo prazo", {"2024-12-31": 50, "2025-12-31": 80}),
                ("1.02.01.08.02", "Clientes por incorporacao de imoveis", {"2024-12-31": 70, "2025-12-31": 120}),
                ("1.01.04", "Estoques", {"2024-12-31": 300, "2025-12-31": 500}),
                ("1.02.01.04.01", "Terrenos e imoveis a comercializar", {"2024-12-31": 40, "2025-12-31": 100}),
                ("2.01.02", "Fornecedores", {"2024-12-31": 50, "2025-12-31": 70}),
                ("2.02.01.01.01", "Aquisicao de terrenos a pagar", {"2024-12-31": 25, "2025-12-31": 35}),
                ("1.02.01.10", "Aplicacoes financeiras", {"2024-12-31": 1000, "2025-12-31": 1000}),
                ("2.02.01.03", "Emprestimos e financiamentos", {"2024-12-31": 1000, "2025-12-31": 1000}),
            ]
        )
        result = ciclo.calculate(payload, dre_payload=dre_payload(), sector="construcao_civil")
        record = result["companies"]["TEST3"][0]
        self.assertEqual(record["metodologia"], ciclo.CONSTRUCTION_METHODOLOGY)
        self.assertAlmostEqual(record["bases_calculo"]["contas_a_receber_medio"], 310)
        self.assertAlmostEqual(record["bases_calculo"]["estoque_medio"], 470)
        self.assertAlmostEqual(record["bases_calculo"]["fornecedores_medio"], 90)
        selected_codes = {item["codigo"] for item in record["contas_selecionadas"]["contas_a_receber_total"]}
        self.assertNotIn("1.02.01.08", selected_codes)
        self.assertIn("1.02.01.08.01", selected_codes)
        self.assertAlmostEqual(record["indicadores_dias"]["ciclo_financeiro"], 492.2523)


if __name__ == "__main__":
    unittest.main()

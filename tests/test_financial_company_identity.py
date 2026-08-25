import unittest

import pandas as pd

import app_dfc
import app_dre
from company_identity import select_company_rows
from company_registry import company_by_ticker, financial_companies


def dre_row(**overrides):
    row = {
        "CNPJ_CIA": "73.178.600/0001-18",
        "DT_REFER": "2026-03-31",
        "VERSAO": "1",
        "DENOM_CIA": "CYRELA BR REALTY EMP PART",
        "CD_CVM": "14460.0",
        "GRUPO_DFP": "DF Consolidado",
        "MOEDA": "REAL",
        "ESCALA_MOEDA": "MIL",
        "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2026-01-01",
        "DT_FIM_EXERC": "2026-03-31",
        "CD_CONTA": "3.01",
        "DS_CONTA": "Receita de Venda",
        "VL_CONTA": "1000",
        "ST_CONTA_FIXA": "S",
        "ANO_ARQUIVO": 2026,
        "DOCUMENTO_CVM": "ITR",
    }
    row.update(overrides)
    return row


class FinancialCompanyIdentityTests(unittest.TestCase):
    def test_cyre_dre_uses_cd_cvm_despite_abbreviated_name(self):
        result = app_dre.preparar_dre(pd.DataFrame([dre_row()]), company_by_ticker("CYRE3"))
        self.assertEqual(set(result["TICKER"]), {"CYRE3"})
        self.assertEqual(result.iloc[0]["IDENTITY_MATCH"], "cd_cvm")

    def test_cnpj_fallback_when_code_is_missing(self):
        result = select_company_rows(
            pd.DataFrame([dre_row(CD_CVM=None, DENOM_CIA="DENOMINACAO TOTALMENTE DIFERENTE")]),
            company_by_ticker("CYRE3"),
            "DRE",
        )
        self.assertEqual(result.iloc[0]["IDENTITY_MATCH"], "cnpj_fallback")

    def test_conflicting_code_and_cnpj_are_rejected(self):
        base = pd.DataFrame([
            dre_row(CNPJ_CIA="00.000.000/0001-00", DENOM_CIA="OUTRA COMPANHIA"),
            dre_row(CD_CVM="99999", DENOM_CIA="CYRELA PELO CNPJ"),
        ])
        with self.assertRaisesRegex(RuntimeError, "conflito de identidade"):
            select_company_rows(base, company_by_ticker("CYRE3"), "DRE")

    def test_absent_company_error_is_auditable(self):
        with self.assertRaisesRegex(RuntimeError, r"CYRE3.*014460.*73\.178\.600/0001-18.*construcao_civil.*con"):
            select_company_rows(pd.DataFrame([dre_row(CD_CVM="99999", CNPJ_CIA="00.000.000/0001-00")]), company_by_ticker("CYRE3"), "DRE")

    def test_dfc_uses_same_identity_hierarchy(self):
        selected = app_dfc.localizar_companhia(pd.DataFrame([dre_row()]), company_by_ticker("CYRE3"))
        self.assertIsNotNone(selected)
        self.assertEqual(selected.iloc[0]["IDENTITY_MATCH"], "cd_cvm")

    def test_all_financial_companies_have_identifiers_for_dre_and_dfc(self):
        for company in financial_companies("all"):
            with self.subTest(company=company.ticker):
                row = dre_row(CD_CVM=company.cd_cvm, CNPJ_CIA=company.cnpj, DENOM_CIA="ABREVIADA")
                self.assertFalse(select_company_rows(pd.DataFrame([row]), company, "DRE").empty)
                self.assertFalse(select_company_rows(pd.DataFrame([row]), company, "DFC").empty)


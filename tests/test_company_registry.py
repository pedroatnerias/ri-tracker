import unittest

from company_registry import REAL_SECTORS, all_companies, company_by_ticker, companies_for_sector, financial_companies, operational_companies, statement_value_factor
from sector_paths import expand_sectors


class CompanyRegistryTests(unittest.TestCase):
    def test_registry_is_unique_and_sector_isolated(self):
        companies = all_companies()
        self.assertEqual(len(companies), len({c.ticker for c in companies}))
        self.assertTrue(all(c.sector in set(REAL_SECTORS) for c in companies))
        self.assertFalse(set(c.ticker for c in companies_for_sector("saude")) & set(c.ticker for c in companies_for_sector("construcao_civil")))

    def test_requested_construction_universe_and_flags(self):
        expected = {"AVLL3","CALI3","CURY3","CYRE3","DIRR3","EVEN3","EZTC3","FIEI3","GFSA3","HBOR3","INNC3","JFEN3","JHSF3","LAVV3","MDNE3","MELK3","MRVE3","MTRE3","PDGR3","PLPL3","RDNI3","RSID3","TCSA3","TEND3","TRIS3","VIVR3"}
        companies = companies_for_sector("construcao_civil")
        self.assertEqual({c.ticker for c in companies}, expected)
        self.assertTrue(all(c.financial_enabled and c.operational_enabled for c in companies))
        self.assertEqual(company_by_ticker("RDOR3").statement_scope, "ind")

    def test_inc_current_and_legacy_tickers(self):
        current = company_by_ticker("INNC3")
        self.assertEqual(current.yahoo_ticker, "INNC3.SA")
        self.assertEqual(current.legacy_tickers, ("INNT3",))
        self.assertEqual(current.yahoo_tickers, ("INNC3.SA", "INNT3.SA"))
        self.assertEqual(company_by_ticker("INNT3").ticker, "INNC3")
        self.assertNotIn("INNT3", {c.ticker for c in all_companies()})
        with self.assertRaises(ValueError):
            company_by_ticker("INTT3")

    def test_unknown_ticker_is_rejected(self):
        with self.assertRaises(ValueError):
            company_by_ticker("XXXX3")

    def test_retail_universe_capabilities_and_legacy_tickers(self):
        expected = {"ALLD3", "AMAR3", "AMER3", "BHIA3", "CEAB3", "CGRA3", "LJQQ3", "LREN3", "MGLU3", "RIAA3", "SBFG3", "TFCO4", "TOKY3", "VSTE3", "WEST3", "WHRL3"}
        self.assertEqual({c.ticker for c in companies_for_sector("varejo")}, expected)
        self.assertEqual({c.ticker for c in financial_companies("varejo")}, expected)
        self.assertEqual(operational_companies("varejo"), ())
        self.assertEqual(company_by_ticker("GUAR3").ticker, "RIAA3")
        self.assertEqual(company_by_ticker("LLIS3").ticker, "VSTE3")
        self.assertEqual({c.ticker for c in company_by_ticker("CGRA3").share_classes}, {"CGRA3", "CGRA4"})
        self.assertEqual({c.ticker for c in company_by_ticker("WHRL3").share_classes}, {"WHRL3", "WHRL4"})
        self.assertEqual({c.cvm_quantity_scale for c in company_by_ticker("CGRA3").share_classes}, {1})
        self.assertEqual({c.cvm_quantity_scale for c in company_by_ticker("WHRL3").share_classes}, {1_000})
        tfco = company_by_ticker("TFCO4")
        self.assertEqual([c.class_label for c in tfco.share_classes], ["ON", "PN"])
        self.assertEqual([c.economic_weight for c in tfco.share_classes], [0.1, 1.0])
        self.assertFalse(expected & {"SLED3", "AUAU3", "AZZA3"})
        self.assertEqual(expand_sectors("all"), ("saude", "construcao_civil", "varejo"))
        toky = company_by_ticker("TOKY3")
        self.assertEqual(statement_value_factor(toky, "ITR", "2026-06-30", "UNIDADE", 1), 1_000)
        with self.assertRaises(ValueError):
            statement_value_factor(toky, "ITR", "2026-09-30", "UNIDADE", 1)
        self.assertEqual(statement_value_factor(toky, "DFP", "2025-12-31", "MIL", 1_000), 1_000)
        self.assertEqual(statement_value_factor(company_by_ticker("MGLU3"), "ITR", "2026-06-30", "UNIDADE", 1), 1)

    def test_retail_cvm_identifiers_are_the_validated_registry_values(self):
        expected = {
            "ALLD3": ("025330", "20.247.322/0001-47"), "AMAR3": ("022055", "61.189.288/0001-89"),
            "AMER3": ("020990", "00.776.574/0001-56"), "BHIA3": ("006505", "33.041.260/0652-90"),
            "CEAB3": ("024848", "45.242.914/0001-05"), "CGRA3": ("004537", "92.012.467/0001-70"),
            "LJQQ3": ("025038", "96.418.264/0218-02"), "LREN3": ("008133", "92.754.738/0001-62"),
            "MGLU3": ("022470", "47.960.950/0001-21"), "RIAA3": ("004669", "08.402.943/0001-52"),
            "SBFG3": ("024694", "13.217.485/0001-11"), "TFCO4": ("025208", "59.418.806/0001-47"),
            "TOKY3": ("025461", "31.553.627/0001-01"), "VSTE3": ("021440", "49.669.856/0001-43"),
            "WEST3": ("025518", "14.776.142/0001-50"), "WHRL3": ("014346", "59.105.999/0001-86"),
        }
        self.assertEqual({c.ticker: (c.cd_cvm, c.cnpj) for c in companies_for_sector("varejo")}, expected)

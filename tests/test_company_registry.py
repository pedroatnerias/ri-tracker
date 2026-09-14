import unittest

from company_registry import REAL_SECTORS, all_companies, canonical_ticker, company_by_ticker, companies_for_sector, financial_companies, operational_companies, statement_value_factor, tickers_for_sector
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
        self.assertEqual(expand_sectors("all"), ("saude", "construcao_civil", "varejo", "tecnologia"))
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

    def test_technology_universe_capabilities_legacy_and_isolation(self):
        expected = {"BMOB3", "BRQB3", "CASH3", "ECOM3", "IFCM3", "INTB3", "LWSA3", "MLAS3", "PDTC3", "POSI3", "QUSW3", "TOTS3", "WDCN3"}
        companies = companies_for_sector("tecnologia")
        self.assertEqual({c.ticker for c in companies}, expected)
        self.assertEqual({c.ticker for c in financial_companies("tecnologia")}, expected)
        self.assertTrue(all(c.financial_enabled and not c.operational_enabled for c in companies))
        self.assertEqual(operational_companies("tecnologia"), ())
        self.assertEqual(set(tickers_for_sector("tecnologia")), expected)
        self.assertEqual(company_by_ticker("TRAD3").ticker, "ECOM3")
        self.assertEqual(canonical_ticker("TRAD3"), "ECOM3")
        self.assertEqual(company_by_ticker("ECOM3").yahoo_tickers, ("ECOM3.SA", "TRAD3.SA"))
        self.assertEqual(company_by_ticker("LVTC3").ticker, "WDCN3")
        self.assertNotIn("TRAD3", {c.ticker for c in all_companies()})
        self.assertNotIn("TRAD3", tickers_for_sector("tecnologia"))
        other_tickers = set().union(*(set(tickers_for_sector(sector)) for sector in ("saude", "construcao_civil", "varejo")))
        self.assertFalse(expected & other_tickers)

    def test_technology_cvm_identifiers_are_the_validated_registry_values(self):
        expected = {
            "BMOB3": ("025500", "09.042.817/0001-05"), "BRQB3": ("023817", "36.542.025/0001-64"),
            "CASH3": ("025232", "14.110.585/0001-07"), "ECOM3": ("026077", "26.345.998/0001-50"),
            "IFCM3": ("025747", "38.456.921/0001-36"), "INTB3": ("025453", "82.901.000/0001-27"),
            "LWSA3": ("024910", "02.351.877/0001-52"), "MLAS3": ("026034", "59.717.553/0001-02"),
            "PDTC3": ("018414", "02.365.069/0001-44"), "POSI3": ("020362", "81.243.735/0001-48"),
            "QUSW3": ("023302", "35.791.391/0001-94"), "TOTS3": ("019992", "53.113.791/0001-22"),
            "WDCN3": ("025895", "05.917.486/0001-40"),
        }
        self.assertEqual({c.ticker: (c.cd_cvm, c.cnpj) for c in companies_for_sector("tecnologia")}, expected)
        self.assertTrue(all(c.statement_scope == "con" for c in companies_for_sector("tecnologia")))

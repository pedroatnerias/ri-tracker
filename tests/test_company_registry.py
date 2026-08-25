import unittest

from company_registry import all_companies, company_by_ticker, companies_for_sector


class CompanyRegistryTests(unittest.TestCase):
    def test_registry_is_unique_and_sector_isolated(self):
        companies = all_companies()
        self.assertEqual(len(companies), len({c.ticker for c in companies}))
        self.assertTrue(all(c.sector in {"saude", "construcao_civil"} for c in companies))
        self.assertFalse(set(c.ticker for c in companies_for_sector("saude")) & set(c.ticker for c in companies_for_sector("construcao_civil")))

    def test_requested_construction_universe_and_flags(self):
        expected = {"AVLL3","CALI3","CURY3","CYRE3","DIRR3","EVEN3","EZTC3","FIEI3","GFSA3","HBOR3","INNT3","JFEN3","JHSF3","LAVV3","MDNE3","MELK3","MRVE3","MTRE3","PDGR3","PLPL3","RDNI3","RSID3","TCSA3","TEND3","TRIS3","VIVR3"}
        companies = companies_for_sector("construcao_civil")
        self.assertEqual({c.ticker for c in companies}, expected)
        self.assertTrue(all(c.financial_enabled and not c.operational_enabled for c in companies))
        self.assertEqual(company_by_ticker("RDOR3").statement_scope, "ind")

    def test_unknown_ticker_is_rejected(self):
        with self.assertRaises(ValueError):
            company_by_ticker("XXXX3")


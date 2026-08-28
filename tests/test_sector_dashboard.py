import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class SectorDashboardTests(unittest.TestCase):
    @staticmethod
    def operational_payload(ticker):
        return {"ticker": ticker, "sector": "construcao_civil", "metricas": {"Lançamentos": [{
            "metric": "Lançamentos", "indicator_id": "launches_vgv", "confidence": "high",
            "calculated": False, "unit": "BRL_million", "source_document": f"{ticker}_release.pdf",
            "series": {"1T26": 100.0},
        }]}}

    def test_legacy_innt3_is_migrated_only_on_read(self):
        migrated = dashboard.migrate_legacy_company_tickers({"companies": {"INNT3": {"ticker": "INNT3", "ticker_yahoo": "INNT3.SA"}}})
        self.assertNotIn("INNT3", migrated["companies"])
        self.assertEqual(migrated["companies"]["INNC3"]["ticker"], "INNC3")
        self.assertEqual(migrated["companies"]["INNC3"]["ticker_yahoo"], "INNC3.SA")

    def test_sector_endpoints_and_selector(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE":"local"}, clear=False):
            root = Path(tmp)
            for sector, ticker in (("saude","AALR3"),("construcao_civil","CURY3")):
                base=root/sector; base.mkdir()
                for name in ("balancos_itr_cvm_2026.json","DRE_ITR_CVM_ultimos_5_anos.json","DFC_ITR_CVM.json"):
                    (base/name).write_text(json.dumps({"companies":{ticker:{}}}),encoding="utf-8")
            client=dashboard.create_app(root).test_client()
            self.assertIn("Selecione o setor", client.get("/").get_data(as_text=True))
            self.assertEqual(client.get("/api/data?sector=invalid").status_code,400)
            health=client.get("/api/data?sector=saude").get_json()
            construction=client.get("/api/data?sector=construcao_civil").get_json()
            self.assertEqual(health["sector"],"saude")
            self.assertTrue(construction["operational_enabled"])
            self.assertEqual(len(construction["operational_metrics"]), 10)
            self.assertNotIn("AALR3", construction["tickers"])

    def test_local_construction_operational_loading_is_sector_isolated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"NERIAS_DATA_SOURCE": "local"}, clear=False):
            root = Path(tmp)
            base = root / "construcao_civil"
            op = base / "dados_operacionais"
            op.mkdir(parents=True)
            for ticker in ("CYRE3", "AVLL3", "DIRR3", "EZTC3", "AALR3"):
                (op / f"{ticker}.json").write_text(json.dumps(self.operational_payload(ticker)), encoding="utf-8")
            for name in ("balancos_itr_cvm_2026.json", "DRE_ITR_CVM_ultimos_5_anos.json", "DFC_ITR_CVM.json"):
                (base / name).write_text(json.dumps({"companies": {"CYRE3": {}}}), encoding="utf-8")
            payload = dashboard.create_app(root).test_client().get("/api/data?sector=construcao_civil").get_json()
        self.assertEqual(set(payload["operational"]["companies"]), {"CYRE3", "AVLL3", "DIRR3", "EZTC3"})
        item = payload["operational"]["companies"]["CYRE3"]["metricas"]["Lançamentos"][0]
        self.assertEqual(item["series"]["1T26"], 100.0)
        self.assertEqual(item["unit"], "BRL_million")
        self.assertEqual(item["source"], "CYRE3_release.pdf")
        self.assertEqual(payload["operational_coverage"]["companies_with_observations"], 4)
        self.assertEqual(payload["operational_coverage"]["companies_requested"], 26)
        self.assertIn("4/26", payload["operational_coverage"]["warning"])

    def test_health_local_loader_rejects_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = Path(tmp) / "dados_operacionais"
            op.mkdir()
            (op / "CYRE3.json").write_text(json.dumps(self.operational_payload("CYRE3")), encoding="utf-8")
            (op / "AALR3.json").write_text(json.dumps({"ticker": "AALR3", "metricas": {}}), encoding="utf-8")
            data, _meta = dashboard.load_operational_data(Path(tmp), "saude")
        self.assertEqual(set(data["companies"]), {"AALR3"})

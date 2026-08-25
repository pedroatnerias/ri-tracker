import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class SectorDashboardTests(unittest.TestCase):
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
            self.assertFalse(construction["operational_enabled"])
            self.assertNotIn("AALR3", construction["tickers"])


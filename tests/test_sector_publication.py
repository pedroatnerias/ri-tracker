import json
import tempfile
import unittest
from pathlib import Path

import data_publication


def financial_outputs(base: Path, ticker: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    payload = {"source": "test", "companies": {ticker: {}}}
    (base / "balancos_itr_cvm_2026.json").write_text(json.dumps(payload), encoding="utf-8")
    for name in data_publication.REQUIRED_ROOT_JSONS:
        (base / name).write_text(json.dumps(payload), encoding="utf-8")


class SectorPublicationTests(unittest.TestCase):
    def test_financial_publications_preserve_other_sector_and_manifest_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "repo" / "data"
            financial_outputs(source / "saude", "AALR3")
            financial_outputs(source / "construcao_civil", "CURY3")
            for sector in ("saude", "construcao_civil"):
                data_publication.validate_results(source, "financial", sector)
                data_publication.publish_validated_data(source, target, "commit", "run", "financial", sector)
            self.assertTrue((target / "sectors" / "saude" / "indicadores.json").exists())
            self.assertTrue((target / "sectors" / "construcao_civil" / "indicadores.json").exists())
            manifest = json.loads((target / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(set(manifest["sectors"]), {"saude", "construcao_civil"})

    def test_construction_operational_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                data_publication.validate_results(Path(tmp), "operational", "construcao_civil")

import json
import tempfile
import unittest
from pathlib import Path

import data_publication

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 600


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

    def test_sector_charts_are_published_under_sector_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resultados"
            target = root / "repo" / "data"
            financial_outputs(source / "construcao_civil", "CURY3")
            chart = source / "construcao_civil" / "charts" / "comparison" / "margem_bruta.png"
            chart.parent.mkdir(parents=True, exist_ok=True)
            chart.write_bytes(PNG_BYTES)

            manifest = data_publication.validate_results(source, "financial", "construcao_civil")
            metadata = data_publication.publish_validated_data(source, target, "commit", "run", "financial", "construcao_civil")

            self.assertEqual(manifest["chart_pngs"], ["charts/comparison/margem_bruta.png"])
            self.assertTrue((target.parent / "charts" / "construcao_civil" / "comparison" / "margem_bruta.png").exists())
            self.assertEqual(metadata["charts"]["comparison"], {"margem_bruta": "charts/comparison/margem_bruta.png"})

    def test_operational_quality_report_separates_state_files_from_valid_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "construcao_civil"
            op = base / "dados_operacionais"
            op.mkdir(parents=True)
            (op / "CYRE3.json").write_text(json.dumps({
                "ticker": "CYRE3", "sector": "construcao_civil", "status": "success",
                "observations": [{"ticker": "CYRE3", "indicator_id": "launches_vgv", "period": "1T26", "value": 0, "unit": "BRL_million", "source_document": "CYRE3.pdf", "confidence": "high", "validation_status": "valid"}],
                "metricas": {"Lançamentos": []},
            }), encoding="utf-8")
            (op / "CURY3.json").write_text(json.dumps({"ticker": "CURY3", "sector": "construcao_civil", "status": "not_found", "observations": [], "metricas": {}}), encoding="utf-8")
            (op / "EZTC3.json").write_text(json.dumps({
                "ticker": "EZTC3", "sector": "construcao_civil", "status": "success",
                "observations": [{"ticker": "EZTC3", "indicator_id": "landbank_vgv", "period": "1T26", "value": .000814, "unit": "BRL_million", "source_document": "EZTC3.pdf", "confidence": "high", "validation_status": "quarantined_scale"}],
                "metricas": {"Banco de terras": []},
            }), encoding="utf-8")
            (base / "data_manifest.json").write_text(json.dumps({"operational_jsons": ["dados_operacionais/CYRE3.json", "dados_operacionais/CURY3.json", "dados_operacionais/EZTC3.json"]}), encoding="utf-8")
            report = data_publication.build_operational_quality_report(Path(tmp), "construcao_civil")
        self.assertEqual(report["companies_with_valid_observations"], 1)
        self.assertEqual(report["companies_not_found"], 1)
        self.assertEqual(report["companies_quarantined_only"], 1)
        self.assertEqual(report["zero_observations"], 1)
        self.assertIn("Cobertura parcial", report["warnings"][0])

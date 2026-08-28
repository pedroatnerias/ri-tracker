import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_extrator_operacional
import app_parser_operacional
import data_publication
from company_registry import operational_companies
from operational_sources import OPERATIONAL_RI_SOURCES, operational_sources_for_sector
from sector_paths import resolve_releases_input_dir, resolve_releases_output_dir


class OperationalSectorIsolationTests(unittest.TestCase):
    def test_construction_source_registry_has_exact_operational_universe(self):
        expected = {company.ticker for company in operational_companies("construcao_civil")}
        self.assertEqual(set(operational_sources_for_sector("construcao_civil")), expected)
        self.assertEqual(OPERATIONAL_RI_SOURCES["construcao_civil"]["INNC3"]["legacy_tickers"], ["INNT3"])
        self.assertNotIn("RDOR3", OPERATIONAL_RI_SOURCES["construcao_civil"])

    def test_release_paths_are_isolated_by_sector(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertNotEqual(resolve_releases_input_dir(base, "saude"), resolve_releases_input_dir(base, "construcao_civil"))
            self.assertNotEqual(resolve_releases_output_dir(base, "saude"), resolve_releases_output_dir(base, "construcao_civil"))

    def test_parser_download_uses_only_selected_sector_sources(self):
        sources = {"CURY3": operational_sources_for_sector("construcao_civil")["CURY3"]}
        seen = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_parser_operacional, "coletar_documentos_empresa", side_effect=lambda **kwargs: seen.append(kwargs["ticker"]) or []):
            app_parser_operacional.baixar_documentos_ri(
                2025, None, False, False, sector="construcao_civil", companies=sources,
                input_dir=Path(tmp) / "in", manifest_path=Path(tmp) / "manifest.json",
            )
        self.assertEqual(seen, ["CURY3"])

    def test_construction_extractor_ignores_residual_health_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "md"
            output = root / "out"
            markdown.mkdir()
            (markdown / "CURY3_previa_1T26.md").write_text(
                "# Prévia operacional (R$ milhões) - participação da companhia\n| Indicador | 1T26 |\n|---|---:|\n| VGV lançado | 250 |",
                encoding="utf-8",
            )
            (markdown / "RDOR3_release_1T26.md").write_text(
                "# Saúde\n| Indicador | 1T26 |\n|---|---:|\n| VGV lançado | 999 |",
                encoding="utf-8",
            )
            args = app_extrator_operacional.build_parser().parse_args([
                "--sector", "construcao_civil", "--md-dir", str(markdown), "--output-dir", str(output),
            ])
            self.assertEqual(asyncio.run(app_extrator_operacional.run(args)), 0)
            self.assertTrue((output / "CURY3.json").exists())
            self.assertFalse((output / "RDOR3.json").exists())
            payload = json.loads((output / "CURY3.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["observations"])
            self.assertTrue(all(item["ticker"] == "CURY3" for item in payload["observations"]))

    def test_offline_rebuild_snapshot_is_found_by_publication_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "fixtures" / "construcao_civil"
            output = root / "resultados" / "construcao_civil" / "dados_operacionais"
            markdown.mkdir(parents=True)
            (markdown / "CURY3_previa_1T26.md").write_text(
                "# Prévia operacional (R$ milhões) - participação da companhia\n| Indicador | 1T26 |\n|---|---:|\n| Vendas líquidas | 180 |",
                encoding="utf-8",
            )
            (markdown / "RDOR3_residual.md").write_text(
                "# Residual saúde\n| Indicador | 1T26 |\n|---|---:|\n| Vendas líquidas | 999 |",
                encoding="utf-8",
            )
            args = app_extrator_operacional.build_parser().parse_args([
                "--sector", "construcao_civil", "--md-dir", str(markdown), "--output-dir", str(output),
            ])
            self.assertEqual(asyncio.run(app_extrator_operacional.run(args)), 0)
            manifest = data_publication.validate_results(root / "resultados", "operational", "construcao_civil")
            self.assertEqual(manifest["operational_jsons"], ["dados_operacionais/CURY3.json"])

    def test_empty_construction_extraction_fails_without_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "md").mkdir()
            args = app_extrator_operacional.build_parser().parse_args([
                "--sector", "construcao_civil", "--md-dir", str(root / "md"), "--output-dir", str(root / "out"),
            ])
            self.assertEqual(asyncio.run(app_extrator_operacional.run(args)), 1)
            self.assertFalse((root / "out" / "operational_observations.json").exists())

    def test_validator_rejects_wrong_sector_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "construcao_civil" / "dados_operacionais" / "CURY3.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"sector": "saude", "ticker": "CURY3", "observations": [{}]}), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "pertence ao setor"):
                data_publication.validate_results(Path(tmp), "operational", "construcao_civil")


if __name__ == "__main__":
    unittest.main()

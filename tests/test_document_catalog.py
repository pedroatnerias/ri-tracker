import tempfile
import unittest
from pathlib import Path

from document_catalog import catalog_record, write_catalog


class DocumentCatalogTests(unittest.TestCase):
    def test_catalog_has_stable_hash_and_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.pdf"
            path.write_bytes(b"%PDF-test")
            record = catalog_record(path, ticker="CYRE3", source_url="https://ri.example/release.pdf")
            self.assertEqual(record["ticker"], "CYRE3")
            self.assertEqual(record["source_domain"], "ri.example")
            self.assertEqual(len(record["sha256"]), 64)
            output = write_catalog([record], Path(tmp) / "catalog.json")
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()

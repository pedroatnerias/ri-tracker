import unittest
from pathlib import Path
import tempfile

from construction_benchmark import run


class ConstructionBenchmarkTests(unittest.TestCase):
    def test_empty_offline_fixture_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(run(root, root), {"mode": "offline", "companies": {}, "source_policy": "official_ri_pdf_only"})


if __name__ == "__main__":
    unittest.main()

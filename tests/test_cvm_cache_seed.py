import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from cvm_cache_seed import seed_cvm_cache
from cvm_downloads import validate_zip


def write_bp_zip(path: Path, year: int, doc: str) -> None:
    prefix = "dfp" if doc == "dfp" else "itr"
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for statement in ("BPA", "BPP"):
            for scope in ("con", "ind"):
                archive.writestr(f"{prefix}_cia_aberta_{statement}_{scope}_{year}.csv", "x;y\n1;2\n")
        for scope in ("con", "ind"):
            archive.writestr(f"{prefix}_cia_aberta_DRE_{scope}_{year}.csv", "x;y\n1;2\n")
            for method in ("MD", "MI"):
                archive.writestr(f"{prefix}_cia_aberta_DFC_{method}_{scope}_{year}.csv", "x;y\n1;2\n")
        archive.writestr("padding.txt", "0" * 2048)
    path.write_bytes(buffer.getvalue())


class CvmCacheSeedTests(unittest.TestCase):
    def test_copies_valid_itr_and_dfp_from_another_sector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_bp_zip(root / "saude/downloads/itr/itr_cia_aberta_2025.zip", 2025, "itr")
            write_bp_zip(root / "saude/downloads/dfp/dfp_cia_aberta_2025.zip", 2025, "dfp")

            copied = seed_cvm_cache(root, "tecnologia")

            self.assertEqual(len(copied), 2)
            self.assertTrue(validate_zip(root / "tecnologia/downloads/itr/itr_cia_aberta_2025.zip", 2025, "itr", "dre"))
            self.assertTrue(validate_zip(root / "tecnologia/downloads/dfp/dfp_cia_aberta_2025.zip", 2025, "dfp", "dfc"))

    def test_rejects_invalid_source_and_preserves_valid_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid = root / "saude/downloads/itr/itr_cia_aberta_2025.zip"
            invalid.parent.mkdir(parents=True)
            invalid.write_bytes(b"not-a-zip")
            target = root / "tecnologia/downloads/itr/itr_cia_aberta_2024.zip"
            write_bp_zip(target, 2024, "itr")
            before = target.read_bytes()

            copied = seed_cvm_cache(root, "tecnologia")

            self.assertEqual(copied, [])
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse((target.parent / "itr_cia_aberta_2025.zip").exists())


if __name__ == "__main__":
    unittest.main()

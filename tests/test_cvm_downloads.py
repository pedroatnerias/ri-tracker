import io
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from cvm_downloads import CvmDownloadError, CvmDownloadPolicy, fetch_cvm_zip, validate_zip


def zip_bytes(year=2022):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name in (
            f"itr_cia_aberta_BPA_con_{year}.csv",
            f"itr_cia_aberta_BPP_con_{year}.csv",
            f"itr_cia_aberta_BPA_ind_{year}.csv",
            f"itr_cia_aberta_BPP_ind_{year}.csv",
        ):
            zf.writestr(name, "x;y\n1;2\n")
        zf.writestr("padding.txt", "0" * 2048)
    return buffer.getvalue()


class FakeResponse:
    headers = {"Content-Type": "application/zip", "ETag": "abc", "Last-Modified": "today"}

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        self._body = io.BytesIO(self.payload)
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self._body.read(size)


class CvmDownloadsTests(unittest.TestCase):
    def test_download_success_is_atomic_and_valid(self):
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen", return_value=FakeResponse(zip_bytes())):
            path, events = fetch_cvm_zip(
                url="https://example/itr.zip",
                year=2022,
                doc="itr",
                destination=Path(tmp),
                filename="itr_cia_aberta_2022.zip",
                user_agent="test",
                policy=CvmDownloadPolicy(refresh="force", max_attempts=1),
            )
            self.assertTrue(validate_zip(path, 2022, "itr", "bp"))
            self.assertEqual(events[-1].next_action, "stored_atomic")

    def test_auto_falls_back_to_valid_cache_on_network_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cached = Path(tmp) / "itr_cia_aberta_2022.zip"
            cached.write_bytes(zip_bytes())
            reason = OSError(101, "Network is unreachable")
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(reason)):
                path, events = fetch_cvm_zip(
                    url="https://example/itr.zip",
                    year=2022,
                    doc="itr",
                    destination=Path(tmp),
                    filename=cached.name,
                    user_agent="test",
                    policy=CvmDownloadPolicy(refresh="auto", max_attempts=5),
                    sleep=lambda _seconds: None,
                )
            self.assertEqual(path, cached)
            self.assertEqual(events[-1].next_action, "reuse_valid_cache")

    def test_force_preserves_valid_previous_file_when_download_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cached = Path(tmp) / "itr_cia_aberta_2022.zip"
            original = zip_bytes()
            cached.write_bytes(original)
            with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 503, "down", {}, None)):
                with self.assertRaises(CvmDownloadError):
                    fetch_cvm_zip(
                        url="https://example/itr.zip",
                        year=2022,
                        doc="itr",
                        destination=Path(tmp),
                        filename=cached.name,
                        user_agent="test",
                        policy=CvmDownloadPolicy(refresh="force", max_attempts=2, backoff_seconds=(0,)),
                        sleep=lambda _seconds: None,
                    )
            self.assertEqual(cached.read_bytes(), original)

    def test_never_prohibits_network_and_requires_local_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen") as mocked:
            with self.assertRaises(CvmDownloadError):
                fetch_cvm_zip(
                    url="https://example/itr.zip",
                    year=2022,
                    doc="itr",
                    destination=Path(tmp),
                    filename="itr_cia_aberta_2022.zip",
                    user_agent="test",
                    policy=CvmDownloadPolicy(refresh="never"),
                )
            mocked.assert_not_called()

    def test_404_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 404, "missing", {}, None)):
            with self.assertRaises(CvmDownloadError) as ctx:
                fetch_cvm_zip(
                    url="https://example/itr.zip",
                    year=2022,
                    doc="itr",
                    destination=Path(tmp),
                    filename="itr_cia_aberta_2022.zip",
                    user_agent="test",
                    policy=CvmDownloadPolicy(refresh="force", max_attempts=5),
                    sleep=lambda _seconds: None,
                )
            self.assertEqual(len(ctx.exception.events), 1)


if __name__ == "__main__":
    unittest.main()

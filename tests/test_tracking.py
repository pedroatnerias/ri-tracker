import json
import tempfile
import unittest
from pathlib import Path

from tracking import TrackingRun, stable_document_id, tracking_summary_for_publication


class TrackingTests(unittest.TestCase):
    def test_document_count_does_not_depend_on_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.pdf"
            path.write_bytes(b"%PDF-1.7")
            run = TrackingRun(sector="construcao_civil", pipeline="test", extractor_version="test")
            document_id = run.document(path, source_type="PDF", ticker="CYRE3")
            run.event(document_id, "accepted")
            run.event(document_id, "read", characters=0)
            run.event(document_id, "validated", observations_count=0)
            summary = run.summary()
            self.assertEqual(summary["documents_found"], 1)
            self.assertEqual(summary["documents_processed"], 1)
            self.assertEqual(summary["documents_with_observations"], 0)

    def test_id_is_stable_and_summary_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.pdf"
            path.write_bytes(b"same")
            self.assertEqual(stable_document_id(path), stable_document_id(path))
            run = TrackingRun(sector="saude", pipeline="test", extractor_version="test")
            document_id = run.document(path, source_type="XLSX")
            run.event(document_id, "extraction_error", error="private detail")
            safe = tracking_summary_for_publication(run.payload())
            self.assertIn("documents_with_errors", safe)
            self.assertNotIn("events", safe)

    def test_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "tracking.json"
            run = TrackingRun(sector="saude", pipeline="test", extractor_version="test")
            run.write(output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["summary"]["documents_found"], 0)

    def test_invalid_transition_is_rejected(self):
        run = TrackingRun(sector="saude", pipeline="test", extractor_version="test")
        document_id = run.document(source_url="https://example.test/file.xlsx", source_type="XLSX")
        with self.assertRaises(ValueError):
            run.event(document_id, "published")

    def test_reserved_event_fields_are_rejected(self):
        run = TrackingRun(sector="saude", pipeline="test", extractor_version="test")
        document_id = run.document(source_url="https://example.test/file.xlsx", source_type="XLSX")
        with self.assertRaises(ValueError):
            run.event(document_id, "accepted", run_id="another-id")


if __name__ == "__main__":
    unittest.main()

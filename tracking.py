"""Common, append-only execution and document tracking.

The tracker is deliberately dependency-free so every extractor and the CI
orchestrator can use the same contract. Detailed events stay in the local
execution artifact; callers may derive a safe summary for publication.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EVENTS = frozenset({
    "discovered", "accepted", "downloaded", "imported", "converted", "read",
    "company_resolved", "parsed", "validated", "published", "preserved_existing",
    "rejected", "unresolved", "extraction_error",
})
TERMINAL_EVENTS = frozenset({"published", "preserved_existing", "rejected", "unresolved", "extraction_error"})
ALLOWED_TRANSITIONS = {
    None: {"discovered"},
    "discovered": {"discovered", "accepted", "rejected", "extraction_error"},
    "accepted": {"accepted", "downloaded", "imported", "converted", "read", "published", "rejected", "extraction_error"},
    "downloaded": {"imported", "converted", "read", "extraction_error"},
    "imported": {"converted", "read", "extraction_error"},
    "converted": {"read", "extraction_error"},
    "read": {"company_resolved", "parsed", "validated", "unresolved", "extraction_error"},
    "company_resolved": {"parsed", "validated", "unresolved", "extraction_error"},
    "parsed": {"validated", "published", "rejected", "extraction_error"},
    "validated": {"published", "preserved_existing", "rejected", "extraction_error"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_document_id(path: str | Path | None = None, *, content: bytes | None = None, source_url: str = "") -> str:
    if content is None and path:
        candidate = Path(path)
        if candidate.exists() and candidate.is_file():
            content = candidate.read_bytes()
    digest = hashlib.sha256(content or b"").hexdigest()
    origin = source_url or (str(path) if path else "")
    return hashlib.sha256(f"{origin}\0{digest}".encode("utf-8")).hexdigest()


class TrackingRun:
    def __init__(self, *, sector: str, pipeline: str, extractor_version: str, run_id: str | None = None) -> None:
        self.run_id = run_id or os.environ.get("GITHUB_RUN_ID") or str(uuid.uuid4())
        self.started_at = utc_now()
        self.sector = sector
        self.pipeline = pipeline
        self.extractor_version = extractor_version
        self.events: list[dict[str, Any]] = []
        self._documents: dict[str, dict[str, Any]] = {}

    def event(self, document_id: str, state: str, **fields: Any) -> dict[str, Any]:
        if state not in EVENTS:
            raise ValueError(f"tracking state invalid: {state}")
        previous = self._documents.get(document_id, {}).get("last_state")
        if previous in TERMINAL_EVENTS:
            raise ValueError(f"tracking document is terminal: {document_id}")
        if state != "discovered" and state not in ALLOWED_TRANSITIONS.get(previous, set()):
            raise ValueError(f"invalid tracking transition: {previous!r} -> {state!r}")
        timestamp = utc_now()
        record = {"run_id": self.run_id, "document_id": document_id, "state": state, "at": timestamp, **fields}
        self.events.append(record)
        document = self._documents.setdefault(document_id, {"document_id": document_id, "events": []})
        document["events"].append(record)
        document["last_state"] = state
        document.update({key: value for key, value in fields.items() if value is not None})
        return record

    def document(self, path: str | Path | None = None, *, content: bytes | None = None, source_url: str = "", source_type: str | None = None, **fields: Any) -> str:
        document_id = stable_document_id(path, content=content, source_url=source_url)
        record: dict[str, Any] = {"document_id": document_id, "source_url": source_url, **fields}
        if path:
            candidate = Path(path)
            record.update({"path": str(candidate), "original_name": candidate.name})
            if candidate.exists() and candidate.is_file():
                record["bytes"] = candidate.stat().st_size
                record["mime_type"] = mimetypes.guess_type(candidate.name)[0]
        if source_url:
            record["domain"] = urlparse(source_url).netloc.lower()
        if source_type:
            record["source_type"] = source_type
        is_new = document_id not in self._documents
        self._documents.setdefault(document_id, {"document_id": document_id, **record, "events": []})
        if is_new:
            self.event(document_id, "discovered", **record)
        return document_id

    def summary(self) -> dict[str, Any]:
        states = [item.get("last_state") for item in self._documents.values()]
        return {
            "run_id": self.run_id, "sector": self.sector, "pipeline": self.pipeline,
            "extractor_version": self.extractor_version, "started_at": self.started_at,
            "finished_at": utc_now(), "documents_found": len(self._documents),
            "documents_accepted": sum(1 for item in self._documents.values() if any(e["state"] == "accepted" for e in item["events"])),
            "documents_processed": sum(1 for state in states if state in {"read", "company_resolved", "parsed", "validated", "published"}),
            "documents_with_observations": sum(1 for item in self._documents.values() if item.get("observations_count", 0) > 0),
            "documents_unresolved": sum(1 for state in states if state == "unresolved"),
            "documents_with_errors": sum(1 for state in states if state == "extraction_error"),
            "documents_rejected": sum(1 for state in states if state == "rejected"),
            "events_count": len(self.events), "coverage_status": self._coverage(states),
        }

    def _coverage(self, states: list[str | None]) -> str:
        if not states:
            return "none"
        processed = sum(state in {"read", "company_resolved", "parsed", "validated", "published"} for state in states)
        return "complete" if processed == len(states) else ("partial" if processed else "none")

    def payload(self) -> dict[str, Any]:
        return {"schema_version": 1, "summary": self.summary(), "documents": list(self._documents.values()), "events": self.events}

    def write(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return output


def tracking_summary_for_publication(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    allowed = ("run_id", "sector", "pipeline", "extractor_version", "started_at", "finished_at", "documents_found", "documents_processed", "documents_with_observations", "documents_unresolved", "documents_with_errors", "coverage_status")
    return {key: summary[key] for key in allowed if key in summary}

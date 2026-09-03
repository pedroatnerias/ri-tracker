"""Auditable local catalog for official RI PDF discovery."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


def catalog_record(path: Path, *, ticker: str | None = None, source_url: str | None = None, method: str = "official_ri") -> dict[str, Any]:
    data = path.read_bytes()
    parsed = urlparse(source_url or "")
    return {
        "document_id": hashlib.sha256(data).hexdigest()[:20],
        "file_name": path.name,
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "ticker": ticker,
        "source_url": source_url,
        "source_domain": parsed.netloc.lower() or None,
        "discovery_method": method,
        "discovered_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_catalog(records: list[dict[str, Any]], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "documents": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    return output

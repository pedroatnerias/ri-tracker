"""Download resiliente e cache atomico dos ZIPs CVM."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


RECOVERABLE_HTTP = {429, 500, 502, 503, 504}
PERMANENT_HTTP = {403, 404}
DEFAULT_BACKOFF_SECONDS = (5, 15, 30, 60, 120)
MIN_ZIP_BYTES = 1024


@dataclass(frozen=True)
class CvmDownloadPolicy:
    refresh: str = "auto"
    max_attempts: int = 5
    timeout: int = 120
    backoff_seconds: tuple[int, ...] = DEFAULT_BACKOFF_SECONDS


@dataclass
class CvmDownloadEvent:
    url: str
    year: int
    doc: str
    attempt: int
    error_type: str | None = None
    http_status: int | None = None
    duration_seconds: float = 0.0
    next_action: str = ""
    fallback_used: bool = False
    reused_path: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    checksum_sha256: str | None = None
    size_bytes: int | None = None


class CvmDownloadError(RuntimeError):
    def __init__(self, message: str, events: list[CvmDownloadEvent], original: Exception | None = None):
        super().__init__(message)
        self.events = events
        self.original = original


def expected_members(doc: str, year: int, kind: str = "bp") -> set[str]:
    prefix = "dfp" if doc == "dfp" else "itr"
    if kind == "dre":
        return {f"{prefix}_cia_aberta_DRE_con_{year}.csv", f"{prefix}_cia_aberta_DRE_ind_{year}.csv"}
    if kind == "dfc":
        return {
            f"{prefix}_cia_aberta_DFC_MD_con_{year}.csv",
            f"{prefix}_cia_aberta_DFC_MI_con_{year}.csv",
            f"{prefix}_cia_aberta_DFC_MD_ind_{year}.csv",
            f"{prefix}_cia_aberta_DFC_MI_ind_{year}.csv",
        }
    return {
        f"{prefix}_cia_aberta_BPA_con_{year}.csv",
        f"{prefix}_cia_aberta_BPP_con_{year}.csv",
        f"{prefix}_cia_aberta_BPA_ind_{year}.csv",
        f"{prefix}_cia_aberta_BPP_ind_{year}.csv",
    }


def validate_zip(path: Path, year: int, doc: str, kind: str = "bp") -> bool:
    if not path.exists() or path.stat().st_size < MIN_ZIP_BYTES:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return archive.testzip() is None and expected_members(doc, year, kind).issubset(names)
    except (OSError, zipfile.BadZipFile):
        return False


def classify_error(exc: Exception) -> tuple[str, int | None, bool]:
    if isinstance(exc, urllib.error.HTTPError):
        status = int(exc.code)
        return f"http_{status}", status, status in RECOVERABLE_HTTP
    if isinstance(exc, TimeoutError):
        return "timeout", None, True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "timeout", None, True
        if isinstance(reason, socket.gaierror):
            return "dns_resolution_failed", None, True
        if isinstance(reason, OSError) and getattr(reason, "errno", None) == 101:
            return "network_unreachable", None, True
        if isinstance(reason, ConnectionRefusedError):
            return "connection_refused", None, True
        return "network_error", None, True
    if isinstance(exc, zipfile.BadZipFile):
        return "invalid_zip", None, False
    return exc.__class__.__name__, None, isinstance(exc, (ConnectionError, OSError))


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_cvm_zip(
    *,
    url: str,
    year: int,
    doc: str,
    destination: Path,
    filename: str,
    user_agent: str,
    kind: str = "bp",
    policy: CvmDownloadPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Path, list[CvmDownloadEvent]]:
    policy = policy or CvmDownloadPolicy()
    if policy.refresh not in {"auto", "force", "never"}:
        raise ValueError(f"refresh_cvm_files invalido: {policy.refresh}")
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / filename
    events: list[CvmDownloadEvent] = []
    has_valid_local = validate_zip(output, year, doc, kind)

    if policy.refresh == "never":
        if has_valid_local:
            events.append(CvmDownloadEvent(url, year, doc.upper(), 0, next_action="reuse_local", reused_path=str(output)))
            return output, events
        raise CvmDownloadError(f"ZIP CVM ausente em modo refresh=never: {output}", events)

    if has_valid_local and policy.refresh == "auto":
        events.append(CvmDownloadEvent(url, year, doc.upper(), 0, next_action="reuse_valid_cache", reused_path=str(output), checksum_sha256=checksum(output), size_bytes=output.stat().st_size))
        return output, events

    last_error: Exception | None = None
    max_attempts = max(1, policy.max_attempts)
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        temporary: Path | None = None
        event = CvmDownloadEvent(url=url, year=year, doc=doc.upper(), attempt=attempt)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=policy.timeout) as response:
                event.etag = response.headers.get("ETag")
                event.last_modified = response.headers.get("Last-Modified")
                content_type = response.headers.get("Content-Type", "").lower()
                if "html" in content_type:
                    raise RuntimeError("content_type_html")
                with tempfile.NamedTemporaryFile(prefix=f"{doc}_{year}_", suffix=".zip", dir=destination, delete=False) as temp_file:
                    temporary = Path(temp_file.name)
                    shutil.copyfileobj(response, temp_file, length=1024 * 1024)
            event.size_bytes = temporary.stat().st_size if temporary else None
            if temporary is None or not validate_zip(temporary, year, doc, kind):
                raise zipfile.BadZipFile("download_incompleto_zip_invalido_ou_csv_ausente")
            event.checksum_sha256 = checksum(temporary)
            os.replace(temporary, output)
            event.duration_seconds = round(time.monotonic() - started, 3)
            event.next_action = "stored_atomic"
            events.append(event)
            return output, events
        except Exception as exc:
            last_error = exc
            if temporary and temporary.exists():
                temporary.unlink()
            error_type, status, recoverable = classify_error(exc)
            event.error_type = error_type
            event.http_status = status
            event.duration_seconds = round(time.monotonic() - started, 3)
            if has_valid_local and policy.refresh == "auto":
                event.next_action = "fallback_to_valid_cache"
                event.fallback_used = True
                event.reused_path = str(output)
                events.append(event)
                logging.warning("CVM %s %s indisponivel (%s); reutilizando cache valido: %s", doc.upper(), year, error_type, output)
                return output, events
            should_retry = recoverable and attempt < max_attempts and status not in PERMANENT_HTTP
            event.next_action = "retry" if should_retry else "fail"
            events.append(event)
            if should_retry:
                wait = policy.backoff_seconds[min(attempt - 1, len(policy.backoff_seconds) - 1)]
                logging.warning("Falha CVM %s %s tentativa %s/%s: %s. Nova tentativa em %ss.", doc.upper(), year, attempt, max_attempts, error_type, wait)
                sleep(wait)
                continue
            break

    raise CvmDownloadError(
        f"Nao foi possivel obter ZIP CVM {doc.upper()} {year}; ultimo erro: {last_error}",
        events,
        last_error,
    )


def write_events_json(path: Path, events: list[CvmDownloadEvent]) -> None:
    import json

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": [event.__dict__ for event in events],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

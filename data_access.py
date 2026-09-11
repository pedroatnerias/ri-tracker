"""Shared local JSON access primitives.

Higher-level modules retain their public helpers so legacy callers keep their
error and fallback behavior; this module only centralizes file decoding.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_json_if_exists(path: Path) -> dict[str, object] | None:
    path = Path(path)
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Grava texto por substituição atômica no mesmo diretório."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def atomic_write_json(path: Path, payload: object, *, indent: int = 2) -> Path:
    """Serializa JSON e o grava por substituição atômica."""
    return atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent) + "\n")

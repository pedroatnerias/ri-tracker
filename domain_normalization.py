"""Shared, side-effect-free normalization primitives.

Domain modules keep their public adapter names and may add domain-specific
rules, while this module owns the common text cleanup behavior.
"""

from __future__ import annotations

import unicodedata
import re
import math
from typing import Any


MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð", "�")


def repair_mojibake(value: Any) -> str:
    """Repair common UTF-8-as-Windows-1252 corruption when unambiguous."""
    text = str(value or "")
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    before = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    after = sum(repaired.count(marker) for marker in MOJIBAKE_MARKERS)
    return repaired if after < before else text


def normalize_text(value: Any, *, repair: bool = True, strip_accents: bool = True) -> str:
    """Normalize text for matching while preserving the original value elsewhere."""
    text = repair_mojibake(value) if repair else str(value or "")
    if strip_accents:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
    else:
        text = unicodedata.normalize("NFC", text)
    return " ".join(text.lower().split())


def normalize_identifier(value: Any, *, uppercase: bool = False) -> str:
    """Normalize an identifier by removing accents and non-alphanumeric runs."""
    text = normalize_text(value, repair=False, strip_accents=True)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    text = " ".join(text.split())
    return text.upper() if uppercase else text


def normalize_filename(value: Any) -> str:
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text.strip("._-") or "documento"


def coerce_number(value: Any) -> float | None:
    """Coerce JSON/locale numeric values, returning None for invalid values."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    try:
        return float(text.replace(".", "").replace(",", ".") if "," in text else text)
    except ValueError:
        return None

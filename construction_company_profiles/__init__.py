"""Declarative extraction profiles for construction companies.

Profiles are intentionally data-only.  The generic extractor owns the logic;
this package only records presentation differences learned from review matrices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(__file__).parent
PROFILE_SCHEMA_VERSION = 1


def load_profile(ticker: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        return {"schema_version": PROFILE_SCHEMA_VERSION, "ticker": ticker.upper()}
    profile = json.loads(path.read_text(encoding="utf-8"))
    validate_profile(profile)
    return profile


def validate_profile(profile: dict[str, Any]) -> None:
    required = {"schema_version", "ticker", "metrics"}
    missing = required - set(profile)
    if missing:
        raise ValueError(f"perfil inválido: campos ausentes {sorted(missing)}")
    if profile["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"schema de perfil não suportado: {profile['schema_version']}")
    if not isinstance(profile["metrics"], dict):
        raise ValueError("perfil inválido: metrics deve ser objeto")
    for metric, rules in profile["metrics"].items():
        if not isinstance(rules, dict):
            raise ValueError(f"perfil inválido: regras de {metric} devem ser objeto")
        for key in ("positive_aliases", "negative_aliases", "preferred_sources"):
            if key in rules and not isinstance(rules[key], list):
                raise ValueError(f"perfil inválido: {metric}.{key} deve ser lista")


def profile_for(ticker: str) -> dict[str, Any]:
    return load_profile(ticker)

"""Declarative extraction profiles for construction companies.

Profiles are intentionally data-only.  The generic extractor owns the logic;
this package only records presentation differences learned from review matrices.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(__file__).parent
PROFILE_SCHEMA_VERSION = 1


def load_profile(ticker: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        return {"schema_version": PROFILE_SCHEMA_VERSION, "ticker": ticker.upper()}
    profile = json.loads(path.read_text(encoding="utf-8"))
    try:
        from operational_sources import operational_sources_for_sector
        source = operational_sources_for_sector("construcao_civil").get(ticker.upper(), {})
    except Exception:
        source = {}
    profile.setdefault("ri_urls", source.get("results_pages", []))
    profile.setdefault("results_pages", source.get("results_pages", []))
    profile.setdefault("allowed_domains", source.get("allowed_domains", []))
    profile.setdefault("document_types", ["RELEASE_RESULTADOS", "PREVIA_OPERACIONAL", "APRESENTACAO_RESULTADOS"])
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


def resolve_company_for_document(path: Any, content: str = "", sector: str = "construcao_civil", profiles: dict[str, dict[str, Any]] | None = None, source_url: str | None = None) -> dict[str, Any] | None:
    """Resolve a document using auditable company evidence, never generic KPI words."""
    if sector != "construcao_civil":
        return None
    from company_registry import operational_companies
    haystack = f"{path} {content}".upper()
    normalized_cnpj = re.sub(r"\D", "", str(content))
    source_domain = source_url.split("/", 3)[2].lower() if source_url and "/" in source_url else ""
    candidates = []
    for company in operational_companies(sector):
        profile = (profiles or {}).get(company.ticker) or load_profile(company.ticker)
        aliases = (company.ticker, *company.legacy_tickers, company.expected_name, *company.aliases, *profile.get("content_aliases", []))
        hits = [alias for alias in aliases if alias and alias.upper() in haystack]
        cnpj_match = re.sub(r"\D", "", company.cnpj) in normalized_cnpj
        domain_match = source_domain in {str(domain).lower() for domain in profile.get("allowed_domains", [])} if source_domain else False
        if cnpj_match:
            hits.append(f"CNPJ:{company.cnpj}")
        elif domain_match:
            hits.append(f"DOMAIN:{source_domain}")
        if hits:
            if company.ticker in str(path).upper():
                method = "filename_ticker"
            elif cnpj_match:
                method = "content_cnpj"
            elif domain_match:
                method = "official_domain"
            else:
                method = "content_alias"
            candidates.append((len(max(hits, key=len)), company, method, max(hits, key=len)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, company, method, alias = candidates[0]
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return {"ticker": company.ticker, "method": method, "matched_alias": alias, "confidence": "high"}

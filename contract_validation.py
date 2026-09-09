"""Contratos pequenos e compartilhados para compatibilidade de payloads."""

from __future__ import annotations

from collections.abc import Mapping


def compatibility_event(kind: str, **details: object) -> dict[str, object]:
    """Cria um diagnóstico serializável e sem dados sensíveis."""
    return {"type": kind, **details}


def append_compatibility_event(payload: Mapping[str, object], event: Mapping[str, object]) -> dict[str, object]:
    """Retorna cópia do payload com evento de compatibilidade acumulado."""
    result = dict(payload)
    events = list(result.get("compatibility_diagnostics") or [])
    events.append(dict(event))
    result["compatibility_diagnostics"] = events
    return result


def payload_companies(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Lê o envelope atual e o envelope histórico de empresas."""
    companies = payload.get("companies")
    if isinstance(companies, Mapping):
        return companies
    legacy = payload.get("empresas")
    return legacy if isinstance(legacy, Mapping) else {}

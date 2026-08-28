#!/usr/bin/env python3
"""Camada de overrides manuais para dados operacionais."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from company_registry import canonical_ticker, company_by_ticker, operational_companies
from operational_dictionary import all_metric_names
from construction_operational import CONSTRUCTION_OPERATIONAL_DICTIONARY


TICKERS: tuple[str, ...] = tuple(company.ticker for company in operational_companies("all"))
MANUAL_OVERRIDES_FILENAME = "manual_operational_overrides.json"
MANUAL_REMOTE_RELATIVE_PATH = MANUAL_OVERRIDES_FILENAME
MANUAL_CONFIDENCE = "MANUAL"
AUTO_ACCEPTED_CONFIDENCES = {"high", "medium"}

METRIC_UNITS = {
    "Ticket Medio": "R$",
    "Ticket Médio": "R$",
    "N. Atendimentos": "contagem",
    "N. Unidades": "contagem",
    "N. Pacientes": "contagem",
    "Receita Bruta": "R$",
    "Glosa/PCLD": "R$",
    **{definition["display_name"]: definition["unit"] for definition in CONSTRUCTION_OPERATIONAL_DICTIONARY.values()},
}

CONSTRUCTION_METRIC_BY_ID = {key: value["display_name"] for key, value in CONSTRUCTION_OPERATIONAL_DICTIONARY.items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_manual_payload() -> dict[str, Any]:
    return {
        "schema_version": "manual_operational_overrides_v1",
        "updated_at": None,
        "overrides": [],
    }


def normalize_metric(metric: str) -> str:
    text = " ".join(str(metric or "").strip().split())
    aliases = {
        "Ticket Medio": "Ticket Médio",
        "ticket medio": "Ticket Médio",
        "ticket médio": "Ticket Médio",
        "n atendimentos": "N. Atendimentos",
        "n. atendimentos": "N. Atendimentos",
        "n unidades": "N. Unidades",
        "n. unidades": "N. Unidades",
        "n pacientes": "N. Pacientes",
        "n. pacientes": "N. Pacientes",
        "receita bruta": "Receita Bruta",
        "glosa/pcld": "Glosa/PCLD",
        "glosa pcld": "Glosa/PCLD",
    }
    return aliases.get(text.lower(), CONSTRUCTION_METRIC_BY_ID.get(text, text))


def normalize_period(period: str) -> str:
    text = str(period or "").strip().upper().replace(" ", "")
    quarterly = re.fullmatch(r"([1-4])[TQ](\d{2}|\d{4})", text)
    if quarterly:
        year = quarterly.group(2)
        return f"{quarterly.group(1)}T{year[-2:]}"
    fy = re.fullmatch(r"FY(20\d{2}|\d{2})", text)
    if fy:
        year = fy.group(1)
        return f"FY{year[-4:] if len(year) == 4 else '20' + year}"
    annual = re.fullmatch(r"20\d{2}", text)
    if annual:
        return text
    raise ValueError(f"Periodo operacional invalido: {period}")


def parse_numeric_value(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Valor manual deve ser numerico.")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Valor manual deve ser numerico.")
        if not re.fullmatch(r"-?[\d.,]+", text):
            raise ValueError("Valor manual deve ser numerico.")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        number = float(text)
    if not (number == number and abs(number) != float("inf")):
        raise ValueError("Valor manual deve ser numerico finito.")
    return number


def validate_manual_record(record: dict[str, Any], *, existing_id: str | None = None) -> dict[str, Any]:
    raw_ticker = str(record.get("ticker") or "").strip().upper()
    try:
        ticker = canonical_ticker(raw_ticker)
        company = company_by_ticker(ticker)
    except ValueError as exc:
        raise ValueError(f"Ticker operacional invalido: {raw_ticker}") from exc
    sector = str(record.get("sector") or company.sector).strip().lower()
    if sector != company.sector or ticker not in TICKERS:
        raise ValueError(f"Ticker operacional invalido para {sector}: {ticker}")
    metric = normalize_metric(str(record.get("metric") or ""))
    if metric not in all_metric_names(sector):
        raise ValueError(f"Metrica operacional invalida: {metric}")
    period = normalize_period(str(record.get("period") or ""))
    value = parse_numeric_value(record.get("value"))
    now = utc_now()
    return {
        "id": existing_id or str(record.get("id") or uuid.uuid4()),
        "ticker": ticker,
        "sector": sector,
        "metric": metric,
        "period": period,
        "value": value,
        "unit": METRIC_UNITS.get(metric, ""),
        "ownership_basis": str(record.get("ownership_basis") or "unknown"),
        "segment": str(record.get("segment") or "consolidated"),
        "comment": str(record.get("comment") or record.get("source_comment") or ""),
        "created_at": str(record.get("created_at") or now),
        "updated_at": now,
        "status": "active",
        "source": "manual",
        "nature": "manual",
        "source_type": "manual",
        "confidence": MANUAL_CONFIDENCE,
    }


def manual_key(record: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(record.get("sector") or "saude"),
        str(record.get("ticker") or "").upper(),
        normalize_metric(str(record.get("metric") or "")),
        normalize_period(str(record.get("period") or "")),
        str(record.get("ownership_basis") or "unknown"),
        str(record.get("segment") or "consolidated"),
    )


def load_manual_overrides_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_manual_payload()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else empty_manual_payload()


def write_manual_overrides_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_manual_payload(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_manual_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = empty_manual_payload()
    if isinstance(payload, dict):
        normalized.update({key: value for key, value in payload.items() if key != "overrides"})
        normalized["overrides"] = payload.get("overrides") if isinstance(payload.get("overrides"), list) else []
    active_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for raw in normalized["overrides"]:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "active")
        try:
            record = validate_manual_record(raw, existing_id=str(raw.get("id") or ""))
        except ValueError:
            continue
        record.update({key: raw[key] for key in ("superseded_at", "superseded_by", "automatic_confidence", "automatic_value") if key in raw})
        record["status"] = status
        if status == "active":
            active_by_key[manual_key(record)] = record
        else:
            history.append(record)
    normalized["overrides"] = history + list(active_by_key.values())
    normalized.setdefault("schema_version", "manual_operational_overrides_v1")
    return normalized


def upsert_manual_override(payload: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_manual_payload(payload)
    new_record = validate_manual_record(record)
    key = manual_key(new_record)
    replaced = False
    for current in payload["overrides"]:
        if current.get("status") == "active" and manual_key(current) == key:
            current.update(new_record)
            current["created_at"] = current.get("created_at") or new_record["created_at"]
            replaced = True
            break
    if not replaced:
        payload["overrides"].append(new_record)
    payload["updated_at"] = utc_now()
    return normalize_manual_payload(payload)


def delete_manual_override(payload: dict[str, Any], record_id: str) -> dict[str, Any]:
    payload = normalize_manual_payload(payload)
    now = utc_now()
    for current in payload["overrides"]:
        if str(current.get("id")) == str(record_id) and current.get("status") == "active":
            current["status"] = "deleted"
            current["updated_at"] = now
            payload["updated_at"] = now
            return payload
    raise KeyError(record_id)


def accepted_auto_value(company: dict[str, Any], metric: str, period: str) -> tuple[bool, Any, str | None]:
    for item in (company.get("metricas") or {}).get(metric, []) or []:
        confidence = str(item.get("confidence") or "").lower()
        if confidence not in AUTO_ACCEPTED_CONFIDENCES:
            continue
        serie = item.get("serie") if isinstance(item.get("serie"), dict) else {}
        if period in serie and serie[period] not in (None, ""):
            return True, serie[period], confidence
    return False, None, None


def resolve_operational_data_with_manual(
    operational_data: dict[str, Any],
    manual_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = deepcopy(operational_data or {"companies": {}})
    data.setdefault("companies", {})
    manual = normalize_manual_payload(manual_payload)
    now = utc_now()
    warnings_by_ticker: dict[str, list[dict[str, Any]]] = {}

    for override in manual["overrides"]:
        if override.get("status") != "active":
            continue
        _sector, ticker, metric, period, _ownership_basis, _segment = manual_key(override)
        company = data["companies"].setdefault(ticker, {"ticker": ticker, "metricas": {}, "warnings": []})
        company.setdefault("metricas", {})
        company.setdefault("warnings", [])
        has_auto, automatic_value, automatic_confidence = accepted_auto_value(company, metric, period)
        if has_auto:
            override["status"] = "superseded"
            override["superseded_at"] = now
            override["superseded_by"] = "automatic"
            override["automatic_confidence"] = automatic_confidence
            override["automatic_value"] = automatic_value
            override["updated_at"] = now
            continue
        item = {
            "manual_id": override.get("id"),
            "metric": metric,
            "nature": "manual",
            "source_type": "manual",
            "confidence": MANUAL_CONFIDENCE,
            "manual": True,
            "requires_review": False,
            "escopo": "Valor informado manualmente",
            "fonte_linha": "Entrada manual",
            "unidade": override.get("unit") or METRIC_UNITS.get(metric, ""),
            "serie": {period: override.get("value")},
            "observations": [
                {
                    "ticker": ticker,
                    "metric": metric,
                    "period": period,
                    "value": override.get("value"),
                    "unit": override.get("unit") or METRIC_UNITS.get(metric, ""),
                    "nature": "manual",
                    "source_type": "manual",
                    "confidence": MANUAL_CONFIDENCE,
                    "manual": True,
                    "created_at": override.get("created_at"),
                    "updated_at": override.get("updated_at"),
                    "status": "MANUAL_ACTIVE",
                }
            ],
        }
        company["metricas"].setdefault(metric, []).append(item)
        warnings_by_ticker.setdefault(ticker, []).append(
            {
                "metric": metric,
                "period": period,
                "status": "manual_active",
                "message": "Valor inserido manualmente.",
            }
        )

    for ticker, warnings in warnings_by_ticker.items():
        data["companies"][ticker].setdefault("warnings", [])
        data["companies"][ticker]["warnings"].extend(warnings)

    manual["updated_at"] = now if any(item.get("status") == "superseded" for item in manual["overrides"]) else manual.get("updated_at")
    return data, manual


def github_api_json(url: str, token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Nerias-RI-Tracker/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def load_remote_manual_overrides(repo: str, branch: str, token: str) -> tuple[dict[str, Any], str | None]:
    encoded_path = quote(f"data/{MANUAL_OVERRIDES_FILENAME}")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={quote(branch)}"
    try:
        response = github_api_json(url, token)
    except HTTPError as exc:
        if exc.code == 404:
            return empty_manual_payload(), None
        raise
    content = base64.b64decode(str(response.get("content") or "")).decode("utf-8")
    return normalize_manual_payload(json.loads(content)), response.get("sha")


def save_remote_manual_overrides(repo: str, branch: str, token: str, payload: dict[str, Any], message: str) -> dict[str, Any]:
    current, sha = load_remote_manual_overrides(repo, branch, token)
    merged = normalize_manual_payload(current)
    for record in normalize_manual_payload(payload)["overrides"]:
        if record.get("status") == "active":
            merged = upsert_manual_override(merged, record)
        else:
            replaced = False
            for idx, existing in enumerate(merged["overrides"]):
                if str(existing.get("id")) == str(record.get("id")):
                    merged["overrides"][idx] = record
                    replaced = True
                    break
            if not replaced:
                merged["overrides"].append(record)
    body = json.dumps(normalize_manual_payload(merged), ensure_ascii=False, indent=2) + "\n"
    request_payload = {
        "message": message,
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        request_payload["sha"] = sha
    encoded_path = quote(f"data/{MANUAL_OVERRIDES_FILENAME}")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
    return github_api_json(url, token, method="PUT", payload=request_payload)


def manual_admin_token_configured() -> bool:
    return bool(os.getenv("NERIAS_MANUAL_ADMIN_TOKEN"))

"""Normalizacao auditavel de preco e capital social para market cap historico."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable


MAX_SHARES_STALENESS_DAYS = 180
STRUCTURAL_FACTORS = (2, 3, 4, 5, 10, 15, 20, 25, 50, 100)


def as_positive_int(value: Any) -> int | None:
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def as_positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _relative_distance(left: float, right: float) -> float:
    return abs(left - right) / max(abs(right), 1e-12)


def approximate_structural_factor(ratio: float | None, tolerance: float = 0.08) -> float | None:
    """Returns a recognised split/reverse-split ratio, otherwise None."""
    if not ratio or ratio <= 0:
        return None
    candidates = tuple(float(value) for value in STRUCTURAL_FACTORS) + tuple(1 / value for value in STRUCTURAL_FACTORS)
    candidate = min(candidates, key=lambda value: _relative_distance(ratio, value))
    return candidate if _relative_distance(ratio, candidate) <= tolerance else None


def resolve_yahoo_split_factor(raw_factor: float | None, shares_ratio: float | None) -> float | None:
    """Expresses a Yahoo split event as the multiplier for prices before it.

    Yahoo vendors may encode reverse splits as either the inverse ratio or the
    direct ratio.  The CVM share ratio is authoritative; select the equivalent
    representation that matches it and reject unrelated events.
    """
    raw = as_positive_float(raw_factor)
    ratio = as_positive_float(shares_ratio)
    if raw is None or ratio is None:
        return None
    candidates = (raw, 1.0 / raw)
    selected = min(candidates, key=lambda value: _relative_distance(value, ratio))
    return selected if _relative_distance(selected, ratio) <= 0.12 else None


def normalize_daily_prices(
    daily_prices: Iterable[dict[str, Any]],
    split_events: Iterable[dict[str, Any]],
    cvm_share_points: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aligns Yahoo daily prices to the CVM historical share basis.

    The returned prices keep original and adjusted values.  A split is applied
    only when its factor is corroborated by two consecutive CVM observations.
    """
    shares = sorted(
        [item for item in cvm_share_points if as_positive_int(item.get("shares")) and item.get("date")],
        key=lambda item: str(item["date"]),
    )
    events: list[dict[str, Any]] = []
    reconciled_share_change_dates: set[str] = set()
    for event in sorted(split_events, key=lambda item: str(item.get("date") or "")):
        event_date = str(event.get("date") or "")
        before = [item for item in shares if str(item["date"]) < event_date]
        after = [item for item in shares if str(item["date"]) >= event_date]
        if not event_date or not before or not after:
            events.append({"date": event_date, "raw_factor": event.get("factor"), "status": "unresolved", "reason": "acoes_cvm_insuficientes"})
            continue
        shares_ratio = as_positive_int(after[0]["shares"]) / as_positive_int(before[-1]["shares"])
        factor = resolve_yahoo_split_factor(event.get("factor"), shares_ratio)
        if factor is None:
            events.append({"date": event_date, "raw_factor": event.get("factor"), "shares_ratio": shares_ratio, "status": "unresolved", "reason": "evento_yahoo_incompativel_com_cvm"})
            continue
        events.append({"date": event_date, "raw_factor": event.get("factor"), "shares_ratio": shares_ratio, "price_factor": factor, "status": "validated", "evidence": "Yahoo Stock Splits + CVM QT_ACAO_TOTAL_CAP_INTEGR"})
        reconciled_share_change_dates.add(str(after[0]["date"]))

    # A material CVM change without a corroborating Yahoo corporate-action event
    # is unsafe as well: publishing pre-event market cap would mix price bases.
    for previous, current in zip(shares, shares[1:]):
        shares_ratio = as_positive_int(current["shares"]) / as_positive_int(previous["shares"])
        structural_factor = approximate_structural_factor(shares_ratio)
        current_date = str(current["date"])
        if structural_factor is not None and current_date not in reconciled_share_change_dates:
            events.append({"date": current_date, "shares_ratio": shares_ratio, "structural_factor": structural_factor, "status": "unresolved", "reason": "alteracao_estrutural_cvm_sem_evento_yahoo_correspondente"})
    events.sort(key=lambda item: str(item.get("date") or ""))

    normalized = []
    for item in daily_prices:
        price = as_positive_float(item.get("price"))
        price_date = str(item.get("date") or "")
        if price is None or not price_date:
            continue
        adjustment = 1.0
        applied = []
        for event in events:
            if event["status"] == "validated" and price_date < event["date"]:
                adjustment *= float(event["price_factor"])
                applied.append(event["date"])
        normalized.append({
            "date": price_date,
            "price_raw": price,
            "price": price * adjustment,
            "price_adjustment_factor": adjustment,
            "applied_events": applied,
            "source": "Yahoo Finance",
        })
    return normalized, events


def resolve_official_shares(
    reference_date: date,
    cvm_points: Iterable[tuple[date, int | None]],
) -> dict[str, Any]:
    """Uses the latest official share count, with a bounded explicit fallback."""
    valid = sorted((point_date, as_positive_int(shares)) for point_date, shares in cvm_points if as_positive_int(shares))
    candidates = [(point_date, shares) for point_date, shares in valid if point_date <= reference_date]
    if not candidates:
        return {"shares": None, "status": "excluded", "reason": "acoes_cvm_ausentes"}
    point_date, shares = candidates[-1]
    age_days = (reference_date - point_date).days
    if age_days == 0:
        return {"shares": shares, "shares_date": point_date.isoformat(), "status": "validated", "source": "CVM", "age_days": 0}
    if age_days <= MAX_SHARES_STALENESS_DAYS:
        return {"shares": shares, "shares_date": point_date.isoformat(), "status": "estimated_from_last_valid_shares", "source": "CVM", "age_days": age_days, "reason": "ultima_quantidade_oficial_valida"}
    return {"shares": None, "shares_date": point_date.isoformat(), "status": "excluded", "source": "CVM", "age_days": age_days, "reason": "acoes_cvm_defasadas_acima_de_180_dias"}

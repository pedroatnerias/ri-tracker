"""Pure financial and comparison helpers used by the dashboard."""

from __future__ import annotations

import math


def nested_get(data: dict, path: str) -> float | None:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current if isinstance(current, (int, float)) and not isinstance(current, bool) and not (isinstance(current, float) and math.isnan(current)) else None


def period_label(record: dict) -> str:
    meta = record.get("metadata") or {}
    year, quarter, is_ytd = meta.get("year"), meta.get("quarter"), meta.get("is_ytd")
    if year and quarter:
        return str(year) if is_ytd and quarter == 4 else f"{quarter}T{str(year)[-2:]}"
    return str(record.get("periodo") or "")


def filter_records_for_view(records: list[dict], view: str) -> list[dict]:
    def key(record: dict) -> tuple[int, int, int]:
        meta = record.get("metadata") or {}
        return (int(meta.get("year") or 0), int(meta.get("quarter") or 0), 1 if meta.get("is_ytd") else 0)

    selected = []
    for record in records:
        meta = record.get("metadata") or {}
        quarter, is_ytd = int(meta.get("quarter") or 0), bool(meta.get("is_ytd"))
        if (view == "annual" and is_ytd and quarter == 4) or (view != "annual" and ((not is_ytd) or quarter == 1)):
            selected.append(record)
    return sorted(selected, key=key)


def as_number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and not (isinstance(value, float) and math.isnan(value)) else None


def record_sort_tuple(record: dict) -> tuple[int, int, int]:
    meta = record.get("metadata") or {}
    return (int(meta.get("year") or 0), int(meta.get("quarter") or 0), 1 if meta.get("is_ytd") else 0)


def period_sort_key(period: str) -> tuple[int, int]:
    text = str(period or "")
    if len(text) == 4 and text.isdigit():
        return int(text), 5
    if len(text) >= 4 and text[1].upper() == "T" and text[0].isdigit():
        yy = text[2:]
        return (int(yy) + 2000 if len(yy) == 2 and yy.isdigit() else 0), int(text[0])
    return 0, 0


def quarter_label_from_record(record: dict) -> str:
    meta = record.get("metadata") or {}
    if meta.get("year") and meta.get("quarter"):
        return f"{int(meta['quarter'])}T{str(meta['year'])[-2:]}"
    return period_label(record)


def annual_records(records: list[dict]) -> list[dict]:
    return filter_records_for_view(records, "annual")


def cagr_value(first: object, last: object, years: int) -> float | None:
    first_num, last_num = as_number(first), as_number(last)
    if first_num is None or last_num is None or first_num <= 0 or last_num <= 0 or years <= 0:
        return None
    return (pow(last_num / first_num, 1 / years) - 1) * 100


def quality_for_metric(record: dict | None, metric: str) -> dict | None:
    if not record:
        return None
    for flag in record.get("quality_flags") or []:
        if flag.get("metric") == metric:
            return flag
    quality = record.get(f"quality_{metric}")
    return quality if isinstance(quality, dict) else None


def comparison_cell(value, period=None, *, quality=None, confidence=None, source=None, extra=None) -> dict:
    return {"value": value, "period": period, "quality": quality, "confidence": confidence, "source": source, **(extra or {})}


def latest_annual_cycle(records: list[dict]) -> dict | None:
    annual = [r for r in records or [] if str((r.get("periodo") or {}).get("inicio") or "").endswith("-01-01") and str((r.get("periodo") or {}).get("fim") or "").endswith("-12-31")]
    return sorted(annual, key=lambda r: str((r.get("periodo") or {}).get("fim") or ""))[-1] if annual else None


def latest_operational_metric(company: dict, metric: str) -> dict | None:
    candidates = []
    for item in (company.get("metricas") or {}).get(metric, []) or []:
        if item.get("confidence") == "low":
            continue
        for period, value in (item.get("serie") or {}).items():
            number = as_number(value)
            if number is not None:
                candidates.append({"period": period, "value": number, "confidence": item.get("confidence"), "source": item.get("fonte_linha") or item.get("escopo")})
    return sorted(candidates, key=lambda item: period_sort_key(str(item["period"]))) [-1] if candidates else None

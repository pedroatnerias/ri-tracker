"""Pure dashboard-domain transformations."""

from __future__ import annotations

import re

from dashboard_presentation import COMPARISON_METRICS, build_chart_assets_payload

# Historical imports from dashboard_services are intentionally supported while
# presentation contracts migrate to dashboard_presentation.
__all__ = [
    "COMPARISON_METRICS",
    "build_chart_assets_payload",
    "normalize_operational_metric_item",
    "operational_annual_series",
]

def normalize_operational_metric_item(item: dict, sector: str) -> dict:
    normalized = dict(item or {})
    series = normalized.get("series") if isinstance(normalized.get("series"), dict) else normalized.get("serie")
    series = dict(series) if isinstance(series, dict) else {}
    observations = [observation for observation in normalized.get("observations", []) if isinstance(observation, dict)]
    rejected_observations = []
    if sector == "construcao_civil" and observations:
        from construction_operational import parse_brazilian_financial_value

        valid_periods = set()
        for observation in observations:
            row_label = str(observation.get("row_label") or "").lower()
            evidence = str(observation.get("evidence_text") or "")
            value = observation.get("value")
            breakdown_as_total = ("por regi" in row_label or any(term in row_label for term in ("por regiao", "por produto", "by region", "by product"))) and "total" not in row_label
            scale_mismatch = False
            if isinstance(value, (int, float)) and value != 0:
                bold_values = re.findall(r"\*\*(\d[\d.,]*)\*\*", evidence)
                parsed_evidence = []
                for raw in bold_values[:4]:
                    try:
                        parsed_evidence.append(parse_brazilian_financial_value(raw, str(observation.get("raw_unit") or observation.get("unit") or "R$ MM"))["normalized_value"])
                    except ValueError:
                        pass
                evidence_ratios = [abs(candidate / value) for candidate in parsed_evidence if candidate]
                scale_mismatch = bool(evidence_ratios and min(evidence_ratios) > 100)
            if breakdown_as_total or scale_mismatch:
                rejected_observations.append({**observation, "dashboard_rejection_reason": "breakdown_as_total" if breakdown_as_total else "scale_incompatible_with_evidence"})
            else:
                valid_periods.add(str(observation.get("period") or ""))
        if rejected_observations:
            series = {period: value for period, value in series.items() if period in valid_periods}
    indicator_id = str(normalized.get("indicator_id") or "")
    series, derived_periods = operational_annual_series(series, indicator_id, sector)
    first_observation = observations[0] if observations else {}
    source = next((str(normalized.get(key)) for key in ("source", "escopo", "fonte_linha", "source_document") if normalized.get(key)), str(first_observation.get("source_document") or first_observation.get("source_url") or ""))
    unit = normalized.get("unit") or normalized.get("unidade") or first_observation.get("unit") or ""
    normalized.update({
        "series": series, "serie": series,
        "unit": unit, "unidade": unit,
        "calculated": bool(normalized.get("calculated", normalized.get("calculado", False)) or derived_periods),
        "calculado": bool(normalized.get("calculated", normalized.get("calculado", False)) or derived_periods),
        "source": source, "derived_periods": sorted(derived_periods),
        "rejected_observations": rejected_observations,
    })
    return normalized



def operational_annual_series(series: dict, indicator_id: str, sector: str) -> tuple[dict, set[str]]:
    result = dict(series)
    derived: set[str] = set()
    if sector != "construcao_civil":
        return result, derived
    from construction_operational import CONSTRUCTION_OPERATIONAL_DICTIONARY
    definition = CONSTRUCTION_OPERATIONAL_DICTIONARY.get(indicator_id, {})
    nature = definition.get("nature")
    classification = definition.get("classification")
    years = sorted({f"20{match.group(2)[-2:]}" for period in series if (match := re.fullmatch(r"([1-4])T(\d{2}|\d{4})", str(period), re.I))})
    for year in years:
        if year in result:
            continue
        quarters = [series.get(f"{quarter}T{year[-2:]}", series.get(f"{quarter}T{year}")) for quarter in range(1, 5)]
        if nature == "stock" and quarters[3] not in (None, ""):
            result[year] = quarters[3]
            derived.add(year)
        elif nature == "flow" and classification != "calculated" and all(isinstance(value, (int, float)) for value in quarters):
            result[year] = sum(quarters)
            derived.add(year)
    return result, derived

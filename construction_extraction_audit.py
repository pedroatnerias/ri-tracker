"""Coverage and conservative history merge for construction observations."""
from construction_operational import CONSTRUCTION_OPERATIONAL_DICTIONARY, validate_observation_evidence


def observation_key(row):
    return tuple(row.get(key) for key in ("ticker", "indicator_id", "period", "ownership_basis", "segment"))


def merge_observations(previous, candidates):
    historical = {observation_key(row): row for row in previous}
    grouped = {}
    rejected = []
    for candidate in candidates:
        row = validate_observation_evidence(candidate)
        if row["validation_status"] != "valid":
            rejected.append(row)
        else:
            grouped.setdefault(observation_key(row), []).append(row)
    accepted = []
    for key, rows in grouped.items():
        values = {(row["value"], row["unit"], row.get("period_type")) for row in rows}
        if len(values) > 1:
            rejected.extend({**row, "validation_status": "ambiguous", "rejection_reason": "conflicting_values"} for row in rows)
            continue
        row = rows[0]
        accepted.append(row)
        historical[key] = row
    accepted_keys = {observation_key(row) for row in accepted}
    return list(historical.values()), accepted, rejected, sum(observation_key(row) not in accepted_keys for row in previous)


def coverage_matrix(ticker, period, accepted, rejected, documents, failures=(), preserved=()):
    from construction_company_profiles import profile_for
    profile = profile_for(ticker)
    result = []
    for metric, definition in CONSTRUCTION_OPERATIONAL_DICTIONARY.items():
        if definition["classification"] != "extracted":
            continue
        found = [row for row in accepted if row["indicator_id"] == metric and row["period"] == period]
        retained = [row for row in preserved if row.get("indicator_id") == metric and row.get("period") == period]
        refused = [row for row in rejected if row.get("indicator_id") == metric and row.get("period") == period]
        status = "extracted" if found else "preserved" if retained else "extraction_failed" if documents else "document_missing"
        if not found and refused:
            status = "ambiguous" if any(row.get("validation_status") == "ambiguous" for row in refused) else "extraction_failed"
        if not found and not documents and failures:
            status = "conversion_failed"
        rules = profile.get("metrics", {}).get(metric, {})
        confirmed = rules.get("publication_evidence", {}).get(period)
        if not found and not refused and rules.get("publication") == "not_disclosed" and period in rules.get("publication_periods", []) and confirmed:
            status = "not_disclosed_confirmed"
        result.append({"ticker": ticker, "indicator_id": metric, "period": period, "status": status,
                       "evidence": found or retained, "new_evidence": found, "preserved_evidence": retained,
                       "rejected": refused, "non_disclosure_evidence": confirmed})
    return result

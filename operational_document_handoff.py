"""Read conversion provenance without depending on Flask or network access."""
from pathlib import Path
from data_access import read_json
from construction_company_profiles import resolve_company_for_document


def resolve_markdown(path, text):
    metadata_path = path.with_name(path.stem + "_metadata.json")
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    resolution = resolve_company_for_document(str(path), text, source_url=metadata.get("url_origem"))
    if metadata.get("ticker") and resolution and metadata["ticker"] != resolution["ticker"]:
        return None, metadata, "identity_conflict"
    # Explicit ticker evidence in the handoff path must not contradict resolution.
    from company_registry import operational_companies
    import re
    hints = {company.ticker for company in operational_companies("construcao_civil")
             if re.search(rf"(?<![A-Z0-9]){re.escape(company.ticker)}(?![A-Z0-9])", str(path).upper())}
    if len(hints) > 1 or resolution and hints and resolution["ticker"] not in hints:
        return None, metadata, "identity_conflict"
    # A heading naming a different issuer is contradictory, unlike a subsidiary
    # mentioned later in the consolidated statements.
    primary = resolve_company_for_document("", text[:4000])
    if resolution and primary and primary["ticker"] != resolution["ticker"]:
        from company_registry import company_by_ticker
        expected = company_by_ticker(resolution["ticker"])
        header = text[:4000].upper()
        if not any(alias.upper() in header for alias in (expected.ticker, expected.expected_name, *expected.aliases)):
            return None, metadata, "identity_conflict"
    return resolution, metadata, None if resolution else "company_unresolved"

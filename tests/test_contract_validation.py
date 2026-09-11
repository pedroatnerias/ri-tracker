from contract_validation import append_compatibility_event, compatibility_event, payload_companies


def test_compatibility_event_is_serializable_and_does_not_mutate_payload():
    payload = {"companies": {"CYRE3": {}}, "compatibility_diagnostics": []}
    result = append_compatibility_event(payload, compatibility_event("legacy", from_ticker="INNT3"))

    assert result["compatibility_diagnostics"] == [{"type": "legacy", "from_ticker": "INNT3"}]
    assert payload["compatibility_diagnostics"] == []


def test_payload_companies_accepts_current_and_historical_envelopes():
    assert payload_companies({"companies": {"CYRE3": {}}}) == {"CYRE3": {}}
    assert payload_companies({"empresas": {"CYRE3": {}}}) == {"CYRE3": {}}
    assert payload_companies({"companies": []}) == {}

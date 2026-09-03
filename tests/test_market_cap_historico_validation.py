from app_market_cap_historico import validar_quantidade_acoes


def test_yahoo_is_primary_when_sources_are_within_tolerance():
    result = validar_quantidade_acoes(100_000, 104_000)
    assert result["quantidade"] == 100_000
    assert result["fonte"] == "Yahoo Finance"
    assert result["status"] == "validated"


def test_material_discrepancy_blocks_market_cap():
    result = validar_quantidade_acoes(195_434_352, 1_954_343_520)
    assert result["quantidade"] is None
    assert result["fonte"] is None
    assert result["status"] == "shares_discrepancy"
    assert result["diferenca_pct"] > 900


def test_cvm_is_fallback_when_yahoo_is_missing():
    result = validar_quantidade_acoes(None, 123_456)
    assert result["quantidade"] == 123_456
    assert result["fonte"] == "CVM"
    assert result["status"] == "cvm_fallback"


def test_same_rule_is_independent_of_sector():
    assert validar_quantidade_acoes(100, 100)["fonte"] == "Yahoo Finance"
    assert validar_quantidade_acoes(100, 110)["status"] == "shares_discrepancy"

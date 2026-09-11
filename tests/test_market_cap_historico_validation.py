from datetime import date

import pandas as pd
from unittest.mock import patch

from app_market_cap_historico import calcular_market_cap_classes, preco_ajustado_na_data, preco_market_cap_na_data, validar_quantidade_acoes
from app_market_cap import _market_cap_classes_atual, _quantidades_classes_historico, processar_ticker
from app_indicadores import _market_cap_historico_map
from company_registry import company_by_ticker


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
    assert result["diferenca_pct"] == 90.0


def test_toky_reverse_split_preserves_market_cap_across_event():
    history = pd.DataFrame(
        {"Close": [6.60, 8.25], "Stock Splits": [0.0, 0.05]},
        index=pd.to_datetime(["2026-08-26", "2026-08-28"], utc=True),
    )
    before_price, _ = preco_market_cap_na_data(history, date(2026, 8, 26))
    after_price, _ = preco_market_cap_na_data(history, date(2026, 8, 28))
    before_2026_08_26 = calcular_market_cap_classes([
        {"ticker": "TOKY3", "preco_acao": before_price, "quantidade_acoes": 54_196_740},
    ])
    after_2026_08_28 = calcular_market_cap_classes([
        {"ticker": "TOKY3", "preco_acao": after_price, "quantidade_acoes": 2_709_837},
    ])
    assert before_price == 0.33
    assert after_price == 8.25
    assert abs(before_2026_08_26 / after_2026_08_28 - 0.8) < 1e-12
    adjusted_before, _ = preco_ajustado_na_data(history, date(2026, 8, 26))
    adjusted_after, _ = preco_ajustado_na_data(history, date(2026, 8, 28))
    assert adjusted_after / adjusted_before == 1.25


def test_historical_price_does_not_use_stale_trading_day():
    history = pd.DataFrame({"Close": [10.0]}, index=pd.to_datetime(["2026-06-01"], utc=True))
    assert preco_market_cap_na_data(history, date(2026, 6, 30)) == (None, None)
    assert preco_ajustado_na_data(history, date(2026, 6, 30)) == (None, None)


def test_multiple_share_classes_are_summed_and_fail_closed():
    assert calcular_market_cap_classes([
        {"ticker": "CGRA3", "preco_acao": 20.0, "quantidade_acoes": 10},
        {"ticker": "CGRA4", "preco_acao": 25.0, "quantidade_acoes": 20},
    ]) == 700.0
    assert calcular_market_cap_classes([
        {"ticker": "WHRL3", "preco_acao": 5.0, "quantidade_acoes": 10},
        {"ticker": "WHRL4", "preco_acao": None, "quantidade_acoes": 20},
    ]) is None


def test_tfco_economic_weight_values_on_at_one_tenth_of_pn():
    assert calcular_market_cap_classes([
        {"ticker": "TFCO4", "preco_acao": 12.0, "quantidade_acoes": 877_251_375, "peso_economico": 0.1},
        {"ticker": "TFCO4", "preco_acao": 12.0, "quantidade_acoes": 65_492_864, "peso_economico": 1.0},
    ]) == 12.0 * (87_725_137.5 + 65_492_864)


def test_tfco_current_market_cap_keeps_two_cvm_classes_with_one_traded_ticker():
    company = company_by_ticker("TFCO4")
    payload = {"empresas": {"TFCO4": {"periodos": [{
        "data_referencia": "2026-06-30",
        "status_validacao_acoes": "validated_class_sum",
        "classes_acoes": [
            {"ticker": "TFCO4", "campo_quantidade_cvm": "QT_ACAO_ORDIN_CAP_INTEGR", "quantidade_acoes": 877_251_375},
            {"ticker": "TFCO4", "campo_quantidade_cvm": "QT_ACAO_PREF_CAP_INTEGR", "quantidade_acoes": 65_492_864},
        ],
    }]}}}
    quantities, reference_date = _quantidades_classes_historico(payload, company)
    with patch("app_market_cap.obter_preco", return_value=(12.0, "test")) as price:
        market_cap, components = _market_cap_classes_atual(company, quantities, reference_date)
    assert price.call_count == 1
    assert [item["classe"] for item in components] == ["ON", "PN"]
    assert market_cap == 12.0 * (87_725_137.5 + 65_492_864)


def test_indicators_do_not_recreate_market_cap_blocked_by_share_discrepancy():
    payload = {"empresas": {"TEST3": {"periodos": [{
        "data_referencia": "2026-06-30",
        "preco_acao": 10.0,
        "quantidade_acoes_total": 100,
        "market_cap": None,
        "status_validacao_acoes": "shares_discrepancy",
    }]}}}
    assert _market_cap_historico_map(payload, "TEST3") == {}


def test_current_multiclass_discrepancy_preserves_components_and_blocks_value():
    company = company_by_ticker("CGRA3")
    payload = {"empresas": {"CGRA3": {"periodos": [{
        "data_referencia": "2026-06-30", "status_validacao_acoes": "validated_class_sum",
        "classes_acoes": [
            {"campo_quantidade_cvm": "QT_ACAO_ORDIN_CAP_INTEGR", "quantidade_acoes": 10},
            {"campo_quantidade_cvm": "QT_ACAO_PREF_CAP_INTEGR", "quantidade_acoes": 20},
        ],
    }]}}}
    with patch("app_market_cap.yf.Ticker"), patch("app_market_cap.obter_preco", return_value=(20.0, "test")), patch("app_market_cap.obter_variacoes_preco", return_value={}), patch("app_market_cap.obter_acoes_em_circulacao", return_value=(100, pd.Timestamp("2026-06-30"), "test")):
        result = processar_ticker(company, payload)
    assert result["market_cap"] is None
    assert result["status_validacao_market_cap"] == "shares_discrepancy"
    assert result["diferenca_acoes_pct"] > 200
    assert len(result["classes_acoes"]) == 2


def test_cvm_is_fallback_when_yahoo_is_missing():
    result = validar_quantidade_acoes(None, 123_456)
    assert result["quantidade"] == 123_456
    assert result["fonte"] == "CVM"
    assert result["status"] == "cvm_fallback"


def test_same_rule_is_independent_of_sector():
    assert validar_quantidade_acoes(100, 100)["fonte"] == "Yahoo Finance"
    assert validar_quantidade_acoes(100, 110)["status"] == "shares_discrepancy"

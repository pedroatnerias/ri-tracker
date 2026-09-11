from datetime import date

from market_data_normalization import normalize_daily_prices, resolve_official_shares


def test_split_adjustment_uses_cvm_share_ratio():
    prices, events = normalize_daily_prices(
        [{"date": "2025-03-31", "price": 30}, {"date": "2025-06-30", "price": 32}],
        [{"date": "2025-05-01", "factor": 0.1}],
        [{"date": "2025-03-31", "shares": 1_000}, {"date": "2025-06-30", "shares": 100}],
    )
    assert events[0]["status"] == "validated"
    assert prices[0]["price"] == 3
    assert prices[1]["price"] == 32


def test_unreconciled_yahoo_event_is_not_adjusted():
    prices, events = normalize_daily_prices(
        [{"date": "2025-03-31", "price": 30}],
        [{"date": "2025-05-01", "factor": 0.1}],
        [{"date": "2025-03-31", "shares": 1_000}, {"date": "2025-06-30", "shares": 750}],
    )
    assert events[0]["status"] == "unresolved"
    assert prices[0]["price"] == 30


def test_last_official_shares_fallback_expires_after_180_days():
    points = [(date(2026, 1, 1), 100)]
    estimated = resolve_official_shares(date(2026, 6, 30), points)
    excluded = resolve_official_shares(date(2026, 7, 1), points)
    assert estimated["status"] == "estimated_from_last_valid_shares"
    assert estimated["shares"] == 100
    assert excluded["status"] == "excluded"


def test_structural_factors_are_recognised_and_reconciled():
    for factor in (2, 5, 10, 15, 20):
        prices, events = normalize_daily_prices(
            [{"date": "2025-03-31", "price": 10}, {"date": "2025-06-30", "price": 10}],
            [{"date": "2025-05-01", "factor": factor}],
            [{"date": "2025-03-31", "shares": 100}, {"date": "2025-06-30", "shares": 100 * factor}],
        )
        assert events[0]["status"] == "validated"
        assert prices[0]["price"] == 10 * factor
        assert prices[0]["price"] * 100 == prices[1]["price"] * (100 * factor)

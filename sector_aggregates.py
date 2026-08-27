"""Metricas agregadas setoriais para a aba Comparativo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable


SECTOR_EV_EBITDA_METHODOLOGY = "sector_aggregate_ev_ebitda_v1"
SECTOR_RETURN_METHODOLOGY = "sector_market_cap_weighted_price_return_v1"
MARKET_CAP_SHARE_METHODOLOGY = "sector_market_cap_share_v1"
MIN_RETURN_COVERAGE = 0.70


def as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if value == value else None
    try:
        return float(str(value).strip().replace(".", "").replace(",", ".") if "," in str(value) else str(value))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def period_label_from_date(value: str) -> str:
    parsed = parse_date(value)
    if not parsed:
        return str(value)
    quarter = (parsed.month - 1) // 3 + 1
    return f"{quarter}T{str(parsed.year)[-2:]}"


def valid_positive(value: Any) -> float | None:
    number = as_number(value)
    return number if number is not None and number > 0 else None


def market_cap_share(market_payload: dict[str, Any], tickers: Iterable[str]) -> dict[str, Any]:
    tickers = tuple(tickers)
    companies = (market_payload or {}).get("companies") or {}
    included = []
    excluded = []
    for ticker in tickers:
        row = companies.get(ticker) or {}
        value = valid_positive(row.get("market_cap"))
        if value is None:
            excluded.append({"ticker": ticker, "reason": "market_cap ausente, invalido, nulo ou negativo"})
            continue
        included.append(
            {
                "ticker": ticker,
                "market_cap": value,
                "date": row.get("data_preco") or row.get("data_acoes") or row.get("timestamp_extracao_brasilia"),
            }
        )
    total = sum(item["market_cap"] for item in included)
    if total <= 0:
        return {
            "methodology": MARKET_CAP_SHARE_METHODOLOGY,
            "available": False,
            "message": "Market cap setorial indisponivel: nenhuma empresa com valor valido.",
            "companies_registered": len(tickers),
            "companies_included": 0,
            "companies_excluded": excluded,
            "coverage_count": 0.0,
            "items": [],
            "total_market_cap": None,
        }
    items = sorted(
        [
            item | {"share_pct": item["market_cap"] / total * 100.0}
            for item in included
        ],
        key=lambda item: item["share_pct"],
        reverse=True,
    )
    return {
        "methodology": MARKET_CAP_SHARE_METHODOLOGY,
        "available": True,
        "base_date": max((str(item.get("date") or "") for item in items), default=""),
        "companies_registered": len(tickers),
        "companies_included": len(items),
        "companies_excluded": excluded,
        "coverage_count": len(items) / len(tickers) if tickers else 0.0,
        "coverage_market_cap": 1.0,
        "total_market_cap": total,
        "items": items,
        "share_sum_pct": sum(item["share_pct"] for item in items),
    }


def aggregate_ev_ebitda(indicators_payload: dict[str, Any], tickers: Iterable[str]) -> dict[str, Any]:
    tickers = tuple(tickers)
    companies = ((indicators_payload or {}).get("companies") or {})
    by_period: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        for row in ((companies.get(ticker) or {}).get("periodos") or []):
            metadata = row.get("metadata") or {}
            period_date = metadata.get("end_date")
            if not period_date:
                continue
            by_period.setdefault(period_date, {"included": [], "excluded": []})
            ev = as_number(row.get("enterprise_value"))
            ebitda = as_number(row.get("ebitda_ltm") if row.get("ebitda_ltm") is not None else row.get("ebitda_contabil_ltm"))
            if ev is None:
                by_period[period_date]["excluded"].append({"ticker": ticker, "reason": "enterprise_value ausente ou invalido"})
                continue
            if ebitda is None:
                by_period[period_date]["excluded"].append({"ticker": ticker, "reason": "EBITDA LTM ausente ou invalido"})
                continue
            by_period[period_date]["included"].append(
                {
                    "ticker": ticker,
                    "enterprise_value": ev,
                    "ebitda_ltm": ebitda,
                    "market_cap": as_number(row.get("market_cap_historico")),
                    "data_market_cap": row.get("data_market_cap"),
                    "data_divida_liquida": row.get("data_divida_liquida"),
                    "data_ebitda_ltm": row.get("data_ebitda_ltm") or period_date,
                }
            )
    series = []
    for period_date in sorted(by_period):
        included = by_period[period_date]["included"]
        ev_sum = sum(item["enterprise_value"] for item in included)
        ebitda_sum = sum(item["ebitda_ltm"] for item in included)
        market_cap_included = sum(item["market_cap"] for item in included if item.get("market_cap") is not None)
        value = ev_sum / ebitda_sum if included and ebitda_sum > 0 else None
        diagnostics = []
        if included and ebitda_sum <= 0:
            diagnostics.append("EBITDA LTM agregado menor ou igual a zero; multiplo nao calculado.")
        if not included:
            diagnostics.append("Nenhuma empresa com EV e EBITDA LTM validos no periodo.")
        series.append(
            {
                "period": period_label_from_date(period_date),
                "date": period_date,
                "value": value,
                "enterprise_value_sum": ev_sum if included else None,
                "ebitda_ltm_sum": ebitda_sum if included else None,
                "market_cap_included": market_cap_included,
                "companies_registered": len(tickers),
                "companies_included": len(included),
                "companies_excluded": by_period[period_date]["excluded"],
                "included_companies": included,
                "coverage_count": len(included) / len(tickers) if tickers else 0.0,
                "methodology": SECTOR_EV_EBITDA_METHODOLOGY,
                "diagnostics": diagnostics,
            }
        )
    return {"methodology": SECTOR_EV_EBITDA_METHODOLOGY, "series": series}


def _historical_rows(market_payload: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    empresa = ((market_payload or {}).get("empresas") or {}).get(ticker) or ((market_payload or {}).get("companies") or {}).get(ticker) or {}
    rows = []
    for row in empresa.get("periodos") or []:
        ref = parse_date(row.get("data_referencia") or row.get("date") or row.get("periodo"))
        price_date = parse_date(row.get("data_preco") or row.get("data_referencia"))
        price = valid_positive(row.get("preco_acao"))
        shares = valid_positive(row.get("quantidade_acoes_total"))
        if ref:
            rows.append({"ref": ref, "price_date": price_date or ref, "price": price, "shares": shares})
    return sorted(rows, key=lambda item: item["ref"])


def _row_at_or_before(rows: list[dict[str, Any]], target: date, field: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row["ref"] <= target and row.get(field) is not None]
    return candidates[-1] if candidates else None


def sector_price_returns(market_payload: dict[str, Any], tickers: Iterable[str], coverage_threshold: float = MIN_RETURN_COVERAGE) -> dict[str, Any]:
    tickers = tuple(tickers)
    rows_by_ticker = {ticker: _historical_rows(market_payload, ticker) for ticker in tickers}
    dates = sorted({row["ref"] for rows in rows_by_ticker.values() for row in rows})
    by_horizon: dict[str, list[dict[str, Any]]] = {"30d": [], "90d": [], "360d": []}
    for horizon in (30, 90, 360):
        key = f"{horizon}d"
        for ref in dates:
            target_start = ref - timedelta(days=horizon)
            included = []
            excluded = []
            total_initial_market_cap = 0.0
            for ticker in tickers:
                rows = rows_by_ticker[ticker]
                final_row = _row_at_or_before(rows, ref, "price")
                initial_price_row = _row_at_or_before(rows, target_start, "price")
                initial_shares_row = _row_at_or_before(rows, target_start, "shares")
                if not final_row or not initial_price_row or not initial_shares_row:
                    excluded.append({"ticker": ticker, "reason": "preco ou quantidade historica indisponivel"})
                    continue
                initial_market_cap = initial_price_row["price"] * initial_shares_row["shares"]
                if initial_market_cap <= 0:
                    excluded.append({"ticker": ticker, "reason": "market cap inicial invalido"})
                    continue
                total_initial_market_cap += initial_market_cap
                included.append(
                    {
                        "ticker": ticker,
                        "price_final": final_row["price"],
                        "price_final_date": final_row["price_date"].isoformat(),
                        "price_initial": initial_price_row["price"],
                        "target_initial_date": target_start.isoformat(),
                        "price_initial_date": initial_price_row["price_date"].isoformat(),
                        "shares": initial_shares_row["shares"],
                        "shares_date": initial_shares_row["ref"].isoformat(),
                        "return": final_row["price"] / initial_price_row["price"] - 1.0,
                        "initial_market_cap": initial_market_cap,
                        "approximation": initial_shares_row["ref"] != target_start,
                    }
                )
            coverage = len(included) / len(tickers) if tickers else 0.0
            if total_initial_market_cap > 0:
                for item in included:
                    item["weight"] = item["initial_market_cap"] / total_initial_market_cap
            value = sum(item["weight"] * item["return"] for item in included) if included and coverage >= coverage_threshold else None
            diagnostics = []
            if coverage < coverage_threshold:
                diagnostics.append(f"Cobertura por quantidade abaixo do minimo de {coverage_threshold:.0%}.")
            by_horizon[key].append(
                {
                    "period": period_label_from_date(ref.isoformat()),
                    "date": ref.isoformat(),
                    "value": value,
                    "return_pct": value * 100.0 if value is not None else None,
                    "total_initial_market_cap": total_initial_market_cap if included else None,
                    "coverage_count": coverage,
                    "coverage_market_cap": 1.0 if included else 0.0,
                    "companies_registered": len(tickers),
                    "companies_included": len(included),
                    "included_companies": included,
                    "companies_excluded": excluded,
                    "methodology": SECTOR_RETURN_METHODOLOGY,
                    "diagnostics": diagnostics,
                }
            )
    return {"methodology": SECTOR_RETURN_METHODOLOGY, "coverage_threshold": coverage_threshold, "series": by_horizon}


def build_sector_aggregates(indicators: dict[str, Any], market_cap: dict[str, Any], market_cap_historico: dict[str, Any], tickers: Iterable[str]) -> dict[str, Any]:
    return {
        "market_cap_share": market_cap_share(market_cap, tickers),
        "ev_ebitda_agregado": aggregate_ev_ebitda(indicators, tickers),
        "retornos_preco": sector_price_returns(market_cap_historico, tickers),
    }

"""Metricas agregadas setoriais para a aba Comparativo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable


SECTOR_EV_EBITDA_METHODOLOGY = "sector_aggregate_ev_ebitda_v1"
SECTOR_RETURN_METHODOLOGY = "sector_market_cap_weighted_price_return_v2"
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
        "coverage_market_cap": None if excluded else 1.0,
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


BLOCKED_MARKET_CAP_STATUSES = {
    "blocked",
    "excluded",
    "invalid",
    "missing",
    "missing_share_class_data",
    "shares_discrepancy",
    "cvm_scale_ambiguous",
    "unresolved",
}
MAX_RETURN_PRICE_STALENESS_DAYS = 7
MAX_MARKET_CAP_STALENESS_DAYS = 120


def _market_cap_is_valid(row: dict[str, Any]) -> bool:
    statuses = {
        str(row.get(field) or "").strip().lower()
        for field in ("status_market_cap", "status_validacao_acoes", "status_validacao_market_cap")
    }
    return valid_positive(row.get("market_cap")) is not None and not (statuses & BLOCKED_MARKET_CAP_STATUSES)


def _historical_rows(market_payload: dict[str, Any], ticker: str) -> dict[str, list[dict[str, Any]]]:
    empresa = ((market_payload or {}).get("empresas") or {}).get(ticker) or ((market_payload or {}).get("companies") or {}).get(ticker) or {}
    market_caps = []
    for row in empresa.get("periodos") or []:
        ref = parse_date(row.get("data_referencia") or row.get("date") or row.get("periodo"))
        if ref:
            market_caps.append(
                {
                    "ref": ref,
                    "market_cap": valid_positive(row.get("market_cap")) if _market_cap_is_valid(row) else None,
                    "nominal_price": valid_positive(row.get("preco_acao_raw") if row.get("preco_acao_raw") is not None else row.get("preco_acao")),
                    "shares": valid_positive(row.get("quantidade_acoes_utilizada") if row.get("quantidade_acoes_utilizada") is not None else row.get("quantidade_acoes_total")),
                    "status": row.get("status_market_cap") or row.get("status_validacao_acoes") or row.get("status_validacao_market_cap"),
                }
            )
    return_prices = []
    for row in empresa.get("precos_diarios_ajustados") or empresa.get("daily_adjusted_prices") or []:
        price_date = parse_date(row.get("data") or row.get("date"))
        price = valid_positive(row.get("preco_ajustado") if row.get("preco_ajustado") is not None else row.get("return_price"))
        if price_date and price is not None:
            return_prices.append({"ref": price_date, "price_date": price_date, "price": price})
    return {
        "market_caps": sorted(market_caps, key=lambda item: item["ref"]),
        "return_prices": sorted(return_prices, key=lambda item: item["ref"]),
    }


def _row_at_or_before(rows: list[dict[str, Any]], target: date, field: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row["ref"] <= target and row.get(field) is not None]
    return candidates[-1] if candidates else None


def _price_at_or_before(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    row = _row_at_or_before(rows, target, "price")
    if row is None or (target - row["price_date"]).days > MAX_RETURN_PRICE_STALENESS_DAYS:
        return None
    return row


def _market_cap_at_or_before(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    row = _row_at_or_before(rows, target, "market_cap")
    if row is None or (target - row["ref"]).days > MAX_MARKET_CAP_STALENESS_DAYS:
        return None
    return row


def sector_price_returns(market_payload: dict[str, Any], tickers: Iterable[str], coverage_threshold: float = MIN_RETURN_COVERAGE) -> dict[str, Any]:
    tickers = tuple(tickers)
    rows_by_ticker = {ticker: _historical_rows(market_payload, ticker) for ticker in tickers}
    dates = sorted({row["ref"] for history in rows_by_ticker.values() for row in history["market_caps"]})
    by_horizon: dict[str, list[dict[str, Any]]] = {"30d": [], "90d": [], "360d": []}
    for horizon in (30, 90, 360):
        key = f"{horizon}d"
        previous_total_market_cap: float | None = None
        for ref in dates:
            target_start = ref - timedelta(days=horizon)
            included = []
            excluded = []
            total_initial_market_cap = 0.0
            eligible_market_cap = 0.0
            unknown_market_cap_count = 0
            for ticker in tickers:
                history = rows_by_ticker[ticker]
                initial_market_cap_row = _market_cap_at_or_before(history["market_caps"], target_start)
                if not initial_market_cap_row:
                    unknown_market_cap_count += 1
                    excluded.append({"ticker": ticker, "reason": "market cap historico nominal inicial ausente, invalido ou bloqueado"})
                    continue
                initial_market_cap = initial_market_cap_row["market_cap"]
                eligible_market_cap += initial_market_cap
                final_row = _price_at_or_before(history["return_prices"], ref)
                initial_price_row = _price_at_or_before(history["return_prices"], target_start)
                if not final_row or not initial_price_row:
                    excluded.append({
                        "ticker": ticker,
                        "reason": "serie diaria de preco ajustado indisponivel ou defasada",
                        "eligible_market_cap": initial_market_cap,
                        "market_cap_date": initial_market_cap_row["ref"].isoformat(),
                    })
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
                        "nominal_price": initial_market_cap_row.get("nominal_price"),
                        "shares": initial_market_cap_row.get("shares"),
                        "market_cap_date": initial_market_cap_row["ref"].isoformat(),
                        "market_cap_status": initial_market_cap_row.get("status"),
                        "return": final_row["price"] / initial_price_row["price"] - 1.0,
                        "initial_market_cap": initial_market_cap,
                        "initial_date_gap_days": (target_start - initial_price_row["price_date"]).days,
                        "final_date_gap_days": (ref - final_row["price_date"]).days,
                        "market_cap_date_gap_days": (target_start - initial_market_cap_row["ref"]).days,
                    }
                )
            coverage = len(included) / len(tickers) if tickers else 0.0
            coverage_market_cap = (
                total_initial_market_cap / eligible_market_cap
                if eligible_market_cap > 0 and unknown_market_cap_count == 0
                else None
            )
            if total_initial_market_cap > 0:
                for item in included:
                    item["weight"] = item["initial_market_cap"] / total_initial_market_cap
            coverage_is_sufficient = (
                coverage >= coverage_threshold
                and coverage_market_cap is not None
                and coverage_market_cap >= coverage_threshold
            )
            value = sum(item["weight"] * item["return"] for item in included) if included and coverage_is_sufficient else None
            diagnostics = []
            if coverage < coverage_threshold:
                diagnostics.append(f"Cobertura por quantidade abaixo do minimo de {coverage_threshold:.0%}.")
            if unknown_market_cap_count:
                diagnostics.append(
                    "Cobertura por market cap indisponivel: "
                    f"{unknown_market_cap_count} empresa(s) sem valuation inicial confiavel."
                )
            elif coverage_market_cap is not None and coverage_market_cap < coverage_threshold:
                diagnostics.append(f"Cobertura por market cap abaixo do minimo de {coverage_threshold:.0%}.")
            largest = max(included, key=lambda item: item.get("weight", 0.0), default=None)
            largest_weight = largest.get("weight") if largest else None
            if largest_weight is not None and largest_weight > 0.80:
                diagnostics.append(f"Maior peso individual acima de 80%: {largest['ticker']} ({largest_weight:.1%}).")
            market_cap_change_ratio = None
            if previous_total_market_cap and total_initial_market_cap > 0:
                market_cap_change_ratio = max(total_initial_market_cap, previous_total_market_cap) / min(total_initial_market_cap, previous_total_market_cap)
                if market_cap_change_ratio >= 10:
                    diagnostics.append(f"Market cap inicial agregado mudou {market_cap_change_ratio:.1f}x contra o ponto anterior.")
            by_horizon[key].append(
                {
                    "period": period_label_from_date(ref.isoformat()),
                    "date": ref.isoformat(),
                    "value": value,
                    "return_pct": value * 100.0 if value is not None else None,
                    "total_initial_market_cap": total_initial_market_cap if included else None,
                    "coverage_count": coverage,
                    "eligible_initial_market_cap": eligible_market_cap if eligible_market_cap > 0 else None,
                    "coverage_market_cap": coverage_market_cap,
                    "largest_weight": largest_weight,
                    "largest_weight_ticker": largest.get("ticker") if largest else None,
                    "market_cap_change_ratio": market_cap_change_ratio,
                    "companies_registered": len(tickers),
                    "companies_included": len(included),
                    "included_companies": included,
                    "companies_excluded": excluded,
                    "methodology": SECTOR_RETURN_METHODOLOGY,
                    "diagnostics": diagnostics,
                }
            )
            if total_initial_market_cap > 0:
                previous_total_market_cap = total_initial_market_cap
    return {"methodology": SECTOR_RETURN_METHODOLOGY, "coverage_threshold": coverage_threshold, "series": by_horizon}


def build_sector_aggregates(indicators: dict[str, Any], market_cap: dict[str, Any], market_cap_historico: dict[str, Any], tickers: Iterable[str]) -> dict[str, Any]:
    return {
        "market_cap_share": market_cap_share(market_cap, tickers),
        "ev_ebitda_agregado": aggregate_ev_ebitda(indicators, tickers),
        "retornos_preco": sector_price_returns(market_cap_historico, tickers),
    }

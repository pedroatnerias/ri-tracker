#!/usr/bin/env python3
"""Gera PNGs Matplotlib derivados dos JSONs finais do dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dashboard import CHARTS, build_comparison_payload, dashboard_payload, make_chart_png
from company_registry import tickers_for_sector


COMPARISON_CHARTS: dict[str, dict[str, str]] = {
    "ciclo_financeiro": {"title": "Ciclo Financeiro", "ylabel": "Dias"},
    "margem_bruta": {"title": "Margem Bruta", "ylabel": "Margem Bruta (%)"},
    "margem_operacional": {"title": "Margem Operacional", "ylabel": "Margem Operacional (%)"},
    "margem_ebitda": {"title": "Margem EBITDA", "ylabel": "Margem EBITDA (%)"},
    "margem_liquida": {"title": "Margem Liquida", "ylabel": "Margem Liquida (%)"},
    "ev_ebitda_agregado": {"title": "EV/EBITDA Agregado", "ylabel": "EV/EBITDA (x)"},
    "retorno_preco_setorial_30d": {"title": "Retorno Setorial de Preco - 30 dias", "ylabel": "Retorno (%)"},
    "retorno_preco_setorial_360d": {"title": "Retorno Setorial de Preco - 360 dias", "ylabel": "Retorno (%)"},
}
SPECIAL_COMPARISON_CHARTS = {"market_cap_share", "ev_ebitda_agregado", "retorno_preco_setorial_30d", "retorno_preco_setorial_360d"}


def validate_png(path: Path, min_size: int = 500) -> None:
    if not path.exists():
        raise ValueError(f"PNG ausente: {path}")
    if path.stat().st_size < min_size:
        raise ValueError(f"PNG pequeno demais: {path}")
    with path.open("rb") as fh:
        signature = fh.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Assinatura PNG invalida: {path}")


def generate_individual_charts(resultados: Path, output_dir: Path, sector: str = "saude") -> list[Path]:
    generated: list[Path] = []
    for ticker in tickers_for_sector(sector):
        ticker_dir = output_dir / "individual" / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        for view in ("annual", "quarterly"):
            for chart_key in CHARTS:
                path = ticker_dir / f"{view}_{chart_key}.png"
                path.write_bytes(make_chart_png(resultados, ticker, view, chart_key, sector))
                validate_png(path)
                generated.append(path)
    return generated


def _comparison_period_sort(period: str) -> tuple[int, int]:
    text = str(period or "")
    if text.startswith("FY") and text[2:].isdigit():
        return int(text[2:]), 5
    if len(text) >= 4 and text[1].upper() == "T" and text[0].isdigit():
        yy = text[2:]
        return (2000 + int(yy[-2:]) if yy[-2:].isdigit() else 0, int(text[0]))
    return 0, 0


def generate_comparison_chart(chart_key: str, chart: dict[str, Any], output: Path, tickers: tuple[str, ...]) -> Path | None:
    config = COMPARISON_CHARTS[chart_key]
    series = chart.get("series") or {}
    periods = sorted(
        {point.get("period") for rows in series.values() for point in rows if point.get("period")},
        key=_comparison_period_sort,
    )
    values = [
        point.get("value")
        for rows in series.values()
        for point in rows
        if isinstance(point.get("value"), (int, float))
    ]
    if not periods or not values:
        return None

    fig_width = max(8.8, min(15.0, 0.55 * len(periods) + 5.5))
    fig, ax = plt.subplots(figsize=(fig_width, 3.8), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.axhline(0, color="#d8d0b0", linewidth=1.1)
    colors = ["#006341", "#23AC81", "#6B7C3A", "#B08A3C", "#6C8CA6", "#8A6F98", "#4D5D53"]
    x_by_period = {period: index for index, period in enumerate(periods)}

    for index, ticker in enumerate(tickers):
        rows = [
            point for point in series.get(ticker, [])
            if point.get("period") in x_by_period and isinstance(point.get("value"), (int, float))
        ]
        if not rows:
            continue
        x = [x_by_period[point["period"]] for point in rows]
        y = [point["value"] for point in rows]
        ax.plot(x, y, color=colors[index % len(colors)], marker="o", markersize=2.4, linewidth=1.0, label=ticker)

    ax.set_xticks(list(range(len(periods))))
    ax.set_xticklabels(periods, rotation=0 if len(periods) <= 8 else 45, ha="right" if len(periods) > 8 else "center", fontsize=8)
    ax.set_ylabel(config["ylabel"], color="#00513F", fontsize=9)
    ax.set_title(config["title"], color="#00513F", loc="left", fontsize=11, fontweight="bold")
    ax.tick_params(axis="x", labelsize=8, colors="#00513F", color="#DDD5B3")
    ax.tick_params(axis="y", labelsize=8, colors="#00513F", color="#DDD5B3")
    ax.spines["top"].set_visible(False)
    for spine in ("left", "right", "bottom"):
        ax.spines[spine].set_color("#DDD5B3")
    ax.grid(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=min(len(tickers), 4), frameon=False, fontsize=8)
    fig.tight_layout(pad=1.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    validate_png(output)
    return output


def generate_market_cap_share_chart(share: dict[str, Any], output: Path) -> Path | None:
    items = share.get("items") or []
    if not share.get("available") or not items:
        return None
    labels = [f"{item['ticker']}\n{item['share_pct']:.1f}%" for item in items]
    values = [item["market_cap"] for item in items]
    colors = [f"C{index % 10}" for index, _ in enumerate(items)]
    fig, ax = plt.subplots(figsize=(7.2, 5.2), dpi=150)
    ax.pie(values, labels=labels, colors=colors, startangle=90, counterclock=False, textprops={"fontsize": 7})
    total = share.get("total_market_cap")
    title = "Participacao no market cap setorial"
    subtitle = f"Total incluido: R$ {total / 1_000_000_000:.1f} bi | Cobertura: {share.get('companies_included')}/{share.get('companies_registered')}"
    ax.set_title(f"{title}\n{subtitle}", color="#00513F", fontsize=10, fontweight="bold")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    validate_png(output)
    return output


def _generate_single_series_chart(series: list[dict[str, Any]], output: Path, title: str, ylabel: str) -> Path | None:
    rows = [row for row in series if isinstance(row.get("value"), (int, float))]
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(9.2, 3.8), dpi=150)
    x = list(range(len(rows)))
    ax.axhline(0, color="#d8d0b0", linewidth=1.0)
    ax.plot(x, [row["value"] for row in rows], color="#006341", marker="o", linewidth=1.4, markersize=3.0)
    ax.set_xticks(x)
    ax.set_xticklabels([row.get("period") or row.get("date") for row in rows], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(ylabel, color="#00513F", fontsize=9)
    ax.set_title(title, color="#00513F", loc="left", fontsize=11, fontweight="bold")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout(pad=1.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    validate_png(output)
    return output


def _generate_return_chart(series: list[dict[str, Any]], output: Path, title: str) -> Path | None:
    rows = [row for row in series if isinstance(row.get("return_pct"), (int, float))]
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(9.2, 3.8), dpi=150)
    x = list(range(len(rows)))
    ax2 = ax.twinx()
    ax.axhline(0, color="#d8d0b0", linewidth=1.0)
    ax.plot(x, [row["return_pct"] for row in rows], color="#006341", marker="o", linewidth=1.4, label="Retorno")
    ax2.plot(x, [(row.get("total_initial_market_cap") or 0) / 1_000_000_000 for row in rows], color="#B08A3C", linewidth=1.1, label="Market cap inicial")
    ax.set_xticks(x)
    ax.set_xticklabels([row.get("period") or row.get("date") for row in rows], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Retorno (%)", color="#00513F", fontsize=9)
    ax2.set_ylabel("Market cap inicial (R$ bi)", color="#7A5A1C", fontsize=9)
    ax.set_title(title, color="#00513F", loc="left", fontsize=11, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    fig.tight_layout(pad=1.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    validate_png(output)
    return output


def generate_sector_aggregate_charts(aggregates: dict[str, Any], output_dir: Path) -> list[Path]:
    generated: list[Path] = []
    target_dir = output_dir / "comparison"
    jobs = [
        ("market_cap_share", lambda path: generate_market_cap_share_chart(aggregates.get("market_cap_share") or {}, path)),
        ("ev_ebitda_agregado", lambda path: _generate_single_series_chart((aggregates.get("ev_ebitda_agregado") or {}).get("series") or [], path, "EV/EBITDA agregado do setor", "EV/EBITDA (x)")),
        ("retorno_preco_setorial_30d", lambda path: _generate_return_chart(((aggregates.get("retornos_preco") or {}).get("series") or {}).get("30d") or [], path, "Retorno setorial de preco - 30 dias")),
        ("retorno_preco_setorial_360d", lambda path: _generate_return_chart(((aggregates.get("retornos_preco") or {}).get("series") or {}).get("360d") or [], path, "Retorno setorial de preco - 360 dias")),
    ]
    for key, factory in jobs:
        path = target_dir / f"{key}.png"
        result = factory(path)
        if result:
            generated.append(result)
        elif path.exists():
            path.unlink()
    return generated


def generate_comparison_charts(resultados: Path, output_dir: Path, sector: str = "saude") -> list[Path]:
    payload = dashboard_payload(resultados, sector=sector)
    tickers = tickers_for_sector(sector)
    comparison = payload.get("comparison") or build_comparison_payload(payload.get("indicators") or {}, payload.get("operational") or {}, tickers)
    charts = comparison.get("charts") or {}
    aggregates = comparison.get("sector_aggregates") or {}
    target_dir = output_dir / "comparison"
    target_dir.mkdir(parents=True, exist_ok=True)
    old_ev = target_dir / "ev_ebitda_ltm.png"
    if old_ev.exists():
        old_ev.unlink()
    generated: list[Path] = []
    for chart_key in COMPARISON_CHARTS:
        if chart_key in SPECIAL_COMPARISON_CHARTS:
            continue
        path = target_dir / f"{chart_key}.png"
        result = generate_comparison_chart(chart_key, charts.get(chart_key) or {}, path, tickers)
        if result:
            generated.append(result)
    generated.extend(generate_sector_aggregate_charts(aggregates, output_dir))
    return generated


def generate_all_charts(resultados: Path, output_dir: Path, sector: str = "saude") -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    generated.extend(generate_individual_charts(resultados, output_dir, sector))
    generated.extend(generate_comparison_charts(resultados, output_dir, sector))
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resultados", type=Path, default=Path("resultados"))
    parser.add_argument("--output-dir", type=Path, default=Path("resultados") / "charts")
    parser.add_argument("--sector", choices=("saude", "construcao_civil", "all"), default="saude")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sectors = ("saude", "construcao_civil") if args.sector == "all" else (args.sector,)
    generated = []
    for sector in sectors:
        sector_resultados = args.resultados.resolve() / sector if (args.resultados.resolve() / sector).is_dir() else args.resultados.resolve()
        generated.extend(generate_all_charts(args.resultados.resolve(), sector_resultados / "charts", sector))
    print(f"Graficos gerados: {len(generated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

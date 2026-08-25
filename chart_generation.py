#!/usr/bin/env python3
"""Gera PNGs Matplotlib derivados dos JSONs finais do dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dashboard import CHARTS, TICKERS, build_comparison_payload, dashboard_payload, make_chart_png
from company_registry import tickers_for_sector


COMPARISON_CHARTS: dict[str, dict[str, str]] = {
    "ciclo_financeiro": {"title": "Ciclo Financeiro", "ylabel": "Dias"},
    "margem_bruta": {"title": "Margem Bruta", "ylabel": "Margem Bruta (%)"},
    "margem_operacional": {"title": "Margem Operacional", "ylabel": "Margem Operacional (%)"},
    "margem_ebitda": {"title": "Margem EBITDA", "ylabel": "Margem EBITDA (%)"},
    "margem_liquida": {"title": "Margem Liquida", "ylabel": "Margem Liquida (%)"},
}


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


def generate_comparison_chart(chart_key: str, chart: dict[str, Any], output: Path) -> Path | None:
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

    for index, ticker in enumerate(TICKERS):
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
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=min(len(TICKERS), 4), frameon=False, fontsize=8)
    fig.tight_layout(pad=1.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    validate_png(output)
    return output


def generate_comparison_charts(resultados: Path, output_dir: Path, sector: str = "saude") -> list[Path]:
    payload = dashboard_payload(resultados, sector=sector)
    comparison = payload.get("comparison") or build_comparison_payload(payload.get("indicators") or {}, payload.get("operational") or {})
    charts = comparison.get("charts") or {}
    target_dir = output_dir / "comparison"
    target_dir.mkdir(parents=True, exist_ok=True)
    old_ev = target_dir / "ev_ebitda_ltm.png"
    if old_ev.exists():
        old_ev.unlink()
    generated: list[Path] = []
    for chart_key in COMPARISON_CHARTS:
        path = target_dir / f"{chart_key}.png"
        result = generate_comparison_chart(chart_key, charts.get(chart_key) or {}, path)
        if result:
            generated.append(result)
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
        generated.extend(generate_all_charts(args.resultados.resolve(), args.output_dir.resolve() / sector, sector))
    print(f"Graficos gerados: {len(generated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

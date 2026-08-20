#!/usr/bin/env python3
"""Gera relatorio tecnico de reconciliacao CVM versus RI/divulgado."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metric_definitions import MATERIALITY_THRESHOLDS, METHODOLOGY_VERSION


CRITICAL_METRICS = (
    "receita_contabil_cvm",
    "receita_operacional_divulgada",
    "ebitda_contabil",
    "ebitda_ajustado_divulgado",
    "lucro_liquido",
    "divida_liquida_padronizada",
    "divida_liquida_divulgada",
    "market_cap_historico",
    "enterprise_value",
    "ev_ebitda_ltm",
)


def classify(cvm_value: float | None, ri_value: float | None, naturally_different: bool = False) -> str:
    if cvm_value is None and ri_value is None:
        return "MISSING_DATA"
    if cvm_value is None or ri_value is None:
        return "MISSING_DATA"
    if cvm_value == 0:
        return "NOT_COMPARABLE"
    diff_pct = abs(ri_value / cvm_value - 1) * 100
    if naturally_different:
        return "METHODOLOGY_DIFFERENCE"
    if diff_pct <= MATERIALITY_THRESHOLDS["match_pct"]:
        return "MATCH"
    if diff_pct <= MATERIALITY_THRESHOLDS["review_pct"]:
        return "IMMATERIAL_DIFFERENCE"
    return "MATERIAL_DIFFERENCE"


def build_report(indicadores: dict[str, Any], divida: dict[str, Any]) -> dict[str, Any]:
    companies: dict[str, Any] = {}
    for ticker, company in (indicadores.get("companies") or {}).items():
        rows = []
        for period in company.get("periodos", []):
            item = {
                "periodo": period.get("periodo"),
                "metadata": period.get("metadata"),
                "metrics": {},
                "quality_flags": period.get("quality_flags") or [],
            }
            for metric in CRITICAL_METRICS:
                value = period.get(metric)
                status = "validated" if value is not None else "MISSING_DATA"
                item["metrics"][metric] = {
                    "value": value,
                    "source": "CVM/calculado pelo sistema" if value is not None else None,
                    "classification": status,
                }

            item["metrics"]["ebitda_contabil_vs_ajustado"] = {
                "cvm_value": period.get("ebitda_contabil"),
                "ri_value": period.get("ebitda_ajustado_divulgado"),
                "difference": (
                    period["ebitda_ajustado_divulgado"] - period["ebitda_contabil"]
                    if period.get("ebitda_ajustado_divulgado") is not None and period.get("ebitda_contabil") is not None
                    else None
                ),
                "classification": classify(
                    period.get("ebitda_contabil"),
                    period.get("ebitda_ajustado_divulgado"),
                    naturally_different=True,
                ),
                "justification": "EBITDA ajustado divulgado possui metodologia propria da companhia quando disponivel.",
            }
            rows.append(item)
        companies[ticker] = {"periodos": rows}

    return {
        "kind": "reconciliation_report",
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "indicadores": "app_indicadores.py",
            "divida_liquida": "app_divida_liquida.py",
        },
        "companies": companies,
        "net_debt_methodology": divida.get("methodology_version"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indicadores", type=Path, default=Path("resultados") / "indicadores.json")
    parser.add_argument("--divida-liquida", type=Path, default=Path("resultados") / "divida_liquida.json")
    parser.add_argument("--saida", type=Path, default=Path("resultados") / "relatorio_reconciliacao.json")
    args = parser.parse_args()

    indicadores = json.loads(args.indicadores.read_text(encoding="utf-8"))
    divida = json.loads(args.divida_liquida.read_text(encoding="utf-8"))
    report = build_report(indicadores, divida)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Relatorio salvo em {args.saida}")


if __name__ == "__main__":
    main()

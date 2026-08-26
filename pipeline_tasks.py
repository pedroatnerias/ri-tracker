"""Etapas reutilizaveis do pipeline sem duplicar logica nos workflows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import chart_generation
import data_publication
from company_registry import validate_sector
from dashboard import find_balanco_json


def script_path(name: str) -> str:
    return str(Path(__file__).resolve().parent / name)


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


def sector_result_dir(resultados: Path, sector: str) -> Path:
    sector = validate_sector(sector)
    if sector != "all" and (resultados / sector).is_dir():
        return resultados / sector
    return resultados


def recalculate_indicators(resultados: Path, sector: str) -> dict[str, object]:
    base = sector_result_dir(resultados, sector)
    balanco = find_balanco_json(base)
    paths = {
        "dre": base / "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": base / "DFC_ITR_CVM.json",
        "divida": base / "divida_liquida.json",
        "ciclo": base / "ciclo_financeiro.json",
        "market_hist": base / "market_cap_historico.json",
        "indicadores": base / "indicadores.json",
    }
    missing = [str(path) for path in [balanco, *paths.values()] if not path.exists() and path.name != "indicadores.json"]
    if missing:
        return {"status": "missing_inputs", "missing": missing}
    run_command([sys.executable, script_path("app_divida_liquida.py"), "calculate", str(balanco), "--output", str(paths["divida"])])
    run_command([sys.executable, script_path("app_ciclo_financeiro.py"), str(balanco), str(paths["ciclo"]), "--dre", str(paths["dre"]), "--sector", sector])
    run_command(
        [
            sys.executable,
            script_path("app_indicadores.py"),
            str(paths["dre"]),
            str(paths["indicadores"]),
            "--dfc",
            str(paths["dfc"]),
            "--market-cap-historico",
            str(paths["market_hist"]),
            "--divida-liquida",
            str(paths["divida"]),
            "--balanco",
            str(balanco),
        ]
    )
    return {"status": "success", "sector": sector, "updated": ["divida_liquida", "ciclo_financeiro", "indicadores"]}


def regenerate_charts(resultados: Path, sector: str) -> dict[str, object]:
    generated = chart_generation.generate_all_charts(resultados.resolve(), sector_result_dir(resultados.resolve(), sector) / "charts", sector)
    return {"status": "success", "sector": sector, "generated": [str(path) for path in generated]}


def validate_outputs(resultados: Path, sector: str, scope: str = "financial") -> dict[str, object]:
    return data_publication.validate_results(resultados, scope=scope, sector=sector)


def sectors_arg(sector: str) -> tuple[str, ...]:
    return ("saude", "construcao_civil") if validate_sector(sector) == "all" else (sector,)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("recalculate-indicators", "regenerate-charts", "rebuild-dashboard-no-fetch"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--resultados", type=Path, default=Path("resultados"))
        cmd.add_argument("--sector", choices=("all", "saude", "construcao_civil"), default="saude")
        cmd.add_argument("--scope", choices=("all", "financial", "market", "sector_aggregates"), default="financial")
        cmd.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    summary: dict[str, object] = {"command": args.command, "sector": args.sector, "external_fetch_enabled": False, "sectors": {}}
    for sector in sectors_arg(args.sector):
        if args.command in {"recalculate-indicators", "rebuild-dashboard-no-fetch"}:
            summary["sectors"][sector] = recalculate_indicators(args.resultados, sector)
        if args.command in {"regenerate-charts", "rebuild-dashboard-no-fetch"}:
            summary["sectors"].setdefault(sector, {})
            summary["sectors"][sector]["charts"] = regenerate_charts(args.resultados, sector)
        validate_outputs(args.resultados, sector, "financial")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

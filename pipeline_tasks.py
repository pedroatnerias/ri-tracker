"""Etapas reutilizaveis do pipeline sem duplicar logica nos workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import chart_generation
import data_publication
from sector_paths import expand_sectors, find_financial_statement_json, read_json_if_exists, resolve_sector_results_dir


def script_path(name: str) -> str:
    return str(Path(__file__).resolve().parent / name)


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


def ensure_no_external_fetch() -> None:
    value = os.environ.get("EXTERNAL_FETCH_ENABLED", "false").strip().lower()
    if value not in {"0", "false", "no", "off"}:
        raise SystemExit("Modo sem coleta violado: EXTERNAL_FETCH_ENABLED deve permanecer false.")


def data_repo_sector_dir(data_repo: Path, sector: str) -> Path:
    candidates = [
        data_repo / "data" / "sectors" / sector,
        data_repo / "sectors" / sector,
        data_repo / "data" if sector == "saude" else data_repo / "data" / sector,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def hydrate_existing_data(data_repo: Path, resultados: Path, sector: str, requirements: str) -> dict[str, object]:
    ensure_no_external_fetch()
    restored: dict[str, object] = {"requirements": requirements, "sectors": {}}
    for current_sector in expand_sectors(sector):
        source = data_repo_sector_dir(data_repo, current_sector)
        target = resolve_sector_results_dir(resultados, current_sector, create=True)
        if not source.exists():
            raise FileNotFoundError(f"Dados publicados ausentes para {current_sector}: {source}")
        copied: list[str] = []
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if requirements != "dashboard" and relative.parts and relative.parts[0] == "publish_staging":
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied.append(relative.as_posix())
        manifest = read_json_if_exists(target / "data_manifest.json")
        balanco = find_financial_statement_json(target, "balanco", manifest)
        restored["sectors"][current_sector] = {
            "source": str(source),
            "target": str(target),
            "manifest": str(target / "data_manifest.json") if (target / "data_manifest.json").exists() else "",
            "balanco": str(balanco),
            "files_restored": copied,
        }
    return restored


def recalculate_indicators(resultados: Path, sector: str, scope: str = "financial") -> dict[str, object]:
    ensure_no_external_fetch()
    base = resolve_sector_results_dir(resultados, sector)
    manifest = read_json_if_exists(base / "data_manifest.json")
    try:
        balanco = find_financial_statement_json(base, "balanco", manifest)
    except FileNotFoundError as exc:
        return {"status": "missing_inputs", "sector": sector, "scope": scope, "error": str(exc)}
    paths = {
        "dre": base / "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": base / "DFC_ITR_CVM.json",
        "divida": base / "divida_liquida.json",
        "ciclo": base / "ciclo_financeiro.json",
        "market_hist": base / "market_cap_historico.json",
        "indicadores": base / "indicadores.json",
    }
    required = [balanco, paths["dre"], paths["dfc"], paths["market_hist"]]
    if scope in {"market", "sector_aggregates"}:
        required.append(paths["divida"])
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return {"status": "missing_inputs", "sector": sector, "scope": scope, "missing": missing}
    updated: list[str] = []
    if scope in {"all", "financial"}:
        run_command([sys.executable, script_path("app_divida_liquida.py"), "calculate", str(balanco), "--output", str(paths["divida"])])
        run_command([sys.executable, script_path("app_ciclo_financeiro.py"), str(balanco), str(paths["ciclo"]), "--dre", str(paths["dre"]), "--sector", sector])
        updated.extend(["divida_liquida", "ciclo_financeiro"])
    if scope in {"all", "financial", "market", "sector_aggregates"}:
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
        updated.append("indicadores")
    return {"status": "success", "sector": sector, "scope": scope, "updated": updated}


def regenerate_charts(resultados: Path, sector: str, chart_scope: str = "all", ticker: str = "all") -> dict[str, object]:
    ensure_no_external_fetch()
    base = resolve_sector_results_dir(resultados.resolve(), sector)
    generated = chart_generation.generate_all_charts(resultados.resolve(), base / "charts", sector, chart_scope=chart_scope, ticker=ticker)
    return {"status": "success", "sector": sector, "chart_scope": chart_scope, "ticker": ticker, "generated": [str(path) for path in generated]}


def validate_outputs(resultados: Path, sector: str, scope: str = "financial") -> dict[str, object]:
    return data_publication.validate_results(resultados, scope=scope, sector=sector)


def run_recalculate_indicators(resultados: Path, sector: str, scope: str) -> dict[str, object]:
    return {"sectors": {current: recalculate_indicators(resultados, current, scope) for current in expand_sectors(sector)}}


def run_regenerate_charts(resultados: Path, sector: str, chart_scope: str, ticker: str) -> dict[str, object]:
    return {"sectors": {current: regenerate_charts(resultados, current, chart_scope, ticker) for current in expand_sectors(sector)}}


def run_rebuild_dashboard_no_fetch(resultados: Path, sector: str, force_rebuild: bool = False) -> dict[str, object]:
    sectors: dict[str, object] = {}
    for current in expand_sectors(sector):
        recalc = recalculate_indicators(resultados, current, "all")
        charts = regenerate_charts(resultados, current, "all", "all")
        manifest = validate_outputs(resultados, current, "financial")
        sectors[current] = {"recalculate": recalc, "charts": charts, "manifest": manifest, "force_rebuild": force_rebuild}
    return {"sectors": sectors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    hydrate = sub.add_parser("hydrate-existing-data")
    hydrate.add_argument("--data-repo", type=Path, required=True)
    hydrate.add_argument("--resultados", type=Path, default=Path("resultados"))
    hydrate.add_argument("--sector", choices=("all", "saude", "construcao_civil"), default="all")
    hydrate.add_argument("--requirements", choices=("indicators", "charts", "dashboard"), required=True)
    for name in ("recalculate-indicators", "regenerate-charts", "rebuild-dashboard-no-fetch"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--resultados", type=Path, default=Path("resultados"))
        cmd.add_argument("--sector", choices=("all", "saude", "construcao_civil"), default="saude")
        cmd.add_argument("--scope", choices=("all", "financial", "market", "sector_aggregates"), default="financial")
        cmd.add_argument("--chart-scope", choices=("all", "individual", "comparison", "sector"), default="all")
        cmd.add_argument("--ticker", default="all")
        cmd.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    summary: dict[str, object] = {"command": args.command, "sector": args.sector, "external_fetch_enabled": False}
    if args.command == "hydrate-existing-data":
        summary.update(hydrate_existing_data(args.data_repo, args.resultados, args.sector, args.requirements))
    elif args.command == "recalculate-indicators":
        summary.update(run_recalculate_indicators(args.resultados, args.sector, args.scope))
    elif args.command == "regenerate-charts":
        summary.update(run_regenerate_charts(args.resultados, args.sector, args.chart_scope, args.ticker))
    elif args.command == "rebuild-dashboard-no-fetch":
        summary.update(run_rebuild_dashboard_no_fetch(args.resultados, args.sector, args.force_rebuild))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

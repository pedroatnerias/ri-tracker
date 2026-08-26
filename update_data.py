#!/usr/bin/env python3
"""Entrypoint CLI para atualizar os JSONs do Nerias RI Tracker."""

from __future__ import annotations

import argparse
from pathlib import Path

from dashboard import run_update, resolve_app_path
from company_registry import SECTORS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sector",
        choices=tuple(sorted(SECTORS)),
        default="saude",
        help="Setor processado. Padrao retrocompativel: saude.",
    )
    parser.add_argument(
        "--resultados",
        type=Path,
        default=Path("resultados"),
        help="Pasta onde os JSONs finais serao gerados.",
    )
    parser.add_argument(
        "--anos",
        nargs="+",
        type=int,
        help="Anos a passar para os apps da CVM. Quando omitido, usa a janela padrao do dashboard.",
    )
    parser.add_argument(
        "--diagnostico-ri",
        action="store_true",
        help="Repassa --diagnostico-ri somente para a etapa app_parser_operacional.py.",
    )
    parser.add_argument(
        "--mode",
        choices=("incremental", "full"),
        default="incremental",
        help="Modo de atualizacao do pipeline. Padrao: incremental.",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "financial", "operational"),
        default="all",
        help="Escopo independente da atualizacao. Padrao: all.",
    )
    parser.add_argument(
        "--refresh-cvm-files",
        choices=("auto", "force", "never"),
        default="auto",
        help="Politica de obtencao dos ZIPs CVM.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    resultados = resolve_app_path(args.resultados)
    run_update(
        resultados,
        args.anos,
        mode=args.mode,
        scope=args.scope,
        sector=args.sector,
        diagnostico_ri=args.diagnostico_ri,
        refresh_cvm_files=args.refresh_cvm_files,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

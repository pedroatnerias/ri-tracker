#!/usr/bin/env python3
"""Entrypoint CLI para atualizar os JSONs do Nerias RI Tracker."""

from __future__ import annotations

import argparse
from pathlib import Path

from dashboard import run_full_update, resolve_app_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resultados = resolve_app_path(args.resultados)
    run_full_update(resultados, args.anos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

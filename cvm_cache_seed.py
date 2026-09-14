"""Compartilha ZIPs CVM validos entre caches setoriais restaurados no CI."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from company_registry import REAL_SECTORS
from cvm_downloads import validate_zip


def parse_year(path: Path, doc: str) -> int | None:
    prefix = f"{doc}_cia_aberta_"
    if not path.name.startswith(prefix) or path.suffix.lower() != ".zip":
        return None
    try:
        return int(path.stem.removeprefix(prefix))
    except ValueError:
        return None


def valid_complete_zip(path: Path, year: int, doc: str) -> bool:
    return all(validate_zip(path, year, doc, kind) for kind in ("bp", "dre", "dfc"))


def seed_cvm_cache(resultados: Path, sector: str) -> list[Path]:
    resultados = resultados.expanduser().resolve()
    targets = REAL_SECTORS if sector == "all" else (sector,)
    copied: list[Path] = []
    for doc in ("itr", "dfp"):
        sources: dict[int, Path] = {}
        for source in resultados.glob(f"*/downloads/{doc}/{doc}_cia_aberta_*.zip"):
            year = parse_year(source, doc)
            if year is not None and valid_complete_zip(source, year, doc):
                sources.setdefault(year, source)
        for target_sector in targets:
            target_dir = resultados / target_sector / "downloads" / doc
            target_dir.mkdir(parents=True, exist_ok=True)
            for year, source in sources.items():
                target = target_dir / source.name
                if valid_complete_zip(target, year, doc):
                    continue
                with tempfile.NamedTemporaryFile(
                    prefix=f".{source.stem}.", suffix=".tmp", dir=target_dir, delete=False
                ) as temporary:
                    temp_path = Path(temporary.name)
                    with source.open("rb") as source_file:
                        shutil.copyfileobj(source_file, temporary, length=1024 * 1024)
                try:
                    if not valid_complete_zip(temp_path, year, doc):
                        raise RuntimeError(f"Copia de cache CVM invalida: {source}")
                    os.replace(temp_path, target)
                    copied.append(target)
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resultados", type=Path, default=Path("resultados"))
    parser.add_argument("--sector", choices=(*REAL_SECTORS, "all"), required=True)
    args = parser.parse_args()
    copied = seed_cvm_cache(args.resultados, args.sector)
    print(f"ZIPs CVM compartilhados com o setor de destino: {len(copied)}")
    for path in copied:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

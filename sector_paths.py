"""Resolucao centralizada de caminhos setoriais e arquivos financeiros."""

from __future__ import annotations

import json
from pathlib import Path

from company_registry import validate_sector


SECTOR_NAMES = ("saude", "construcao_civil")


def resolve_releases_input_dir(base: Path, sector: str, *, create: bool = False) -> Path:
    path = Path(base).resolve() / "Releases e relatórios" / "Entrada" / validate_sector(sector)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_releases_output_dir(base: Path, sector: str, *, create: bool = False) -> Path:
    path = Path(base).resolve() / "Releases e relatórios" / "Saída" / validate_sector(sector)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_releases_manifest_path(base: Path, sector: str) -> Path:
    return Path(base).resolve() / "Releases e relatórios" / f"manifesto_downloads_{validate_sector(sector)}.json"


def resolve_operational_results_dir(base: Path, sector: str, *, create: bool = False) -> Path:
    path = resolve_sector_results_dir(base, sector, create=create) / "dados_operacionais"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def expand_sectors(sector: str) -> tuple[str, ...]:
    return SECTOR_NAMES if validate_sector(sector) == "all" else (validate_sector(sector),)


def resolve_sector_results_dir(resultados: Path, sector: str, *, create: bool = False) -> Path:
    sector = validate_sector(sector)
    if sector == "all":
        raise ValueError("resolve_sector_results_dir espera um setor real, nao 'all'.")
    resultados = Path(resultados).resolve()
    sector_dir = resultados / sector
    if create:
        sector_dir.mkdir(parents=True, exist_ok=True)
        return sector_dir
    if sector_dir.exists():
        return sector_dir
    if sector == "saude" and (
        any(resultados.glob("balancos_itr_cvm_*.json"))
        or (resultados / "dados_operacionais").exists()
        or (resultados / "manual_operational_overrides.json").exists()
    ):
        return resultados
    return sector_dir


def read_json_if_exists(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def manifest_file_for_statement(manifest: dict[str, object] | None, statement: str) -> str | None:
    if not manifest:
        return None
    files = manifest.get("files")
    if isinstance(files, dict):
        value = files.get(statement)
        if isinstance(value, str) and value:
            return value
    root_jsons = manifest.get("root_jsons")
    if isinstance(root_jsons, list) and statement == "balanco":
        return next((str(name) for name in root_jsons if str(name).startswith("balancos_itr_cvm_")), None)
    return None


def find_financial_statement_json(base: Path, statement: str = "balanco", manifest: dict[str, object] | None = None) -> Path:
    base = Path(base)
    canonical = manifest_file_for_statement(manifest, statement)
    if canonical:
        candidate = base / canonical
        if candidate.exists():
            return candidate
    patterns = {
        "balanco": "balancos_itr_cvm_*.json",
        "dre": "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": "DFC_ITR_CVM.json",
    }
    candidates = sorted(base.glob(patterns.get(statement, statement)), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    manifest_path = base / "data_manifest.json"
    found = sorted(path.name for path in base.glob("*.json"))
    raise FileNotFoundError(
        "Nenhum JSON de balanço foi encontrado entre os dados restaurados.\n"
        f"Pasta pesquisada: {base}\n"
        f"Manifest consultado: {manifest_path if manifest_path.exists() else 'ausente'}\n"
        f"Arquivos JSON encontrados: {found or 'nenhum'}"
    )

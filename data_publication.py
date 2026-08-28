#!/usr/bin/env python3
"""Validacao e publicacao dos JSONs finais no repositorio de dados."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from manual_operational import MANUAL_OVERRIDES_FILENAME
from manual_operational import normalize_manual_payload, resolve_operational_data_with_manual
from company_registry import operational_companies
from sector_paths import find_financial_statement_json, read_json_if_exists, resolve_sector_results_dir
from company_registry import SECTORS, tickers_for_sector, validate_sector

BASE_DIR = Path(__file__).resolve().parent
PUBLICATION_SCOPES = {"all", "financial", "operational"}

REQUIRED_ROOT_JSONS = [
    "DRE_ITR_CVM_ultimos_5_anos.json",
    "DFC_ITR_CVM.json",
    "divida_liquida.json",
    "ciclo_financeiro.json",
    "market_cap.json",
    "market_cap_historico.json",
    "indicadores.json",
    "relatorio_reconciliacao.json",
]

BLOCKED_TERMS = [
    "DATA_REPO_TOKEN",
    "Nerias Dropbox",
    "A3 Capital",
    "ghp_",
    "github_pat_",
    "-----BEGIN",
]

RESIDUAL_LOCAL_PATH_TERMS = [
    "/home/runner/work/",
    "C:\\Users\\",
    "C:/Users/",
]


def publication_staging_dir(source: Path) -> Path:
    return source.resolve().parent / "publish_staging"


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_json_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Arquivo {label} ausente: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"Arquivo {label} JSON vazio: {path}")
    read_json(path)


def validate_png_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Arquivo {label} ausente: {path}")
    if path.stat().st_size < 500:
        raise SystemExit(f"Arquivo {label} PNG vazio/pequeno demais: {path}")
    with path.open("rb") as fh:
        if fh.read(8) != b"\x89PNG\r\n\x1a\n":
            raise SystemExit(f"Arquivo {label} nao e PNG valido: {path}")


def validate_blocked_terms(paths: list[Path]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for term in BLOCKED_TERMS:
            if term in text:
                raise SystemExit(f"Termo potencialmente privado encontrado em {path}: {term}")
        for term in RESIDUAL_LOCAL_PATH_TERMS:
            if term in text:
                raise SystemExit(f"Caminho local residual encontrado em {path}: {term}")


def normalize_path_text(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").rstrip("/")


def sanitize_string(value: str) -> str:
    sanitized = value
    project_root = normalize_path_text(BASE_DIR)
    project_parent = normalize_path_text(BASE_DIR.parent)
    replacements = [
        ("/home/runner/work/ri-tracker/ri-tracker/", ""),
        ("/home/runner/work/ri-tracker/ri-tracker", ""),
        (f"{project_root}/", ""),
        (project_root, ""),
        (f"{project_parent}/", "<LOCAL_PATH>/"),
        (project_parent, "<LOCAL_PATH>"),
        ("/home/runner/work/", "<LOCAL_PATH>/"),
    ]
    windows_root = str(BASE_DIR.resolve()).rstrip("\\")
    windows_parent = str(BASE_DIR.parent.resolve()).rstrip("\\")
    replacements.extend(
        [
            (f"{windows_root}\\", ""),
            (windows_root, ""),
            (f"{windows_parent}\\", "<LOCAL_PATH>\\"),
            (windows_parent, "<LOCAL_PATH>"),
        ]
    )
    for old, new in replacements:
        if old:
            sanitized = sanitized.replace(old, new)
    return sanitized


def sanitize_json_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_string(value)
    return value


def reset_staging(staging: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)


def write_sanitized_copy(source_path: Path, source_root: Path, staging: Path) -> Path:
    relative = source_path.relative_to(source_root)
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_json_value(read_json(source_path))
    target.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_json_file(target, "sanitizado para publicacao")
    return target


def validate_scope(scope: str) -> str:
    normalized = (scope or "all").lower()
    if normalized not in PUBLICATION_SCOPES:
        raise SystemExit(f"Scope de publicacao invalido: {scope}")
    return normalized


def build_publication_staging(base: Path, manifest: dict[str, object]) -> Path:
    staging = publication_staging_dir(base)
    reset_staging(staging)
    publish_relatives = list(manifest["root_jsons"]) + list(manifest["operational_jsons"]) + ["data_manifest.json"]
    if manifest.get("manual_operational_overrides"):
        publish_relatives.append(MANUAL_OVERRIDES_FILENAME)
    staged_paths = [
        write_sanitized_copy(base / relative, base, staging)
        for relative in publish_relatives
    ]
    validate_blocked_terms(staged_paths)
    for relative in manifest.get("chart_pngs", []):
        source = base / relative
        validate_png_file(source, "grafico")
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return staging


def data_manifest_payload(manifest: dict[str, object], data_version: str | None = None) -> dict[str, object]:
    chart_paths = manifest.get("chart_pngs", [])
    individual: dict[str, dict[str, str]] = {}
    comparison: dict[str, str] = {}
    for relative in chart_paths:
        path = Path(str(relative))
        parts = path.parts
        if len(parts) == 4 and parts[0] == "charts" and parts[1] == "individual":
            ticker = parts[2]
            key = path.stem
            individual.setdefault(ticker, {})[key] = Path(*parts).as_posix()
        if len(parts) == 3 and parts[0] == "charts" and parts[1] == "comparison":
            comparison[path.stem] = Path(*parts).as_posix()
    files = {
            "balanco": next((name for name in manifest["root_jsons"] if name.startswith("balancos_itr_cvm_")), ""),
            "dre": "DRE_ITR_CVM_ultimos_5_anos.json",
            "dfc": "DFC_ITR_CVM.json",
            "divida_liquida": "divida_liquida.json",
            "ciclo_financeiro": "ciclo_financeiro.json",
            "market_cap": "market_cap.json",
            "market_cap_historico": "market_cap_historico.json",
            "indicadores": "indicadores.json",
            "reconciliacao": "relatorio_reconciliacao.json",
    }
    if manifest.get("manual_operational_overrides"):
        files["manual_operational_overrides"] = MANUAL_OVERRIDES_FILENAME
    return {
        "files": files,
        "operational_jsons": manifest["operational_jsons"],
        "charts": {
            "individual": individual,
            "comparison": comparison,
        },
        "data_version": data_version if data_version is not None else os.environ.get("SOURCE_COMMIT") or os.environ.get("GITHUB_SHA") or "",
    }


def merge_data_manifest(previous: dict[str, object] | None, current: dict[str, object], scope: str) -> dict[str, object]:
    if not previous:
        return current
    if scope == "all":
        merged = dict(current)
        if isinstance(previous.get("files"), dict) and previous["files"].get("manual_operational_overrides"):
            files = dict(merged.get("files") or {})
            files.setdefault("manual_operational_overrides", previous["files"]["manual_operational_overrides"])
            merged["files"] = files
        return merged
    merged = dict(previous)
    merged["data_version"] = current.get("data_version", previous.get("data_version", ""))
    if scope == "financial":
        merged["files"] = current.get("files", previous.get("files", {}))
        if isinstance(previous.get("files"), dict) and previous["files"].get("manual_operational_overrides"):
            merged["files"]["manual_operational_overrides"] = previous["files"]["manual_operational_overrides"]
        merged["charts"] = current.get("charts", previous.get("charts", {}))
        merged["operational_jsons"] = previous.get("operational_jsons", [])
    elif scope == "operational":
        previous_files = previous.get("files", {})
        merged["files"] = dict(previous_files) if isinstance(previous_files, dict) else {}
        current_files = current.get("files", {})
        if isinstance(current_files, dict) and current_files.get("manual_operational_overrides"):
            merged["files"]["manual_operational_overrides"] = current_files["manual_operational_overrides"]
        merged["charts"] = previous.get("charts", {})
        previous_operational = previous.get("operational_jsons", []) if isinstance(previous.get("operational_jsons"), list) else []
        current_operational = current.get("operational_jsons", []) if isinstance(current.get("operational_jsons"), list) else []
        merged["operational_jsons"] = list(dict.fromkeys((*previous_operational, *current_operational)))
    return merged


def read_existing_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def resolve_manual_for_publication(manual_payload: dict[str, object], staging: Path, manifest: dict[str, object]) -> dict[str, object]:
    companies: dict[str, object] = {}
    for relative in manifest.get("operational_jsons", []):
        payload = read_json(staging / relative)
        if isinstance(payload, dict):
            ticker = str(payload.get("ticker") or "").upper()
            if ticker:
                companies[ticker] = payload
    _operational, resolved_manual = resolve_operational_data_with_manual({"companies": companies}, manual_payload)
    return normalize_manual_payload(resolved_manual)


def build_publish_manifest(base: Path, scope: str = "all", sector: str = "saude") -> dict[str, object]:
    scope = validate_scope(scope)
    sector = validate_sector(sector)
    base = base.resolve()
    if sector != "all":
        base = resolve_sector_results_dir(base, sector)
    financial_paths: list[Path] = []
    if scope in {"all", "financial"}:
        manifest = read_json_if_exists(base / "data_manifest.json")
        try:
            financial_paths.append(find_financial_statement_json(base, "balanco", manifest))
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
        financial_paths.extend(base / name for name in REQUIRED_ROOT_JSONS)

        for path in financial_paths:
            validate_json_file(path, "financeiro obrigatorio")

    op_dir = base / "dados_operacionais"
    allowed_operational_names = {f"{company.ticker}.json" for company in operational_companies(sector)}
    operational_jsons = sorted(
        path for path in op_dir.iterdir() if path.is_file() and path.name in allowed_operational_names
    ) if scope in {"all", "operational"} and op_dir.exists() else []
    for path in operational_jsons:
        validate_json_file(path, "operacional")
    manual_path = base / MANUAL_OVERRIDES_FILENAME
    manual_exists = manual_path.exists()
    if manual_exists:
        validate_json_file(manual_path, "override operacional manual")
    if scope == "operational" and not operational_jsons and not manual_exists:
        raise SystemExit("Nenhum JSON operacional foi gerado.")

    chart_dir = base / "charts"
    chart_pngs = sorted(chart_dir.rglob("*.png")) if scope in {"all", "financial"} and chart_dir.exists() else []
    chart_pngs = [
        path for path in chart_pngs
        if (
            path.relative_to(base).as_posix().startswith("charts/individual/")
            or path.relative_to(base).as_posix().startswith("charts/comparison/")
        )
        and path.name != "ev_ebitda_ltm.png"
    ]
    for path in chart_pngs:
        validate_png_file(path, "grafico")

    manifest = {
        "root_jsons": [path.relative_to(base).as_posix() for path in financial_paths],
        "operational_jsons": [path.relative_to(base).as_posix() for path in operational_jsons],
        "manual_operational_overrides": manual_exists,
        "chart_pngs": [path.relative_to(base).as_posix() for path in chart_pngs],
        "scope": scope,
        "sector": sector,
        "warnings": [] if operational_jsons or scope == "financial" else [
            "Nenhum JSON operacional novo validado; snapshot operacional anterior sera preservado."
        ],
    }
    (base / "publish_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (base / "data_manifest.json").write_text(
        json.dumps(data_manifest_payload(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    build_publication_staging(base, manifest)
    return manifest


def validate_results(base: Path, scope: str = "all", sector: str = "saude") -> dict[str, object]:
    if validate_sector(sector) == "all":
        health = validate_results(base, scope=scope, sector="saude")
        construction = validate_results(base, scope="financial" if scope != "operational" else "operational", sector="construcao_civil") if scope != "operational" else None
        return {"sector": "all", "scope": scope, "sectors": {"saude": health, **({"construcao_civil": construction} if construction else {})}}
    manifest = build_publish_manifest(base, scope, sector)
    print(
        "Validacao concluida: "
        f"{len(manifest['root_jsons'])} JSONs financeiros validos; "
        f"{len(manifest['operational_jsons'])} JSONs operacionais validos."
    )
    return manifest


def clear_financial_component(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.name in {"dados_operacionais", MANUAL_OVERRIDES_FILENAME}:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def publish_validated_data(
    source: Path,
    target: Path,
    source_commit: str = "",
    workflow_run_id: str = "",
    scope: str = "all",
    sector: str = "saude",
) -> dict[str, object]:
    if validate_sector(sector) == "all":
        health = publish_validated_data(source, target, source_commit, workflow_run_id, scope, "saude")
        construction = None
        if scope != "operational":
            construction = publish_validated_data(source, target, source_commit, workflow_run_id, "financial", "construcao_civil")
        return {"sector": "all", "scope": scope, "status": "success", "sectors": {"saude": health, **({"construcao_civil": construction} if construction else {})}}
    scope = validate_scope(scope)
    sector = validate_sector(sector)
    source = source.resolve()
    publication_root = target.resolve()
    if publication_root.name != "data":
        raise SystemExit(f"Destino de publicacao inesperado: {publication_root}")
    sector_layout = sector != "all" and (source / sector).is_dir()
    if sector_layout:
        source = source / sector
    target = publication_root / "sectors" / sector if sector_layout else publication_root

    manifest = read_json(source / "publish_manifest.json")
    manifest_scope = str(manifest.get("scope") or scope)
    if manifest_scope != scope:
        raise SystemExit(f"Scope do manifest ({manifest_scope}) difere do publish ({scope})")
    data_version = source_commit or os.environ.get("SOURCE_COMMIT") or os.environ.get("GITHUB_SHA") or ""
    data_manifest_path = source / "data_manifest.json"
    data_manifest_path.write_text(
        json.dumps(data_manifest_payload(manifest, data_version), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staging = build_publication_staging(source, manifest)
    current_manifest = read_json(staging / "data_manifest.json")
    previous_manifest = read_existing_json(target / "data_manifest.json")
    previous_metadata = read_existing_json(target / "update_metadata.json") or {}
    previous_manual = read_existing_json(target / MANUAL_OVERRIDES_FILENAME)
    staged_manifest = merge_data_manifest(previous_manifest, current_manifest, scope)
    target.mkdir(parents=True, exist_ok=True)
    if scope in {"all", "financial"}:
        clear_financial_component(target)
        chart_target = (publication_root.parent / "charts" / sector) if sector_layout else target.parent / "charts"
        if chart_target.exists():
            shutil.rmtree(chart_target)
        chart_target.mkdir(parents=True, exist_ok=True)

    copied = 0
    if scope in {"all", "financial"}:
        for relative in manifest["root_jsons"]:
            path = staging / relative
            shutil.copy2(path, target / path.name)
            copied += 1

    (target / "data_manifest.json").write_text(
        json.dumps(staged_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    copied += 1

    target_operational = target / "dados_operacionais"
    financial_updated = scope in {"all", "financial"} and bool(manifest["root_jsons"])
    operational_updated = scope in {"all", "operational"} and bool(manifest["operational_jsons"])
    if scope in {"all", "operational"} and operational_updated:
        target_operational.mkdir(parents=True, exist_ok=True)
        for relative in manifest["operational_jsons"]:
            path = staging / relative
            shutil.copy2(path, target_operational / path.name)
            copied += 1

    manual_source = staging / MANUAL_OVERRIDES_FILENAME
    manual_updated = bool(manifest.get("manual_operational_overrides")) and manual_source.exists()
    if manual_updated:
        manual_payload = read_json(manual_source)
        if scope in {"all", "operational"}:
            manual_payload = resolve_manual_for_publication(manual_payload, staging, manifest)
            manual_source.write_text(json.dumps(manual_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(manual_source, target / MANUAL_OVERRIDES_FILENAME)
        staged_manifest.setdefault("files", {})["manual_operational_overrides"] = MANUAL_OVERRIDES_FILENAME
        copied += 1
    elif previous_manual:
        manual_payload = previous_manual
        if scope in {"all", "operational"}:
            manual_payload = resolve_manual_for_publication(previous_manual, staging, manifest)
        (target / MANUAL_OVERRIDES_FILENAME).write_text(
            json.dumps(manual_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        staged_manifest.setdefault("files", {})["manual_operational_overrides"] = MANUAL_OVERRIDES_FILENAME
        copied += 1

    (target / "data_manifest.json").write_text(
        json.dumps(staged_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    now = datetime.now(timezone.utc).isoformat()
    previous_components = previous_metadata.get("components") if isinstance(previous_metadata.get("components"), dict) else {}

    def component_metadata(name: str, updated: bool, skipped_status: str = "skipped_by_scope") -> dict[str, object]:
        previous = previous_components.get(name) if isinstance(previous_components, dict) else None
        if not isinstance(previous, dict):
            previous = {}
        if updated:
            return {
                "last_update": now,
                "mode": os.environ.get("UPDATE_MODE", ""),
                "status": "success",
                "updated": True,
            }
        preserved = dict(previous)
        preserved.setdefault("last_update", None)
        preserved.setdefault("mode", "")
        preserved["status"] = skipped_status
        preserved["updated"] = False
        return preserved

    financial_skipped_status = "skipped_by_scope" if scope == "operational" else "skipped_no_change"
    operational_skipped_status = "skipped_by_scope" if scope == "financial" else "skipped_no_change"

    metadata = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_update": now,
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
        "scope": scope,
        "sector": sector,
        "mode": os.environ.get("UPDATE_MODE", ""),
        "status": "success_with_warnings" if manifest.get("warnings") else "success",
        "warnings": manifest.get("warnings", []),
        "components": {
            "financial": component_metadata("financial", financial_updated, financial_skipped_status),
            "operational": component_metadata("operational", operational_updated, operational_skipped_status),
        },
        "json_files_published": copied,
        "chart_pngs_published": 0,
        "files": staged_manifest["files"],
        "operational_jsons": manifest["operational_jsons"],
        "charts": staged_manifest.get("charts", {}),
        "data_version": staged_manifest.get("data_version", data_version),
    }
    chart_copied = 0
    if scope in {"all", "financial"}:
        for relative in manifest.get("chart_pngs", []):
            source_path = staging / relative
            if not source_path.exists():
                continue
            rel_path = Path(relative)
            target_path = ((publication_root.parent / "charts" / sector / Path(*rel_path.parts[1:])) if sector_layout else target.parent / rel_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            chart_copied += 1
    metadata["chart_pngs_published"] = chart_copied
    (target / "update_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if sector_layout:
        root_manifest = read_existing_json(publication_root / "data_manifest.json") or {"schema_version": 2, "sectors": {}}
        if root_manifest.get("schema_version") != 2:
            root_manifest = {"schema_version": 2, "sectors": {"saude": root_manifest}}
        root_manifest.setdefault("sectors", {})[sector] = staged_manifest
        root_manifest["schema_version"] = 2
        root_manifest["data_version"] = data_version
        (publication_root / "data_manifest.json").write_text(json.dumps(root_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        root_metadata = read_existing_json(publication_root / "update_metadata.json") or {"sectors": {}}
        root_metadata.setdefault("sectors", {}).setdefault(sector, {})["components"] = metadata["components"]
        root_metadata["updated_at_utc"] = now
        root_metadata["source_commit"] = source_commit
        root_metadata["workflow_run_id"] = workflow_run_id
        (publication_root / "update_metadata.json").write_text(json.dumps(root_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Publicacao preparada: {copied} JSONs copiados para data/ e {chart_copied} PNGs para charts/.")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("source", type=Path)
    validate.add_argument("--scope", choices=tuple(sorted(PUBLICATION_SCOPES)), default="all")
    validate.add_argument("--sector", choices=tuple(sorted(SECTORS)), default="saude")

    publish = subparsers.add_parser("publish")
    publish.add_argument("source", type=Path)
    publish.add_argument("target", type=Path)
    publish.add_argument("--scope", choices=tuple(sorted(PUBLICATION_SCOPES)), default="all")
    publish.add_argument("--sector", choices=tuple(sorted(SECTORS)), default="saude")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate":
        validate_results(args.source, scope=args.scope, sector=args.sector)
        return 0
    if args.command == "publish":
        publish_validated_data(
            args.source,
            args.target,
            source_commit=os.environ.get("SOURCE_COMMIT", ""),
            workflow_run_id=os.environ.get("WORKFLOW_RUN_ID", ""),
            scope=args.scope,
            sector=args.sector,
        )
        return 0
    raise SystemExit(f"Comando desconhecido: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

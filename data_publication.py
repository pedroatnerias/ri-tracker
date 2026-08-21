#!/usr/bin/env python3
"""Validacao e publicacao dos JSONs finais no repositorio de dados."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

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


def build_publication_staging(base: Path, manifest: dict[str, object]) -> Path:
    staging = publication_staging_dir(base)
    reset_staging(staging)
    publish_relatives = list(manifest["root_jsons"]) + list(manifest["operational_jsons"])
    staged_paths = [
        write_sanitized_copy(base / relative, base, staging)
        for relative in publish_relatives
    ]
    validate_blocked_terms(staged_paths)
    return staging


def build_publish_manifest(base: Path) -> dict[str, object]:
    base = base.resolve()
    financial_paths: list[Path] = []
    balancos = sorted(base.glob("balancos_itr_cvm_*.json"), key=lambda p: p.stat().st_mtime)
    if not balancos:
        raise SystemExit("Nenhum balancos_itr_cvm_*.json foi gerado.")
    financial_paths.append(balancos[-1])
    financial_paths.extend(base / name for name in REQUIRED_ROOT_JSONS)

    for path in financial_paths:
        validate_json_file(path, "financeiro obrigatorio")

    op_dir = base / "dados_operacionais"
    operational_jsons = sorted(op_dir.glob("*.json")) if op_dir.exists() else []
    for path in operational_jsons:
        validate_json_file(path, "operacional")

    manifest = {
        "root_jsons": [path.relative_to(base).as_posix() for path in financial_paths],
        "operational_jsons": [path.relative_to(base).as_posix() for path in operational_jsons],
        "warnings": [] if operational_jsons else [
            "Nenhum JSON operacional novo validado; snapshot operacional anterior sera preservado."
        ],
    }
    (base / "publish_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    build_publication_staging(base, manifest)
    return manifest


def validate_results(base: Path) -> dict[str, object]:
    manifest = build_publish_manifest(base)
    print(
        "Validacao concluida: "
        f"{len(manifest['root_jsons'])} JSONs financeiros validos; "
        f"{len(manifest['operational_jsons'])} JSONs operacionais validos."
    )
    return manifest


def clear_financial_component(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.name == "dados_operacionais":
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
) -> dict[str, object]:
    source = source.resolve()
    target = target.resolve()
    if target.name != "data":
        raise SystemExit(f"Destino de publicacao inesperado: {target}")

    manifest = read_json(source / "publish_manifest.json")
    staging = publication_staging_dir(source)
    if not staging.exists():
        build_publication_staging(source, manifest)
    clear_financial_component(target)

    copied = 0
    for relative in manifest["root_jsons"]:
        path = staging / relative
        shutil.copy2(path, target / path.name)
        copied += 1

    target_operational = target / "dados_operacionais"
    operational_updated = bool(manifest["operational_jsons"])
    if operational_updated:
        if target_operational.exists():
            shutil.rmtree(target_operational)
        target_operational.mkdir(parents=True, exist_ok=True)
        for relative in manifest["operational_jsons"]:
            path = staging / relative
            shutil.copy2(path, target_operational / path.name)
            copied += 1

    metadata = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
        "status": "success" if operational_updated else "success_with_warnings",
        "warnings": manifest.get("warnings", []),
        "components": {
            "financial": {
                "status": "success",
                "updated": True,
            },
            "operational": {
                "status": "success" if operational_updated else "skipped",
                "updated": operational_updated,
            },
        },
        "json_files_published": copied,
    }
    (target / "update_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Publicacao preparada: {copied} JSONs copiados para data/.")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("source", type=Path)

    publish = subparsers.add_parser("publish")
    publish.add_argument("source", type=Path)
    publish.add_argument("target", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate":
        validate_results(args.source)
        return 0
    if args.command == "publish":
        publish_validated_data(
            args.source,
            args.target,
            source_commit=os.environ.get("SOURCE_COMMIT", ""),
            workflow_run_id=os.environ.get("WORKFLOW_RUN_ID", ""),
        )
        return 0
    raise SystemExit(f"Comando desconhecido: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

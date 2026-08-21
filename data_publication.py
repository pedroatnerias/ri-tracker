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


def build_publication_staging(base: Path, manifest: dict[str, object]) -> Path:
    staging = publication_staging_dir(base)
    reset_staging(staging)
    publish_relatives = list(manifest["root_jsons"]) + list(manifest["operational_jsons"]) + ["data_manifest.json"]
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
    return {
        "files": {
            "balanco": next((name for name in manifest["root_jsons"] if name.startswith("balancos_itr_cvm_")), ""),
            "dre": "DRE_ITR_CVM_ultimos_5_anos.json",
            "dfc": "DFC_ITR_CVM.json",
            "divida_liquida": "divida_liquida.json",
            "ciclo_financeiro": "ciclo_financeiro.json",
            "market_cap": "market_cap.json",
            "market_cap_historico": "market_cap_historico.json",
            "indicadores": "indicadores.json",
            "reconciliacao": "relatorio_reconciliacao.json",
        },
        "operational_jsons": manifest["operational_jsons"],
        "charts": {
            "individual": individual,
            "comparison": comparison,
        },
        "data_version": data_version if data_version is not None else os.environ.get("SOURCE_COMMIT") or os.environ.get("GITHUB_SHA") or "",
    }


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

    chart_dir = base / "charts"
    chart_pngs = sorted(chart_dir.rglob("*.png")) if chart_dir.exists() else []
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
        "chart_pngs": [path.relative_to(base).as_posix() for path in chart_pngs],
        "warnings": [] if operational_jsons else [
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
    data_version = source_commit or os.environ.get("SOURCE_COMMIT") or os.environ.get("GITHUB_SHA") or ""
    data_manifest_path = source / "data_manifest.json"
    data_manifest_path.write_text(
        json.dumps(data_manifest_payload(manifest, data_version), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staging = build_publication_staging(source, manifest)
    staged_manifest = read_json(staging / "data_manifest.json")
    clear_financial_component(target)
    chart_target = target.parent / "charts"
    if chart_target.exists():
        shutil.rmtree(chart_target)
    chart_target.mkdir(parents=True, exist_ok=True)

    copied = 0
    for relative in manifest["root_jsons"]:
        path = staging / relative
        shutil.copy2(path, target / path.name)
        copied += 1

    shutil.copy2(staging / "data_manifest.json", target / "data_manifest.json")
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
        "chart_pngs_published": 0,
        "files": staged_manifest["files"],
        "operational_jsons": manifest["operational_jsons"],
        "charts": staged_manifest.get("charts", {}),
        "data_version": staged_manifest.get("data_version", data_version),
    }
    chart_copied = 0
    for relative in manifest.get("chart_pngs", []):
        source_path = staging / relative
        if not source_path.exists():
            continue
        target_path = target.parent / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        chart_copied += 1
    metadata["chart_pngs_published"] = chart_copied
    (target / "update_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Publicacao preparada: {copied} JSONs copiados para data/ e {chart_copied} PNGs para charts/.")
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

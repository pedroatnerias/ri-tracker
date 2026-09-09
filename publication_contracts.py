"""Contratos puros de manifesto para a publicação setorial."""

from __future__ import annotations

from pathlib import Path


def data_manifest_payload(manifest: dict[str, object], data_version: str = "", *, manual_filename: str) -> dict[str, object]:
    chart_paths = manifest.get("chart_pngs", [])
    individual: dict[str, dict[str, str]] = {}
    comparison: dict[str, str] = {}
    for relative in chart_paths:
        path = Path(str(relative))
        parts = path.parts
        if len(parts) == 4 and parts[0] == "charts" and parts[1] == "individual":
            individual.setdefault(parts[2], {})[path.stem] = path.as_posix()
        if len(parts) == 3 and parts[0] == "charts" and parts[1] == "comparison":
            comparison[path.stem] = path.as_posix()
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
        files["manual_operational_overrides"] = manual_filename
    payload = {
        "files": files,
        "operational_jsons": manifest["operational_jsons"],
        "charts": {"individual": individual, "comparison": comparison},
        "data_version": data_version,
    }
    if isinstance(manifest.get("tracking_summary"), dict):
        payload["tracking"] = manifest["tracking_summary"]
    return payload


def merge_data_manifest(previous: dict[str, object] | None, current: dict[str, object], scope: str, *, manual_filename: str) -> dict[str, object]:
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
            merged["files"] = dict(merged["files"])
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
        old = previous.get("operational_jsons", []) if isinstance(previous.get("operational_jsons"), list) else []
        new = current.get("operational_jsons", []) if isinstance(current.get("operational_jsons"), list) else []
        merged["operational_jsons"] = list(dict.fromkeys((*old, *new)))
    return merged

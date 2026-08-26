#!/usr/bin/env python3
"""Dashboard Flask para BP, DRE, DFC e indicadores a partir dos JSONs locais."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import platform
import subprocess
import sys
import threading
import traceback
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, request, send_from_directory
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from manual_operational import (
    MANUAL_OVERRIDES_FILENAME,
    delete_manual_override,
    empty_manual_payload,
    load_manual_overrides_file,
    load_remote_manual_overrides,
    manual_admin_token_configured,
    normalize_manual_payload,
    resolve_operational_data_with_manual,
    save_remote_manual_overrides,
    upsert_manual_override,
    validate_manual_record,
    write_manual_overrides_file,
)
from operational_dictionary import TARGET_METRICS
from company_registry import SECTOR_LABELS, financial_companies, operational_companies, tickers_for_sector, validate_sector


TICKERS = ("AALR3", "DASA3", "FLRY3", "HAPV3", "MATD3", "ONCO3", "RDOR3")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8050
UPDATE_MODES = {"incremental", "full"}
UPDATE_SCOPES = {"all", "financial", "operational"}
DATA_SOURCE_MODES = {"local", "remote", "auto"}
DEFAULT_REMOTE_DATA_BASE_URL = "https://raw.githubusercontent.com/pedroatnerias/ri-tracker-data/main/data"
DEFAULT_REMOTE_CACHE_TTL_SECONDS = 600
REMOTE_HTTP_TIMEOUT_SECONDS = 15
REMOTE_CACHE: dict[str, dict[str, object]] = {}
REMOTE_CACHE_LOCK = threading.Lock()
DEFAULT_DATA_REPO = "pedroatnerias/ri-tracker-data"
DEFAULT_DATA_REPO_BRANCH = "main"


def resolve_app_path(path: Path) -> Path:
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (BASE_DIR / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anos", nargs="+", type=int, help="Anos a passar para os apps da CVM.")
    parser.add_argument("--resultados", type=Path, default=Path("resultados"), help="Pasta dos JSONs.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--atualizar", action="store_true", help="Roda os apps antes de iniciar o servidor.")
    parser.add_argument("--update-scope", choices=tuple(sorted(UPDATE_SCOPES)), default="all", help="Escopo usado com --atualizar.")
    parser.add_argument("--update-sector", choices=("saude", "construcao_civil", "all"), default="saude", help="Setor usado com --atualizar.")
    parser.add_argument("--sector", choices=("saude", "construcao_civil"), default="saude", help="Setor usado na exportacao HTML.")
    parser.add_argument("--update-mode", choices=tuple(sorted(UPDATE_MODES)), default="full", help="Modo usado com --atualizar.")
    parser.add_argument("--export-html", type=Path, help="Exporta uma versao HTML estatica e encerra.")
    parser.add_argument(
        "--nao-liberar-porta",
        action="store_true",
        help="nao encerra processos antigos na mesma porta antes de iniciar",
    )
    args = parser.parse_args()
    if args.port is None:
        args.port = env_port(DEFAULT_PORT)
    return args


def env_port(default: int) -> int:
    port_text = os.getenv("PORT")
    if not port_text:
        return default
    try:
        return int(port_text)
    except ValueError:
        return default


def script_path(filename: str) -> str:
    return str(BASE_DIR / filename)


class RemoteDataError(RuntimeError):
    pass


def configured_data_source_mode() -> str:
    mode = os.getenv("NERIAS_DATA_SOURCE", "auto").strip().lower()
    return mode if mode in DATA_SOURCE_MODES else "auto"


def remote_data_base_url() -> str:
    return os.getenv("NERIAS_REMOTE_DATA_BASE_URL", DEFAULT_REMOTE_DATA_BASE_URL).rstrip("/")


def remote_cache_ttl_seconds() -> int:
    value = os.getenv("NERIAS_REMOTE_CACHE_TTL_SECONDS")
    if not value:
        return DEFAULT_REMOTE_CACHE_TTL_SECONDS
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_REMOTE_CACHE_TTL_SECONDS


def validate_remote_relative_path(relative_path: str) -> str:
    normalized = str(relative_path).replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Caminho remoto invalido: {relative_path}")
    if not parts[-1].endswith(".json"):
        raise ValueError(f"Apenas JSON remoto e permitido: {relative_path}")
    return "/".join(parts)


def validate_remote_asset_path(relative_path: str, suffixes: tuple[str, ...]) -> str:
    normalized = str(relative_path).replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Caminho remoto invalido: {relative_path}")
    if not parts[-1].endswith(suffixes):
        raise ValueError(f"Extensao remota nao permitida: {relative_path}")
    return "/".join(parts)


def remote_url_for(relative_path: str) -> str:
    safe_path = validate_remote_relative_path(relative_path)
    encoded = "/".join(quote(part) for part in safe_path.split("/"))
    return f"{remote_data_base_url()}/{encoded}"


def remote_repository_base_url() -> str:
    base = remote_data_base_url()
    return base.rsplit("/data", 1)[0] if base.endswith("/data") else base


def remote_asset_url_for(relative_path: str) -> str:
    safe_path = validate_remote_asset_path(relative_path, (".png", ".json"))
    encoded = "/".join(quote(part) for part in safe_path.split("/"))
    return f"{remote_repository_base_url()}/{encoded}"


def remote_http_get_json(relative_path: str) -> dict:
    url = remote_url_for(relative_path)
    request = Request(url, headers={"User-Agent": "Nerias-RI-Tracker/1.0"})
    try:
        with urlopen(request, timeout=REMOTE_HTTP_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:
        raise RemoteDataError(f"Falha ao carregar JSON remoto: {relative_path}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RemoteDataError(f"JSON remoto invalido: {relative_path}") from exc
    if not isinstance(data, dict):
        raise RemoteDataError(f"JSON remoto sem objeto raiz: {relative_path}")
    return data


def clear_remote_cache() -> None:
    with REMOTE_CACHE_LOCK:
        REMOTE_CACHE.clear()


def cached_remote_json(relative_path: str, force_refresh: bool = False) -> tuple[dict | None, dict]:
    safe_path = validate_remote_relative_path(relative_path)
    now = time.time()
    ttl = remote_cache_ttl_seconds()
    with REMOTE_CACHE_LOCK:
        cached = REMOTE_CACHE.get(safe_path)
        if cached and not force_refresh and now - float(cached["fetched_at"]) <= ttl:
            return cached["data"], {
                "path": remote_url_for(safe_path),
                "modified_at": cached["fetched_at"],
                "exists": True,
                "source": "remote_cache",
                "warning": None,
            }
    try:
        data = remote_http_get_json(safe_path)
    except Exception as exc:
        with REMOTE_CACHE_LOCK:
            cached = REMOTE_CACHE.get(safe_path)
        if cached:
            return cached["data"], {
                "path": remote_url_for(safe_path),
                "modified_at": cached["fetched_at"],
                "exists": True,
                "source": "remote_cache_stale",
                "warning": str(exc),
            }
        return None, {
            "path": remote_url_for(safe_path),
            "modified_at": None,
            "exists": False,
            "source": "remote",
            "warning": str(exc),
        }

    meta = {
        "path": remote_url_for(safe_path),
        "modified_at": now,
        "exists": True,
        "source": "remote",
        "warning": None,
    }
    with REMOTE_CACHE_LOCK:
        REMOTE_CACHE[safe_path] = {"data": data, "fetched_at": now, "source": "remote"}
    return data, meta


class DashboardDataSource:
    def __init__(self, resultados: Path, mode: str | None = None, force_remote_refresh: bool = False, sector: str = "saude"):
        requested = (mode or configured_data_source_mode()).strip().lower()
        self.mode = requested if requested in DATA_SOURCE_MODES else "auto"
        self.resultados = resultados
        self.sector = validate_sector(sector)
        self.force_remote_refresh = force_remote_refresh
        self.files: dict[str, dict] = {}
        self.remote_metadata: dict = {}
        self.data_source = self.mode
        self.remote_available = False
        self._remote_manifest: dict = {}
        self.manifest_v2 = False
        if self.mode in {"remote", "auto"}:
            self._load_remote_metadata()

    def _load_remote_metadata(self) -> None:
        metadata, meta = cached_remote_json("update_metadata.json", self.force_remote_refresh)
        manifest, manifest_meta = cached_remote_json("data_manifest.json", self.force_remote_refresh)
        self.files["update_metadata"] = meta
        self.files["data_manifest"] = manifest_meta
        if metadata:
            self.remote_metadata = metadata
        if manifest:
            self._remote_manifest = manifest
        self.manifest_v2 = self._remote_manifest.get("schema_version") == 2 and isinstance(self._remote_manifest.get("sectors"), dict)
        if isinstance(self._remote_manifest.get("sectors"), dict):
            self._remote_manifest = dict(self._remote_manifest["sectors"].get(self.sector) or {}) | {"data_version": self._remote_manifest.get("data_version", "")}
        if isinstance(self.remote_metadata.get("sectors"), dict):
            self.remote_metadata = dict(self.remote_metadata["sectors"].get(self.sector) or {}) | {"data_version": self.remote_metadata.get("data_version", "")}
        self.remote_available = bool(metadata or manifest)

    def remote_file_map(self) -> dict:
        files = {}
        if isinstance(self.remote_metadata.get("files"), dict):
            files.update(self.remote_metadata["files"])
        if isinstance(self._remote_manifest.get("files"), dict):
            files.update({key: value for key, value in self._remote_manifest["files"].items() if value})
        return files

    def chart_manifest(self) -> dict:
        charts = {}
        if isinstance(self.remote_metadata.get("charts"), dict):
            charts.update(self.remote_metadata["charts"])
        if isinstance(self._remote_manifest.get("charts"), dict):
            charts.update(self._remote_manifest["charts"])
        return charts

    def data_version(self) -> str:
        return str(
            self.remote_metadata.get("data_version")
            or self._remote_manifest.get("data_version")
            or self.remote_metadata.get("source_commit")
            or self.remote_metadata.get("updated_at_utc")
            or ""
        )

    def operational_paths(self) -> list[str]:
        paths = self.remote_metadata.get("operational_jsons")
        if not isinstance(paths, list):
            paths = self._remote_manifest.get("operational_jsons")
        return [validate_remote_relative_path(path) for path in (paths or []) if isinstance(path, str)]

    def manual_operational_path(self) -> str | None:
        files = self.remote_file_map()
        path = files.get("manual_operational_overrides")
        if isinstance(path, str) and path:
            return validate_remote_relative_path(path)
        return None

    def load_remote_optional(self, relative_path: str, key: str | None = None) -> dict | None:
        if self.manifest_v2:
            if not relative_path.startswith("sectors/"):
                relative_path = f"sectors/{self.sector}/{relative_path}"
        data, meta = cached_remote_json(relative_path, self.force_remote_refresh)
        self.files[key or relative_path] = meta
        if data is None:
            return None
        self.data_source = meta.get("source") or "remote"
        return data

    def load_local_optional(self, path: Path | None, key: str | None = None, expected_path: Path | None = None) -> dict | None:
        meta_key = key or str(path or expected_path or "")
        self.files[meta_key] = file_metadata(path, expected_path)
        if path is None or not path.exists():
            return None
        self.data_source = "local"
        return load_json(path)

    def load_optional(self, key: str, local_path: Path | None, remote_relative: str | None, expected_path: Path | None = None) -> dict | None:
        if self.mode in {"remote", "auto"} and remote_relative:
            data = self.load_remote_optional(remote_relative, key)
            if data is not None:
                return data
            if self.mode == "remote":
                return None
        if self.mode in {"local", "auto"}:
            return self.load_local_optional(local_path, key, expected_path)
        return None


def sanitize_log_message(message: str) -> str:
    base = str(BASE_DIR)
    parent = str(BASE_DIR.parent)
    return message.replace(base, "<BASE_DIR>").replace(parent, "<PROJECT_PARENT>")


def effective_update_years(anos: list[int] | None = None, quantidade: int = 5) -> list[int]:
    """Janela movel usada para atualizar todos os arquivos dependentes da CVM."""
    if anos:
        return sorted(set(anos))
    ano_atual = datetime.now().year
    return list(range(ano_atual - quantidade + 1, ano_atual + 1))


def validate_update_mode(mode: str) -> str:
    normalized = (mode or "incremental").lower()
    if normalized not in UPDATE_MODES:
        raise ValueError(f"Modo de atualizacao invalido: {mode}")
    return normalized


def validate_update_scope(scope: str) -> str:
    normalized = (scope or "all").lower()
    if normalized not in UPDATE_SCOPES:
        raise ValueError(f"Escopo de atualizacao invalido: {scope}")
    return normalized


def run_command(command: list[str]) -> None:
    print("Rodando:", " ".join(command))
    subprocess.run(command, cwd=BASE_DIR, check=True)


UPDATE_STATE: dict[str, object] = {
    "running": False,
    "status": "idle",
    "current_step": None,
    "scope": None,
    "sector": None,
    "mode": None,
    "started_at": None,
    "finished_at": None,
    "logs": [],
    "error": None,
}
UPDATE_LOCK = threading.Lock()


def append_update_log(message: str) -> None:
    message = sanitize_log_message(message)
    console_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    console_message = message.encode(console_encoding, errors="replace").decode(console_encoding, errors="replace")
    print(console_message, flush=True)
    with UPDATE_LOCK:
        logs = list(UPDATE_STATE.get("logs") or [])
        logs.append(message)
        UPDATE_STATE["logs"] = logs[-250:]


def run_update_command(label: str, command: list[str], critical: bool = True) -> dict[str, object]:
    append_update_log(f"Iniciando: {label}")
    with UPDATE_LOCK:
        UPDATE_STATE["current_step"] = label
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if output:
        append_update_log(output[-8000:])
    if result.returncode != 0:
        message = f"{label} falhou com codigo {result.returncode}"
        if critical:
            raise RuntimeError(message)
        append_update_log(f"[WARNING] {message}. O pipeline financeiro continuara.")
        return {
            "label": label,
            "status": "failed",
            "critical": critical,
            "returncode": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    append_update_log(f"Concluido: {label}")
    return {
        "label": label,
        "status": "ok",
        "critical": critical,
        "returncode": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def command_failed(result: dict[str, object] | None) -> bool:
    return bool(result and result.get("status") == "failed")


def run_update(
    resultados: Path,
    anos: list[int] | None = None,
    mode: str = "incremental",
    scope: str = "all",
    sector: str = "saude",
    diagnostico_ri: bool = False,
) -> dict[str, object]:
    mode = validate_update_mode(mode)
    scope = validate_update_scope(scope)
    sector = validate_sector(sector)
    if sector == "all":
        (resultados.expanduser().resolve() / "saude").mkdir(parents=True, exist_ok=True)
        results = []
        if scope in {"all", "financial", "operational"}:
            health_scope = scope
            results.append(run_update(resultados, anos, mode=mode, scope=health_scope, sector="saude", diagnostico_ri=diagnostico_ri))
        if scope in {"all", "financial"}:
            results.append(run_update(resultados, anos, mode=mode, scope="financial", sector="construcao_civil", diagnostico_ri=False))
        return {
            "status": "success_with_warnings" if any(r.get("warnings") for r in results) else "success",
            "warnings": [w for r in results for w in r.get("warnings", [])],
            "steps": [s for r in results for s in r.get("steps", [])],
            "scope": scope, "mode": mode, "sector": "all",
            "companies": {"financial": [c.ticker for c in financial_companies("all")] if scope != "operational" else [], "operational": [c.ticker for c in operational_companies("saude")] if scope != "financial" else []},
        }
    if sector == "construcao_civil" and scope == "operational":
        raise ValueError("O setor construcao_civil ainda não possui atualização operacional.")
    full_mode = mode == "full"
    full_suffix = " [FULL]" if full_mode else ""
    resultados = resultados.expanduser().resolve()
    # A raiz plana continua sendo aceita para saude; novos setores ficam isolados.
    if sector != "saude" or (resultados / "saude").exists():
        resultados = resultados / sector
    resultados.mkdir(parents=True, exist_ok=True)
    operational_dir = resultados / "dados_operacionais"
    dre_path = resultados / "DRE_ITR_CVM_ultimos_5_anos.json"
    dfc_path = resultados / "DFC_ITR_CVM.json"
    divida_path = resultados / "divida_liquida.json"
    ciclo_path = resultados / "ciclo_financeiro.json"
    market_path = resultados / "market_cap.json"
    market_hist_path = resultados / "market_cap_historico.json"
    indicadores_path = resultados / "indicadores.json"
    reconciliacao_path = resultados / "relatorio_reconciliacao.json"
    anos_efetivos = effective_update_years(anos)
    year_args = [str(ano) for ano in anos_efetivos]
    step_results: list[dict[str, object]] = []
    warnings: list[str] = []
    started_total = time.monotonic()
    run_financial = scope in {"all", "financial"}
    run_operational = scope in {"all", "operational"} and sector in {"saude", "all"}
    selected_financial = [c.ticker for c in financial_companies(sector)] if run_financial else []
    selected_operational = [c.ticker for c in operational_companies(sector)] if run_operational else []
    if sector == "construcao_civil" and scope == "all":
        warnings.append("Componente operacional ignorado: não habilitado para construcao_civil.")
    if run_operational:
        operational_dir.mkdir(parents=True, exist_ok=True)

    def skipped_step(label: str) -> dict[str, object]:
        append_update_log(f"[SKIP] {label} - scope={scope}")
        return {
            "label": label,
            "status": "skipped",
            "reason": "SKIPPED_BY_SCOPE",
            "scope": scope,
            "duration_seconds": 0,
        }

    append_update_log(f"Scope de atualizacao: {scope}")
    append_update_log(f"Setor de atualizacao: {sector}")
    append_update_log(f"Empresas financeiras: {', '.join(selected_financial) or '-'}")
    append_update_log(f"Empresas operacionais: {', '.join(selected_operational) or '-'}")
    append_update_log(f"Modo de atualizacao: {mode}")
    append_update_log(f"Anos da atualizacao CVM: {', '.join(year_args)}")

    balanco_path: Path | None = None
    if run_financial:
        balanco_cmd = [sys.executable, script_path("app_balancos.py"), "--output-dir", str(resultados), "--sector", sector]
        if year_args:
            balanco_cmd.extend(["--years", *year_args])
        if full_mode:
            balanco_cmd.append("--force-download")
        step_results.append(run_update_command(f"Balanço Patrimonial CVM{full_suffix}", balanco_cmd))
        balanco_path = find_balanco_json(resultados)

        shared_itr_cache = resultados / "downloads" / "itr"
        shared_dfp_cache = resultados / "downloads" / "dfp"
        dre_cmd = [sys.executable, script_path("app_dre.py"), "--saida", str(dre_path), "--sector", sector, "--pasta-zips", str(shared_itr_cache), "--pasta-zips-dfp", str(shared_dfp_cache)]
        if year_args:
            dre_cmd.extend(["--anos", *year_args])
        step_results.append(run_update_command(f"DRE CVM{full_suffix}", dre_cmd))

        dfc_cmd = [sys.executable, script_path("app_dfc.py"), "--diretorio", str(resultados), "--saida", str(dfc_path), "--sector", sector, "--pasta-zips", str(shared_itr_cache), "--pasta-zips-dfp", str(shared_dfp_cache)]
        if year_args:
            dfc_cmd.extend(["--anos", *year_args])
        step_results.append(run_update_command(f"DFC CVM{full_suffix}", dfc_cmd))
    else:
        step_results.extend([skipped_step("Balanço Patrimonial CVM"), skipped_step("DRE CVM"), skipped_step("DFC CVM")])

    if run_operational:
        parser_cmd = [sys.executable, script_path("app_parser_operacional.py")]
        if full_mode:
            parser_cmd.append("--sobrescrever-downloads")
        if diagnostico_ri:
            parser_cmd.append("--diagnostico-ri")
        parser_result = run_update_command(
            f"Releases e relatorios operacionais{full_suffix}",
            parser_cmd,
            critical=False,
        )
        step_results.append(parser_result)
        if command_failed(parser_result):
            warnings.append("Releases e relatorios operacionais falhou; Dados operacionais foi pulado.")
            skipped = {
                "label": "Dados operacionais",
                "status": "skipped",
                "critical": False,
                "reason": "parser operacional falhou nesta execucao",
                "duration_seconds": 0,
            }
            step_results.append(skipped)
            append_update_log("[SKIPPED] Dados operacionais. Motivo: parser operacional falhou nesta execucao.")
        else:
            extractor_result = run_update_command(
                "Dados operacionais",
                [sys.executable, script_path("app_extrator_operacional.py"), "--output-dir", str(operational_dir)],
                critical=False,
            )
            step_results.append(extractor_result)
            if command_failed(extractor_result):
                warnings.append("Dados operacionais falhou; pipeline continuou.")
    else:
        step_results.extend([skipped_step("Releases e relatorios operacionais"), skipped_step("Dados operacionais")])

    if run_financial:
        assert balanco_path is not None
        step_results.append(run_update_command("Divida liquida", [sys.executable, script_path("app_divida_liquida.py"), "calculate", str(balanco_path), "--output", str(divida_path)]))
        step_results.append(run_update_command("Ciclo financeiro", [sys.executable, script_path("app_ciclo_financeiro.py"), str(balanco_path), str(ciclo_path), "--dre", str(dre_path), "--sector", sector]))
        step_results.append(run_update_command("Market cap atual", [sys.executable, script_path("app_market_cap.py"), "--saida", str(market_path), "--sector", sector]))
        step_results.append(run_update_command("Market cap historico", [sys.executable, script_path("app_market_cap_historico.py"), "--saida", str(market_hist_path), "--sector", sector]))
        step_results.append(
            run_update_command(
                "Indicadores financeiros",
                [
                    sys.executable,
                    script_path("app_indicadores.py"),
                    str(dre_path),
                    str(indicadores_path),
                    "--dfc",
                    str(dfc_path),
                    "--market-cap-historico",
                    str(market_hist_path),
                    "--divida-liquida",
                    str(divida_path),
                    "--balanco",
                    str(balanco_path),
                ],
            )
        )
        step_results.append(
            run_update_command(
                "Relatorio de reconciliacao",
                [
                    sys.executable,
                    script_path("app_reconciliacao.py"),
                    "--indicadores",
                    str(indicadores_path),
                    "--divida-liquida",
                    str(divida_path),
                    "--saida",
                    str(reconciliacao_path),
                ],
            )
        )
    else:
        step_results.extend(
            [
                skipped_step("Divida liquida"),
                skipped_step("Ciclo financeiro"),
                skipped_step("Market cap atual"),
                skipped_step("Market cap historico"),
                skipped_step("Indicadores financeiros"),
                skipped_step("Relatorio de reconciliacao"),
            ]
        )

    global_status = "success_with_warnings" if warnings else "success"
    step_results = [step for step in step_results if step]
    for step in step_results:
        status = str(step.get("status", "ok")).upper()
        marker = "WARNING" if status == "FAILED" else status
        append_update_log(f"[{marker}] {step.get('label')}")
    if warnings:
        append_update_log("Pipeline concluido com avisos.")
    else:
        append_update_log("Pipeline concluido com sucesso.")
    append_update_log(f"TOTAL {round(time.monotonic() - started_total, 3)}s")
    return {"status": global_status, "warnings": warnings, "steps": step_results, "scope": scope, "mode": mode, "sector": sector, "companies": {"financial": selected_financial, "operational": selected_operational}}


def run_full_update(
    resultados: Path,
    anos: list[int] | None = None,
    diagnostico_ri: bool = False,
    scope: str = "all",
    sector: str = "saude",
) -> dict[str, object]:
    if sector == "saude":
        return run_update(resultados, anos, mode="full", scope=scope, diagnostico_ri=diagnostico_ri)
    return run_update(resultados, anos, mode="full", scope=scope, sector=sector, diagnostico_ri=diagnostico_ri)


def port_process_ids(port: int) -> set[int]:
    if platform.system() != "Windows":
        return set()
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()

    pids: set[int] = set()
    port_suffix = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[3].upper()
        pid_text = parts[-1]
        if state != "LISTENING" or not local_address.endswith(port_suffix):
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid != os.getpid():
            pids.add(pid)
    return pids


def liberar_porta_dashboard(port: int) -> None:
    if platform.system() != "Windows":
        return
    for pid in port_process_ids(port):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
            print(f"Processo antigo na porta {port} encerrado (PID {pid}).")
        except OSError as exc:
            print(f"Aviso: nao foi possivel encerrar PID {pid} na porta {port}: {exc}")


def run_apps(args: argparse.Namespace, paths: dict[str, Path]) -> None:
    year_args = [str(ano) for ano in effective_update_years(args.anos)]

    balancos = [sys.executable, script_path("app_balancos.py"), "--output-dir", str(args.resultados)]
    if year_args:
        balancos.extend(["--years", *year_args])
    balancos.append("--force-download")
    run_command(balancos)

    dre = [sys.executable, script_path("app_dre.py"), "--saida", str(paths["dre"])]
    if year_args:
        dre.extend(["--anos", *year_args])
    dre.append("--sobrescrever-zips")
    run_command(dre)

    dfc = [sys.executable, script_path("app_dfc.py"), "--diretorio", str(args.resultados), "--saida", str(paths["dfc"])]
    if year_args:
        dfc.extend(["--anos", *year_args])
    dfc.append("--sobrescrever-downloads")
    run_command(dfc)


def find_balanco_json(resultados: Path) -> Path:
    candidatos = sorted(resultados.glob("balancos_itr_cvm_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum JSON de balanco encontrado em {resultados}. "
            "Rode o dashboard a partir da pasta V2, use --atualizar, ou informe --resultados com o caminho correto."
        )
    return candidatos[0]


def find_optional_balanco_json(resultados: Path) -> Path | None:
    candidatos = sorted(resultados.glob("balancos_itr_cvm_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidatos[0] if candidatos else None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return load_json(path)


def load_optional_statement(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return load_json(path)


def file_metadata(path: Path | None, expected_path: Path | None = None) -> dict:
    reference = path or expected_path
    return {
        "path": str(reference) if reference is not None else "",
        "modified_at": path.stat().st_mtime if path is not None and path.exists() else None,
        "exists": bool(path is not None and path.exists()),
    }


def load_methodology_markdown() -> str:
    path = BASE_DIR / "metodologia.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def migrate_legacy_company_tickers(payload: dict | None) -> dict | None:
    """Migra somente na leitura chaves publicadas sob tickers históricos."""
    if not isinstance(payload, dict):
        return payload
    companies = payload.get("companies")
    if isinstance(companies, dict) and "INNT3" in companies and "INNC3" not in companies:
        companies = dict(companies)
        company = companies.pop("INNT3")
        if isinstance(company, dict):
            company = dict(company)
            for key in ("ticker", "ticker_b3"):
                if company.get(key) == "INNT3":
                    company[key] = "INNC3"
            if company.get("ticker_yahoo") == "INNT3.SA":
                company["ticker_yahoo"] = "INNC3.SA"
        companies["INNC3"] = company
        payload = dict(payload)
        payload["companies"] = companies
    return payload


def load_operational_data(resultados: Path) -> tuple[dict, dict[str, dict]]:
    candidate_files = [
        resultados / "dados_operacionais.json",
        resultados / "operacional.json",
        resultados / "fundamentos_operacionais.json",
        resultados / "app_extrator_operacional.json",
    ]
    for path in candidate_files:
        if not path.exists():
            continue
        data = load_json(path)
        if "companies" in data:
            return data, {"operacional": {"path": str(path), "modified_at": path.stat().st_mtime}}
        ticker = str(data.get("ticker") or "").upper()
        if ticker in TICKERS and "metricas" in data:
            return {"companies": {ticker: data}}, {"operacional": {"path": str(path), "modified_at": path.stat().st_mtime}}

    companies: dict[str, dict] = {}
    file_meta: dict[str, dict] = {}
    search_dirs = [resultados / "operacional", resultados / "dados_operacionais", resultados]
    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = load_json(path)
            except Exception:
                continue
            ticker = str(data.get("ticker") or "").upper()
            if ticker not in TICKERS or "metricas" not in data:
                continue
            companies[ticker] = data
            file_meta[f"operacional_{ticker}"] = {"path": str(path), "modified_at": path.stat().st_mtime, "exists": True}
    return {"companies": companies}, file_meta


def load_operational_data_from_source(source: DashboardDataSource, resultados: Path) -> tuple[dict, dict[str, dict]]:
    if source.mode in {"remote", "auto"} and source.remote_available:
        companies: dict[str, dict] = {}
        file_meta: dict[str, dict] = {}
        for relative in source.operational_paths():
            data = source.load_remote_optional(relative, f"operacional_{Path(relative).stem.upper()}")
            if not data:
                continue
            ticker = str(data.get("ticker") or "").upper()
            if ticker in TICKERS and "metricas" in data:
                companies[ticker] = data
                file_meta[f"operacional_{ticker}"] = source.files.get(f"operacional_{Path(relative).stem.upper()}", {})
        if companies or source.mode == "remote":
            return {"companies": companies}, file_meta
    return load_operational_data(resultados)


def local_manual_overrides_path(resultados: Path) -> Path:
    return resultados / MANUAL_OVERRIDES_FILENAME


def load_manual_overrides_from_source(source: DashboardDataSource, resultados: Path) -> tuple[dict, dict[str, dict]]:
    remote_relative = source.manual_operational_path()
    expected = local_manual_overrides_path(resultados)
    if source.mode in {"remote", "auto"} and source.remote_available and remote_relative:
        data = source.load_remote_optional(remote_relative, "manual_operational")
        if data is not None:
            return normalize_manual_payload(data), {"manual_operational": source.files.get("manual_operational", {})}
        if source.mode == "remote":
            return empty_manual_payload(), {"manual_operational": source.files.get("manual_operational", {})}
    if source.mode in {"local", "auto"}:
        source.files["manual_operational"] = file_metadata(expected if expected.exists() else None, expected)
        return load_manual_overrides_file(expected), {"manual_operational": source.files["manual_operational"]}
    return empty_manual_payload(), {}


def dashboard_payload(resultados: Path, sector: str = "saude", force_remote_refresh: bool = False) -> dict:
    sector = validate_sector(sector)
    if sector == "all":
        raise ValueError("O dashboard requer um setor especifico.")
    resultados.mkdir(parents=True, exist_ok=True)
    sector_dir = resultados / sector
    data_dir = sector_dir if sector_dir.exists() or sector != "saude" else resultados
    data_dir.mkdir(parents=True, exist_ok=True)
    source = DashboardDataSource(data_dir, force_remote_refresh=force_remote_refresh, sector=sector)
    remote_files = source.remote_file_map()
    balanco_relative = remote_files.get("balanco")
    local_paths = {
        "balanco": find_optional_balanco_json(data_dir),
        "dre": data_dir / "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": data_dir / "DFC_ITR_CVM.json",
        "indicadores": data_dir / "indicadores.json",
        "divida_liquida": data_dir / "divida_liquida.json",
        "ciclo_financeiro": data_dir / "ciclo_financeiro.json",
        "market_cap": data_dir / "market_cap.json",
    }
    expected_paths = {
        "balanco": resultados / "balancos_itr_cvm_*.json",
        "dre": local_paths["dre"],
        "dfc": local_paths["dfc"],
        "indicadores": local_paths["indicadores"],
        "divida_liquida": local_paths["divida_liquida"],
        "ciclo_financeiro": local_paths["ciclo_financeiro"],
        "market_cap": local_paths["market_cap"],
    }
    statements = {
        "balanco": source.load_optional("balanco", local_paths["balanco"], balanco_relative, expected_paths["balanco"]) or {},
        "dre": source.load_optional("dre", local_paths["dre"], remote_files.get("dre", "DRE_ITR_CVM_ultimos_5_anos.json"), expected_paths["dre"]) or {},
        "dfc": source.load_optional("dfc", local_paths["dfc"], remote_files.get("dfc", "DFC_ITR_CVM.json"), expected_paths["dfc"]) or {},
    }
    if sector == "construcao_civil":
        statements = {key: migrate_legacy_company_tickers(value) or {} for key, value in statements.items()}
    operational_data, operational_files = load_operational_data_from_source(source, data_dir) if sector == "saude" else ({"companies": {}}, {})
    manual_overrides, manual_files = load_manual_overrides_from_source(source, data_dir) if sector == "saude" else (empty_manual_payload(), {})
    operational_data, manual_overrides_resolved = resolve_operational_data_with_manual(operational_data, manual_overrides)
    indicators = {
        "indicadores": source.load_optional("indicadores", local_paths["indicadores"], remote_files.get("indicadores", "indicadores.json"), expected_paths["indicadores"]),
        "divida_liquida": source.load_optional("divida_liquida", local_paths["divida_liquida"], remote_files.get("divida_liquida", "divida_liquida.json"), expected_paths["divida_liquida"]),
        "ciclo_financeiro": source.load_optional("ciclo_financeiro", local_paths["ciclo_financeiro"], remote_files.get("ciclo_financeiro", "ciclo_financeiro.json"), expected_paths["ciclo_financeiro"]),
        "market_cap": source.load_optional("market_cap", local_paths["market_cap"], remote_files.get("market_cap", "market_cap.json"), expected_paths["market_cap"]),
    }
    if sector == "construcao_civil":
        indicators = {key: migrate_legacy_company_tickers(value) for key, value in indicators.items()}
    # Primeiro boot em cloud pode nao ter JSONs; has_data so fica true quando
    # os tres demonstrativos financeiros minimos ja foram gerados.
    has_data = all(bool(statements[key]) for key in ("balanco", "dre", "dfc"))
    comparison = build_comparison_payload(indicators, operational_data, tickers_for_sector(sector))
    chart_assets = build_chart_assets(source)
    return {
        "sector": sector,
        "sector_label": SECTOR_LABELS[sector],
        "operational_enabled": sector == "saude",
        "tickers": tickers_for_sector(sector),
        "has_data": has_data,
        "data_source": source.data_source,
        "data_source_mode": source.mode,
        "remote_metadata": source.remote_metadata,
        "statements": statements,
        "indicators": indicators,
        "operational": operational_data,
        "manual_operational": {
            **manual_overrides_resolved,
            "write_enabled": manual_admin_token_configured(),
        },
        "comparison": comparison,
        "chart_assets": chart_assets,
        "methodology_markdown": load_methodology_markdown(),
        "update_status": dict(UPDATE_STATE),
        "files": source.files | operational_files | manual_files,
    }


CHARTS = {
    "ev_ebitda": {
        "title": "EV/EBITDA LTM historico",
        "kind": "line",
        "value": "ev_ebitda",
        "value_label": "EV/EBITDA LTM (x)",
    },
    "capital_giro": {
        "title": "Capital de giro e % da receita",
        "kind": "combo",
        "value": "capital_giro",
        "secondary": "capital_giro_percentual_receita",
        "value_label": "Capital de giro (R$ mi)",
        "secondary_label": "CG / receita (%)",
    },
    "resultado_bruto": {
        "title": "Resultado bruto e margem bruta",
        "kind": "combo",
        "value": "resultado_bruto",
        "secondary": "margens_percentual.margem_bruta",
        "value_label": "Resultado bruto (R$ mi)",
        "secondary_label": "Margem bruta (%)",
    },
    "ebit": {
        "title": "EBIT e margem operacional",
        "kind": "combo",
        "value": "ebit",
        "secondary": "margens_percentual.margem_operacional",
        "value_label": "EBIT (R$ mi)",
        "secondary_label": "Margem operacional (%)",
    },
    "ebitda": {
        "title": "EBITDA contabil calculado e margem",
        "kind": "combo",
        "value": "ebitda",
        "secondary": "margens_percentual.margem_ebitda",
        "value_label": "EBITDA contabil (R$ mi)",
        "secondary_label": "Margem EBITDA contabil (%)",
    },
    "lucro_liquido": {
        "title": "Lucro liquido e margem liquida",
        "kind": "combo",
        "value": "lucro_liquido",
        "secondary": "margens_percentual.margem_liquida",
        "value_label": "Lucro liquido (R$ mi)",
        "secondary_label": "Margem liquida (%)",
    },
}


def nested_get(data: dict, path: str) -> float | None:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current if isinstance(current, (int, float)) else None


def period_label(record: dict) -> str:
    meta = record.get("metadata") or {}
    year = meta.get("year")
    quarter = meta.get("quarter")
    is_ytd = meta.get("is_ytd")
    if year and quarter:
        return str(year) if is_ytd and quarter == 4 else f"{quarter}T{str(year)[-2:]}"
    return str(record.get("periodo") or "")


def filter_records_for_view(records: list[dict], view: str) -> list[dict]:
    def key(record: dict) -> tuple[int, int, int]:
        meta = record.get("metadata") or {}
        return (int(meta.get("year") or 0), int(meta.get("quarter") or 0), 1 if meta.get("is_ytd") else 0)

    selected = []
    for record in records:
        meta = record.get("metadata") or {}
        quarter = int(meta.get("quarter") or 0)
        is_ytd = bool(meta.get("is_ytd"))
        if view == "annual":
            if is_ytd and quarter == 4:
                selected.append(record)
        else:
            if (not is_ytd) or quarter == 1:
                selected.append(record)
    return sorted(selected, key=key)


COMPARISON_METRICS = (
    ("cagr_receita", "CAGR Receita", "percent"),
    ("cagr_lucros", "CAGR Lucros", "percent"),
    ("ciclo_financeiro", "Ciclo Financeiro", "days"),
    ("margem_bruta", "Margem Bruta", "percent"),
    ("margem_operacional", "Margem Operacional", "percent"),
    ("margem_ebitda", "Margem EBITDA", "percent"),
    ("margem_liquida", "Margem Líquida", "percent"),
    ("ev_ebitda", "EV/EBITDA", "multiple"),
    ("delta_preco_30d", "Delta Preço da Ação 30 dias", "signed_percent"),
    ("delta_preco_360d", "Delta Preço da Ação 360 dias", "signed_percent"),
    ("n_unidades", "N. Unidades", "integer"),
)


def _as_number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and pd.notna(value) else None


def _record_sort_tuple(record: dict) -> tuple[int, int, int]:
    meta = record.get("metadata") or {}
    return (
        int(meta.get("year") or 0),
        int(meta.get("quarter") or 0),
        1 if meta.get("is_ytd") else 0,
    )


def _period_sort_key(period: str) -> tuple[int, int]:
    text = str(period or "")
    if len(text) == 4 and text.isdigit():
        return int(text), 5
    if len(text) >= 4 and text[1].upper() == "T" and text[0].isdigit():
        yy = text[2:]
        year = int(yy) + 2000 if len(yy) == 2 and yy.isdigit() else 0
        return year, int(text[0])
    return 0, 0


def _quarter_label_from_record(record: dict) -> str:
    meta = record.get("metadata") or {}
    year = meta.get("year")
    quarter = meta.get("quarter")
    if year and quarter:
        return f"{int(quarter)}T{str(year)[-2:]}"
    return period_label(record)


def _annual_records(records: list[dict]) -> list[dict]:
    return filter_records_for_view(records, "annual")


def _cagr_value(first: object, last: object, years: int) -> float | None:
    first_num = _as_number(first)
    last_num = _as_number(last)
    if first_num is None or last_num is None or first_num <= 0 or last_num <= 0 or years <= 0:
        return None
    return (pow(last_num / first_num, 1 / years) - 1) * 100


def _quality_for_metric(record: dict | None, metric: str) -> dict | None:
    if not record:
        return None
    for flag in record.get("quality_flags") or []:
        if flag.get("metric") == metric:
            return flag
    quality = record.get(f"quality_{metric}")
    return quality if isinstance(quality, dict) else None


def _comparison_cell(
    value: float | int | None,
    period: str | None = None,
    *,
    quality: dict | None = None,
    confidence: str | None = None,
    source: str | None = None,
    extra: dict | None = None,
) -> dict:
    return {
        "value": value,
        "period": period,
        "quality": quality,
        "confidence": confidence,
        "source": source,
        **(extra or {}),
    }


def _latest_annual_cycle(records: list[dict]) -> dict | None:
    annual = []
    for record in records or []:
        periodo = record.get("periodo") or {}
        inicio = str(periodo.get("inicio") or "")
        fim = str(periodo.get("fim") or "")
        if inicio.endswith("-01-01") and fim.endswith("-12-31"):
            annual.append(record)
    return sorted(annual, key=lambda item: str((item.get("periodo") or {}).get("fim") or ""))[-1] if annual else None


def _latest_operational_metric(company: dict, metric: str) -> dict | None:
    candidates = []
    for item in (company.get("metricas") or {}).get(metric, []) or []:
        if item.get("confidence") == "low":
            continue
        for period, value in (item.get("serie") or {}).items():
            number = _as_number(value)
            if number is None:
                continue
            candidates.append(
                {
                    "period": period,
                    "value": number,
                    "confidence": item.get("confidence"),
                    "source": item.get("fonte_linha") or item.get("escopo"),
                }
            )
    return sorted(candidates, key=lambda item: _period_sort_key(str(item["period"])))[-1] if candidates else None


def build_comparison_payload(indicators: dict, operational: dict, tickers: Iterable[str] | None = None) -> dict:
    tickers = tuple(tickers or TICKERS)
    indicadores = ((indicators.get("indicadores") or {}).get("companies") or {})
    ciclo = ((indicators.get("ciclo_financeiro") or {}).get("companies") or {})
    market = ((indicators.get("market_cap") or {}).get("companies") or {})
    operational_companies = ((operational or {}).get("companies") or {})
    companies: dict[str, dict[str, dict]] = {}
    charts = {
        "ciclo_financeiro": {"title": "Ciclo Financeiro", "unit": "dias", "periodicity": "annual", "series": {}},
        "margem_bruta": {"title": "Margem Bruta", "unit": "%", "periodicity": "annual", "series": {}},
        "margem_operacional": {"title": "Margem Operacional", "unit": "%", "periodicity": "annual", "series": {}},
        "margem_ebitda": {"title": "Margem EBITDA", "unit": "%", "periodicity": "annual", "series": {}},
        "margem_liquida": {"title": "Margem Líquida", "unit": "%", "periodicity": "annual", "series": {}},
    }

    for ticker in tickers:
        records = list((indicadores.get(ticker) or {}).get("periodos") or [])
        annual = _annual_records(records)
        first = annual[0] if annual else None
        last = annual[-1] if annual else None
        first_year = (first.get("metadata") or {}).get("year") if first else None
        last_year = (last.get("metadata") or {}).get("year") if last else None
        years = int(last_year) - int(first_year) if first_year and last_year else 0
        cagr_period = f"{first_year}–{last_year}" if years > 0 else None

        company = {
            "cagr_receita": _comparison_cell(
                _cagr_value(first.get("receita_liquida") if first else None, last.get("receita_liquida") if last else None, years),
                cagr_period,
            ),
            "cagr_lucros": _comparison_cell(
                _cagr_value(first.get("lucro_liquido") if first else None, last.get("lucro_liquido") if last else None, years),
                cagr_period,
            ),
        }

        cycle_record = _latest_annual_cycle(ciclo.get(ticker) or [])
        cycle_value = ((cycle_record or {}).get("indicadores_dias") or {}).get("ciclo_financeiro")
        cycle_period = None
        if cycle_record:
            fim = ((cycle_record.get("periodo") or {}).get("fim") or "")[:4]
            cycle_period = f"FY{fim}" if fim else None
        company["ciclo_financeiro"] = _comparison_cell(_as_number(cycle_value), cycle_period)

        margin_map = {
            "margem_bruta": "margem_bruta",
            "margem_operacional": "margem_operacional",
            "margem_ebitda": "margem_ebitda",
            "margem_liquida": "margem_liquida",
        }
        for out_key, source_key in margin_map.items():
            value = ((last or {}).get("margens_percentual") or {}).get(source_key)
            period = f"FY{last_year}" if last_year else None
            quality = _quality_for_metric(last, source_key)
            if quality and quality.get("status") in {"incomplete", "not_comparable"}:
                value = None
            company[out_key] = _comparison_cell(_as_number(value), period, quality=quality)

        valid_ev = [
            record for record in records
            if _as_number(record.get("ev_ebitda_ltm")) is not None
        ]
        valid_ev = sorted(valid_ev, key=_record_sort_tuple)
        ev_record = valid_ev[-1] if valid_ev else None
        company["ev_ebitda"] = _comparison_cell(
            _as_number(ev_record.get("ev_ebitda_ltm")) if ev_record else None,
            f"LTM {_quarter_label_from_record(ev_record)}" if ev_record else None,
            quality=(ev_record or {}).get("quality_ev_ebitda_ltm") if ev_record else None,
            extra={
                "enterprise_value": (ev_record or {}).get("enterprise_value"),
                "ebitda_ltm": (ev_record or {}).get("ebitda_ltm"),
                "data_market_cap": (ev_record or {}).get("data_market_cap"),
                "data_divida_liquida": (ev_record or {}).get("data_divida_liquida"),
                "data_ebitda_ltm": (ev_record or {}).get("data_ebitda_ltm"),
            } if ev_record else None,
        )

        quote_data = market.get(ticker) or {}
        company["delta_preco_30d"] = _comparison_cell(_as_number(quote_data.get("variacao_30d_pct")), "Atual")
        company["delta_preco_360d"] = _comparison_cell(_as_number(quote_data.get("variacao_360d_pct")), "Atual")

        units = _latest_operational_metric(operational_companies.get(ticker) or {}, "N. Unidades")
        company["n_unidades"] = _comparison_cell(
            units.get("value") if units else None,
            units.get("period") if units else None,
            confidence=units.get("confidence") if units else "not_found",
            source=units.get("source") if units else None,
        )
        companies[ticker] = company

        charts["ciclo_financeiro"]["series"][ticker] = [
            {
                "period": f"FY{(item.get('periodo') or {}).get('fim', '')[:4]}",
                "value": _as_number((item.get("indicadores_dias") or {}).get("ciclo_financeiro")),
            }
            for item in sorted([item for item in (ciclo.get(ticker) or []) if _latest_annual_cycle([item])], key=lambda row: str((row.get("periodo") or {}).get("fim") or ""))
        ]
        for chart_key, source_key in margin_map.items():
            charts[chart_key]["series"][ticker] = [
                {
                    "period": f"FY{(record.get('metadata') or {}).get('year')}",
                    "value": _as_number((record.get("margens_percentual") or {}).get(source_key)),
                    "quality": _quality_for_metric(record, source_key),
                }
                for record in annual
            ]

    return {
        "companies_order": list(tickers),
        "metrics": [
            {"key": key, "label": label, "format": fmt}
            for key, label, fmt in COMPARISON_METRICS
        ],
        "companies": companies,
        "charts": charts,
    }


def build_chart_assets(source: DashboardDataSource) -> dict:
    manifest = source.chart_manifest()
    version = source.data_version()

    def with_url(path: str) -> dict:
        asset_path = f"charts/{source.sector}/{path.removeprefix('charts/')}" if source.manifest_v2 and path.startswith("charts/") else path
        url = remote_asset_url_for(asset_path) if asset_path else ""
        return {"path": path, "url": f"{url}?v={quote(version)}" if url and version else url}

    individual: dict[str, dict[str, dict]] = {}
    for ticker, charts in (manifest.get("individual") or {}).items():
        if not isinstance(charts, dict):
            continue
        individual[ticker] = {key: with_url(path) for key, path in charts.items() if isinstance(path, str)}
    comparison = {
        key: with_url(path)
        for key, path in (manifest.get("comparison") or {}).items()
        if isinstance(path, str)
    }
    return {
        "version": version,
        "individual": individual,
        "comparison": comparison,
    }


def chart_dataframe(resultados: Path, ticker: str, view: str, chart_key: str, sector: str = "saude") -> pd.DataFrame:
    payload = dashboard_payload(resultados, sector=sector)
    company = (((payload.get("indicators") or {}).get("indicadores") or {}).get("companies") or {}).get(ticker)
    if not company:
        return pd.DataFrame()
    config = CHARTS[chart_key]
    rows = []
    for record in filter_records_for_view(company.get("periodos") or [], view):
        value = nested_get(record, config["value"])
        secondary = nested_get(record, config.get("secondary", "")) if config.get("secondary") else None
        if value is None:
            continue
        rows.append(
            {
                "periodo": period_label(record),
                "valor": value / 1_000_000 if config["kind"] == "combo" else value,
                "secundario": secondary,
            }
        )
    return pd.DataFrame(rows)


def make_chart_png(resultados: Path, ticker: str, view: str, chart_key: str, sector: str = "saude") -> bytes:
    config = CHARTS[chart_key]
    df = chart_dataframe(resultados, ticker, view, chart_key, sector)
    fig_width = max(8.0, min(16.0, 0.65 * max(len(df), 1) + 5.5))
    fig_height = 4.2 if view == "quarterly" else 3.6
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    if df.empty:
        ax.text(0.5, 0.5, "Sem dados", ha="center", va="center", color="#52625d")
        ax.axis("off")
    else:
        x = range(len(df))
        labels = df["periodo"].tolist()
        ax.axhline(0, color="#d8d0b0", linewidth=1.2)
        if config["kind"] == "combo":
            bars = ax.bar(x, df["valor"], color="#23AC81", width=0.52, label=config["value_label"])
            ax2 = ax.twinx()
            ax2.plot(
                x,
                df["secundario"],
                color="#00513F",
                marker="o",
                markersize=2.0,
                linewidth=0.7,
                label=config["secondary_label"],
            )
            ax.set_ylabel(config["value_label"], color="#00513F", fontsize=9)
            ax2.set_ylabel(config["secondary_label"], color="#00513F", fontsize=9)
            ax2.axhline(0, color="#d8d0b0", linewidth=1.0, alpha=0)
            for bar in bars:
                height = bar.get_height()
                if pd.isna(height):
                    continue
                label_y = height - (abs(height) * 0.08 if height >= 0 else -abs(height) * 0.08)
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    label_y,
                    f"{height:,.0f}".replace(",", "."),
                    ha="center",
                    va="top" if height >= 0 else "bottom",
                    color="#F4F1E6",
                    fontsize=8,
                    fontweight="bold",
                )
            ax2.tick_params(axis="y", labelsize=8, colors="#00513F", color="#DDD5B3")
            for spine in ("left", "right", "bottom"):
                ax2.spines[spine].set_color("#DDD5B3")
            ax2.spines["top"].set_visible(False)
        else:
            ax.plot(x, df["valor"], color="#00513F", marker="o", markersize=2.0, linewidth=0.75)
            ax.set_ylabel(config["value_label"], color="#00513F", fontsize=9)
            for xi, value in zip(x, df["valor"]):
                ax.annotate(
                    f"{value:.2f}",
                    (xi, value),
                    textcoords="offset points",
                    xytext=(0, 8),
                    ha="center",
                    color="#00513F",
                    fontsize=8,
                    fontweight="bold",
                )

        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=0 if len(df) <= 8 else 45, ha="right" if len(df) > 8 else "center", fontsize=8)
        ax.tick_params(axis="x", labelsize=8, colors="#00513F", color="#DDD5B3")
        ax.tick_params(axis="y", labelsize=8, colors="#00513F", color="#DDD5B3")
        ax.spines["top"].set_visible(False)
        for spine in ("left", "right", "bottom"):
            ax.spines[spine].set_color("#DDD5B3")
        ax.grid(False)
        ax.set_title(config["title"], color="#00513F", loc="left", fontsize=11, fontweight="bold")

    fig.tight_layout(pad=1.1)
    output = io.BytesIO()
    fig.savefig(output, format="png", bbox_inches="tight")
    plt.close(fig)
    return output.getvalue()


def static_export_html(resultados: Path, sector: str = "saude") -> str:
    payload = dashboard_payload(resultados, sector=sector)
    charts: dict[str, str] = {}
    for ticker in tickers_for_sector(sector):
        for view in ("annual", "quarterly"):
            for chart_key in CHARTS:
                try:
                    png = make_chart_png(resultados, ticker, view, chart_key, sector)
                except Exception:
                    continue
                charts[f"{ticker}|{view}|{chart_key}"] = (
                    "data:image/png;base64,"
                    + base64.b64encode(png).decode("ascii")
                )

    static_script = (
        "<script>\n"
        f"window.__STATIC_DATA__ = {json.dumps(payload, ensure_ascii=False, allow_nan=False)};\n"
        f"window.__STATIC_CHARTS__ = {json.dumps(charts, ensure_ascii=False, allow_nan=False)};\n"
        "</script>\n"
    )
    return HTML.replace("<script>\n    let DATA = null;", static_script + "<script>\n    let DATA = null;", 1)


def manual_auth_ok() -> bool:
    expected = os.getenv("NERIAS_MANUAL_ADMIN_TOKEN")
    if not expected:
        return False
    provided = request.headers.get("X-Nerias-Admin-Token") or ""
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        provided = auth.split(" ", 1)[1].strip()
    return bool(provided) and provided == expected


def current_manual_payload_for_write(resultados: Path) -> dict:
    token = os.getenv("DATA_REPO_TOKEN")
    if configured_data_source_mode() in {"remote", "auto"} and token:
        repo = os.getenv("NERIAS_DATA_REPO", DEFAULT_DATA_REPO)
        branch = os.getenv("NERIAS_DATA_REPO_BRANCH", DEFAULT_DATA_REPO_BRANCH)
        payload, _sha = load_remote_manual_overrides(repo, branch, token)
        return payload
    return load_manual_overrides_file(local_manual_overrides_path(resultados))


def persist_manual_payload(resultados: Path, payload: dict, message: str) -> dict:
    token = os.getenv("DATA_REPO_TOKEN")
    if configured_data_source_mode() in {"remote", "auto"} and token:
        repo = os.getenv("NERIAS_DATA_REPO", DEFAULT_DATA_REPO)
        branch = os.getenv("NERIAS_DATA_REPO_BRANCH", DEFAULT_DATA_REPO_BRANCH)
        save_remote_manual_overrides(repo, branch, token, payload, message)
        clear_remote_cache()
        return {"storage": "github_data_repo", "repo": repo, "branch": branch}
    path = local_manual_overrides_path(resultados)
    write_manual_overrides_file(path, payload)
    return {"storage": "local_file", "path": str(path)}


HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acompanhador de Mercado</title>
  <style>
    :root {
      --nerias-ink: #0A1611;
      --nerias-green-deep: #00513F;
      --nerias-green: #006341;
      --nerias-green-mid: #034B3C;
      --nerias-mint: #23AC81;
      --nerias-bg: #F4F1E6;
      --nerias-surface: #ffffff;
      --nerias-sand: #DDD5B3;
      --nerias-line: #d8d0b0;
      --nerias-muted: #52625d;
      --nerias-aggregate: #edf3ee;
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Apparat", "Aptos", "Segoe UI", Arial, sans-serif;
      margin: 0;
      color: var(--nerias-ink);
      background: var(--nerias-bg);
    }
    body::before {
      content: "";
      display: block;
      height: 5px;
      background: linear-gradient(90deg, var(--nerias-ink), var(--nerias-green-deep), var(--nerias-mint));
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 24px 28px 18px;
      background: var(--nerias-green-deep);
      color: white;
      border-bottom: 1px solid rgba(255,255,255,0.12);
    }
    .brand-title {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .nerias-logo {
      width: 128px;
      height: 54px;
      object-fit: contain;
      display: block;
    }
    h1 {
      margin: 0;
      font-size: 34px;
      font-weight: 650;
      letter-spacing: 0;
    }
    h2 {
      margin: 22px 28px 10px;
      color: var(--nerias-green-deep);
      font-size: 16px;
      font-weight: 650;
    }
    .quote {
      display: flex;
      align-items: stretch;
      justify-content: flex-end;
      gap: 10px;
      min-width: 0;
      padding: 0;
      text-align: left;
      border: 0;
      background: transparent;
    }
    .quote-logo-card,
    .quote-price-card {
      border-radius: 12px;
      border: 1px solid rgba(221,213,179,0.42);
      min-height: 74px;
    }
    .quote-logo-card {
      width: 112px;
      padding: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: white;
    }
    .quote-logo-card img {
      max-width: 92px;
      max-height: 50px;
      object-fit: contain;
      display: block;
    }
    .quote-price-card {
      width: 214px;
      padding: 10px 12px;
      font-size: 13px;
      color: rgba(255,255,255,0.78);
      background: rgba(255,255,255,0.06);
    }
    .quote strong {
      display: block;
      margin-bottom: 4px;
      font-size: 18px;
      color: white;
      font-weight: 650;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0;
      padding: 14px 28px 0;
      background: var(--nerias-surface);
    }
    button {
      padding: 8px 13px;
      border: 1px solid var(--nerias-line);
      background: #fbfaf8;
      color: var(--nerias-green);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      border-radius: 999px;
    }
    button:hover { border-color: var(--nerias-mint); color: var(--nerias-green-deep); }
    button.active {
      background: var(--nerias-green);
      color: white;
      border-color: var(--nerias-green);
    }
    button.update-button {
      margin-left: auto;
      background: var(--nerias-green-deep);
      color: #fffaf0;
      border-color: var(--nerias-green-deep);
    }
    button.update-button:disabled {
      opacity: 0.58;
      cursor: wait;
    }
    .update-status {
      min-height: 22px;
      padding: 8px 28px 0;
      color: var(--nerias-muted);
      background: var(--nerias-surface);
      font-size: 13px;
    }
    .update-status strong { color: var(--nerias-green-deep); }
    .meta {
      margin: 0;
      padding: 12px 28px 18px;
      color: var(--nerias-muted);
      background: var(--nerias-surface);
      border-bottom: 1px solid var(--nerias-line);
      font-size: 13px;
    }
    #content { padding: 18px 28px 30px; }
    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .charts-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      align-items: start;
      margin-top: 18px;
    }
    .dashboard-card { min-width: 0; }
    .dashboard-card h2 { margin: 0 0 10px; }
    .chart-card { min-width: 0; }
    .chart-card h2 { margin: 0 0 10px; }
    .chart-card .table-wrap { max-height: none; }
    .chart-card svg { width: 100%; height: auto; }
    .chart-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      padding: 0 12px 10px;
      color: var(--nerias-muted);
      font-size: 12px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }
    .legend-item i {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }
    .chart-img {
      display: block;
      width: 100%;
      height: auto;
      background: white;
    }
    .chart-card.wide { grid-column: 1 / -1; }
    .series-table {
      margin-top: 8px;
      max-height: none;
      box-shadow: none;
    }
    .series-table table {
      width: 100%;
      min-width: 0;
      font-size: 12px;
    }
    .series-table th,
    .series-table td {
      padding: 5px 7px;
      text-align: right;
    }
    .series-table th:first-child,
    .series-table td:first-child {
      text-align: left;
      width: 120px;
    }
    .dashboard-grid .table-wrap { max-height: none; }
    .dashboard-grid table { width: 100%; min-width: 0; }
    .table-wrap {
      overflow: auto;
      max-height: 72vh;
      margin-bottom: 18px;
      border: 1px solid var(--nerias-line);
      background: var(--nerias-surface);
      box-shadow: 0 12px 28px rgba(16,26,42,0.06);
      border-radius: 12px;
    }
    table { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 13px; }
    table.fixed-layout { table-layout: fixed; width: auto; min-width: 100%; }
    table.fixed-layout th,
    table.fixed-layout td {
      overflow: hidden;
      text-overflow: ellipsis;
    }
    table.fixed-layout td.desc {
      white-space: normal;
      overflow-wrap: anywhere;
    }
    th, td {
      border: 1px solid var(--nerias-line);
      padding: 7px 9px;
      white-space: nowrap;
    }
    th {
      position: sticky;
      top: 0;
      background: #eee8d5;
      color: var(--nerias-green-deep);
      z-index: 1;
      font-weight: 700;
    }
    td { background: var(--nerias-surface); }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    td.desc { min-width: 360px; white-space: normal; }
    tr.aggregator td {
      background: var(--nerias-aggregate);
      color: var(--nerias-green-deep);
      font-weight: bold;
    }
    .row-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      margin-right: 6px;
      padding: 0;
      border-radius: 50%;
      font-size: 12px;
      line-height: 1;
      vertical-align: middle;
    }
    .empty {
      padding: 24px;
      background: var(--nerias-surface);
      border: 1px solid var(--nerias-line);
      color: var(--nerias-muted);
      border-radius: 12px;
    }
    .disclaimer {
      margin: 0 0 14px;
      padding: 12px 14px;
      border: 1px solid var(--nerias-line);
      border-radius: 12px;
      background: #fbfaf8;
      color: var(--nerias-muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .manual-toolbar {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin: 0 0 12px;
    }
    .manual-badge {
      display: inline-block;
      margin-left: 6px;
      padding: 2px 6px;
      border-radius: 999px;
      background: #b42318;
      color: #fffaf0;
      font-size: 11px;
      font-weight: 700;
    }
    td.manual-value {
      color: #b42318;
      font-weight: 700;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(10,22,17,0.42);
      z-index: 20;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: min(520px, 100%);
      padding: 20px;
      border-radius: 14px;
      border: 1px solid var(--nerias-line);
      background: var(--nerias-surface);
      box-shadow: 0 20px 50px rgba(10,22,17,0.22);
    }
    .modal h2 { margin: 0 0 14px; }
    .form-grid {
      display: grid;
      gap: 10px;
    }
    .form-grid label {
      display: grid;
      gap: 4px;
      color: var(--nerias-green-deep);
      font-size: 13px;
      font-weight: 650;
    }
    .form-grid input,
    .form-grid select {
      width: 100%;
      padding: 9px 10px;
      border: 1px solid var(--nerias-line);
      border-radius: 8px;
      font: inherit;
      color: var(--nerias-ink);
      background: #fbfaf8;
    }
    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 14px;
    }
    .manual-error {
      min-height: 18px;
      color: #b42318;
      font-size: 13px;
    }
    .methodology-content {
      max-width: 1180px;
      padding-bottom: 40px;
    }
    .methodology-content h2,
    .methodology-content h3,
    .methodology-content h4 {
      margin: 24px 0 10px;
      color: var(--nerias-green-deep);
    }
    .methodology-content p,
    .methodology-content li {
      max-width: 980px;
      line-height: 1.55;
    }
    .methodology-content pre {
      max-width: 980px;
      overflow: auto;
      padding: 14px;
      background: #fbfaf8;
      border: 1px solid var(--nerias-line);
      border-radius: 10px;
    }
    .methodology-content code {
      color: var(--nerias-green-deep);
      background: #fbfaf8;
      border: 1px solid rgba(221,213,179,0.6);
      border-radius: 5px;
      padding: 1px 4px;
    }
    svg { display: block; background: var(--nerias-surface); }
    @media (max-width: 760px) {
      .topbar { display: block; padding: 20px; }
      .brand-title { align-items: flex-start; }
      .nerias-logo { width: 92px; height: 42px; }
      h1 { font-size: 26px; }
      .quote { margin-top: 14px; justify-content: flex-start; }
      .tabs, .meta, #content { padding-left: 16px; padding-right: 16px; }
      h2 { margin-left: 16px; margin-right: 16px; }
      .dashboard-grid { grid-template-columns: 1fr; }
      .charts-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="sector-selector" style="position:fixed;inset:0;z-index:9999;background:#f4f7fb;display:flex;align-items:center;justify-content:center">
    <div style="text-align:center"><h1>Selecione o setor</h1><p>Escolha os dados que deseja consultar.</p>
      <button class="update-button" onclick="selectSector('saude')">Saúde</button>
      <button class="update-button" onclick="selectSector('construcao_civil')">Construção civil</button>
    </div>
  </div>
  <div class="topbar">
    <div class="brand-title">
      <img class="nerias-logo" src="/logos/Nerias.png" alt="Nerias">
      <h1>Acompanhador de Mercado</h1>
      <span id="active-sector"></span><button onclick="changeSector()">Trocar setor</button>
    </div>
    <div id="quote" class="quote"></div>
  </div>
  <div id="main-tabs" class="tabs"></div>
  <div id="company-tabs" class="tabs"></div>
  <div id="statement-tabs" class="tabs"></div>
  <div id="view-tabs" class="tabs"></div>
  <div id="update-status" class="update-status"></div>
  <div id="meta" class="meta">Carregando...</div>
  <div id="content"></div>
  <div id="manual-modal" class="modal-backdrop">
    <div class="modal">
      <h2>Adicionar dado manual</h2>
      <div class="form-grid">
        <label>Empresa<select id="manual-ticker"></select></label>
        <label>Indicador<select id="manual-metric"></select></label>
        <label>Período<input id="manual-period" placeholder="2T26 ou 2025"></label>
        <label>Valor<input id="manual-value" placeholder="1.234,56"></label>
        <label>Token admin<input id="manual-token" type="password" autocomplete="off"></label>
      </div>
      <div id="manual-error" class="manual-error"></div>
      <div class="modal-actions">
        <button onclick="closeManualModal()">Cancelar</button>
        <button class="update-button" onclick="saveManualOverride()">Salvar</button>
      </div>
    </div>
  </div>
  <script>
    let DATA = null;
    let currentSector = null;
    let currentTicker = null;
    let currentMain = "dados";
    let currentStatement = "dashboard";
    let currentView = "annual";
    let comparisonSelectedTickers = [];
    let updatePolling = null;
    let currentManualEditingId = null;
    const expandedRows = new Set();
    const labels = { dashboard: "Dashboard", operacional: "Dados Operacionais", balanco: "Balanço", dre: "DRE", dfc: "DFC" };
    const mainLabels = { dados: "Dados", comparativo: "Comparativo", metodologia: "Metodologia", auditoria: "Auditoria" };
    const viewLabels = { annual: "Anual", quarterly: "Trimestral" };
    const operationalMetrics = ["Ticket Médio", "N. Atendimentos", "N. Unidades", "N. Pacientes", "Receita Bruta", "Glosa/PCLD"];
    const workflowUrl = "https://github.com/pedroatnerias/ri-tracker/actions/workflows/update-data.yml";

    function selectSector(sector) {
      currentSector = sector;
      DATA = null; currentTicker = null; currentMain = "dados"; currentStatement = "dashboard"; currentView = "annual"; comparisonSelectedTickers = [];
      expandedRows.clear();
      if (updatePolling) { clearInterval(updatePolling); updatePolling = null; }
      document.getElementById("sector-selector").style.display = "none";
      loadData().catch(error => { document.getElementById("meta").textContent = error.message; });
    }
    function changeSector() {
      currentSector = null; DATA = null; currentTicker = null; comparisonSelectedTickers = [];
      document.getElementById("sector-selector").style.display = "flex";
    }

    async function loadData() {
      if (window.__STATIC_DATA__) {
        DATA = window.__STATIC_DATA__;
        currentTicker = DATA.tickers.includes(currentTicker) ? currentTicker : DATA.tickers[0];
        render();
        updateStatusText(DATA.update_status);
        return;
      }
      if (!currentSector) return;
      const response = await fetch(`/api/data?sector=${encodeURIComponent(currentSector)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(await response.text());
      DATA = await response.json();
      document.getElementById("active-sector").textContent = DATA.sector_label || "";
      currentTicker = DATA.tickers.includes(currentTicker) ? currentTicker : DATA.tickers[0];
      render();
      updateStatusText(DATA.update_status);
      if (DATA.update_status?.running && !updatePolling) {
        updatePolling = setInterval(pollUpdateStatus, 2500);
      }
    }

    function updateStatusText(state) {
      const el = document.getElementById("update-status");
      if (!el || !state) return;
      if (state.running) {
        const scope = state.scope ? ` ${escapeHtml(updateScopeLabel(state.scope))}` : "";
        el.innerHTML = `<strong>Atualizando${scope}...</strong> ${escapeHtml(state.current_step || "")}`;
        return;
      }
      if (state.status === "success") {
        el.innerHTML = "<strong>Atualização concluída.</strong> Dados recarregados.";
        return;
      }
      if (state.status === "success_with_warnings") {
        el.innerHTML = "<strong>Atualizacao concluida com avisos.</strong> Dados recarregados.";
        return;
      }
      if (state.status === "error") {
        el.innerHTML = `<strong>Erro na atualização:</strong> ${escapeHtml(state.error || "verifique o terminal/logs")}`;
        return;
      }
      el.innerHTML = updateFreshnessHtml();
    }

    function formatTimestamp(value) {
      if (!value) return "N/D";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
    }

    function updateFreshnessHtml() {
      const components = DATA?.remote_metadata?.components || {};
      const financial = components.financial?.last_update;
      const operational = components.operational?.last_update;
      if (!financial && !operational) return "";
      return `<span><strong>Última atualização financeira:</strong> ${escapeHtml(formatTimestamp(financial))}</span> <span><strong>Última atualização operacional:</strong> ${escapeHtml(formatTimestamp(operational))}</span>`;
    }

    async function pollUpdateStatus() {
      const response = await fetch("/api/update-status", { cache: "no-store" });
      if (!response.ok) return;
      const state = await response.json();
      if (DATA) DATA.update_status = state;
      updateStatusText(state);
      renderTabs();
      if (!state.running) {
        if (updatePolling) clearInterval(updatePolling);
        updatePolling = null;
        if (["success", "success_with_warnings"].includes(state.status)) await loadData();
      }
    }

    function updateScopeLabel(scope) {
      if (scope === "financial") return "Financeiro";
      if (scope === "operational") return "Operacional";
      return "Tudo";
    }

    function updateScopeDescription(scope) {
      if (scope === "financial") return "BP, DRE, DFC, dívida, ciclo, market cap, indicadores, reconciliação e gráficos financeiros.";
      if (scope === "operational") return "documentos RI, planilhas, parser, extrator e seis métricas operacionais.";
      return "blocos financeiro e operacional.";
    }

    function openWorkflowForScope(scope) {
      const el = document.getElementById("update-status");
      if (el) {
        el.innerHTML = `<strong>Atualização remota:</strong> o Render não executa o pipeline pesado. Abrindo o GitHub Actions; selecione update_scope=${escapeHtml(scope)} e update_mode conforme necessário.`;
      }
      window.open(workflowUrl, "_blank", "noopener");
    }

    async function startUpdate(scope = "all", mode = "full") {
      if (isRemoteConfigured()) {
        openWorkflowForScope(scope);
        return;
      }
      const confirmed = window.confirm(`Atualizar ${updateScopeLabel(scope)}? Escopo: ${updateScopeDescription(scope)}`);
      if (!confirmed) return;
      const response = await fetch("/api/update", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sector: currentSector, scope, mode }),
      });
      const payload = await response.json().catch(() => ({}));
      updateStatusText(payload.status);
      if (!response.ok && response.status !== 409) {
        throw new Error(payload.error || "Falha ao iniciar atualização.");
      }
      if (!updatePolling) updatePolling = setInterval(pollUpdateStatus, 2500);
      await pollUpdateStatus();
    }

    async function startFullUpdate() {
      return startUpdate("all", "full");
    }

    async function refreshRemoteData() {
      const response = await fetch("/api/refresh-data", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sector: currentSector }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Falha ao recarregar dados.");
      await loadData();
      const el = document.getElementById("update-status");
      if (el) el.innerHTML = "<strong>Dados recarregados.</strong>";
    }

    function isRemoteConfigured() {
      return DATA?.data_source_mode === "remote" || DATA?.data_source === "remote_cache";
    }

    function renderUpdateButtons() {
      if (window.__STATIC_DATA__) return [];
      const scopes = (DATA?.operational_enabled ? [
        ["financial", "Atualizar Financeiro"],
        ["operational", "Atualizar Operacional"],
        ["all", "Atualizar Tudo"],
      ] : [["financial", "Atualizar Financeiro"]]);
      return scopes.map(([scope, label]) => {
        const btn = button(label, false, () => {
          startUpdate(scope, scope === "all" ? "full" : "incremental").catch(error => {
            const el = document.getElementById("update-status");
            if (el) el.innerHTML = `<strong>Erro:</strong> ${escapeHtml(error.message)}`;
          });
        });
        btn.classList.add("update-button");
        btn.title = isRemoteConfigured()
          ? `Abrir GitHub Actions. Selecione update_scope=${scope}.`
          : updateScopeDescription(scope);
        btn.disabled = !isRemoteConfigured() && Boolean(DATA.update_status?.running);
        return btn;
      });
    }

    function formatNumber(value) {
      if (value === null || value === undefined || Number.isNaN(value)) return "";
      if (typeof value !== "number") return value;
      return value.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
    }

    function formatMillions(value) {
      if (value === null || value === undefined || Number.isNaN(value)) return "";
      if (typeof value !== "number") return value;
      return (value / 1000000).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
    }

    function formatPercent(value) {
      if (value === null || value === undefined || Number.isNaN(value)) return "";
      if (typeof value !== "number") return value;
      return value.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function button(label, active, onClick) {
      const el = document.createElement("button");
      el.textContent = label;
      el.className = active ? "active" : "";
      el.onclick = onClick;
      return el;
    }

    function openManualModal(record = null) {
      currentManualEditingId = record?.id || null;
      const modal = document.getElementById("manual-modal");
      const tickerSelect = document.getElementById("manual-ticker");
      const metricSelect = document.getElementById("manual-metric");
      tickerSelect.innerHTML = (DATA.tickers || []).map(ticker => `<option value="${escapeHtml(ticker)}">${escapeHtml(ticker)}</option>`).join("");
      metricSelect.innerHTML = operationalMetrics.map(metric => `<option value="${escapeHtml(metric)}">${escapeHtml(metric)}</option>`).join("");
      tickerSelect.value = record?.ticker || currentTicker;
      metricSelect.value = record?.metric || operationalMetrics[0];
      document.getElementById("manual-period").value = record?.period || "";
      document.getElementById("manual-value").value = record?.value ?? "";
      document.getElementById("manual-error").textContent = "";
      modal.classList.add("open");
    }

    function closeManualModal() {
      currentManualEditingId = null;
      document.getElementById("manual-modal").classList.remove("open");
    }

    async function saveManualOverride() {
      const error = document.getElementById("manual-error");
      const payload = {
        ticker: document.getElementById("manual-ticker").value,
        metric: document.getElementById("manual-metric").value,
        period: document.getElementById("manual-period").value,
        value: document.getElementById("manual-value").value,
      };
      const token = document.getElementById("manual-token").value;
      if (!payload.ticker || !payload.metric || !payload.period || !payload.value) {
        error.textContent = "Empresa, indicador, período e valor são obrigatórios.";
        return;
      }
      if (!token) {
        error.textContent = "Token admin obrigatório para gravar dados manuais.";
        return;
      }
      const url = currentManualEditingId ? `/api/operational/manual/${encodeURIComponent(currentManualEditingId)}` : "/api/operational/manual";
      const response = await fetch(url, {
        method: currentManualEditingId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", "X-Nerias-Admin-Token": token },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        error.textContent = result.error || "Erro ao salvar dado manual.";
        return;
      }
      closeManualModal();
      await loadData();
    }

    function editManualOverride(id) {
      const record = (DATA.manual_operational?.overrides || []).find(item => item.id === id);
      if (record && record.status === "active") openManualModal(record);
    }

    async function deleteManualOverride(id) {
      if (!confirm("Excluir este dado manual?")) return;
      const token = prompt("Token admin");
      if (!token) return;
      const response = await fetch(`/api/operational/manual/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { "X-Nerias-Admin-Token": token },
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        alert(result.error || "Erro ao excluir dado manual.");
        return;
      }
      await loadData();
    }

    function expansionKey(statementKey, ticker, code) {
      return `${statementKey}|${ticker}|${code}`;
    }

    function parentToggleCode(code, rows, row) {
      if (row?.parent_code) return String(row.parent_code);
      const parts = String(code || "").split(".");
      while (parts.length > 1) {
        parts.pop();
        const candidate = parts.join(".");
        if (candidate.length <= 7) return candidate;
      }
      return "";
    }

    function isRowVisibleByToggle(row, statementKey, rows) {
      const code = String(row.code || "");
      if (!["balanco", "dre", "dfc"].includes(statementKey)) return true;
      if (code.length <= 7) return true;
      const parent = parentToggleCode(code, rows, row);
      return parent ? expandedRows.has(expansionKey(statementKey, currentTicker, parent)) : true;
    }

    function hasToggleChildren(row, rows) {
      const code = String(row.code || "");
      if (!code || code.length > 7) return false;
      return rows.some(candidate => {
        const childCode = String(candidate.code || "");
        return childCode.length > 7 && parentToggleCode(childCode, rows, candidate) === code;
      });
    }

    function toggleRow(statementKey, ticker, code) {
      const key = expansionKey(statementKey, ticker, code);
      if (expandedRows.has(key)) expandedRows.delete(key);
      else expandedRows.add(key);
      render();
    }

    function parsePeriod(text) {
      if (!text) return null;
      const iso = String(text).match(/(20\\d{2}-\\d{2}-\\d{2})/g);
      if (iso?.length >= 3) {
        return {
          reference: new Date(iso[0] + "T00:00:00"),
          start: new Date(iso[1] + "T00:00:00"),
          end: new Date(iso[2] + "T00:00:00"),
        };
      }
      if (iso?.length >= 2) return {
        reference: new Date(iso[iso.length - 1] + "T00:00:00"),
        start: new Date(iso[0] + "T00:00:00"),
        end: new Date(iso[iso.length - 1] + "T00:00:00"),
      };
      if (iso?.length === 1) {
        const date = new Date(iso[0] + "T00:00:00");
        return { reference: date, start: date, end: date };
      }
      const br = String(text).match(/(\\d{2})\\/(\\d{2})\\/(20\\d{2})/g);
      if (br?.length >= 2) {
        const [sd, sm, sy] = br[0].split("/");
        const [ed, em, ey] = br[br.length - 1].split("/");
        const end = new Date(`${ey}-${em}-${ed}T00:00:00`);
        return { reference: end, start: new Date(`${sy}-${sm}-${sd}T00:00:00`), end };
      }
      if (br?.length === 1) {
        const [day, month, year] = br[0].split("/");
        const date = new Date(`${year}-${month}-${day}T00:00:00`);
        return { reference: date, start: date, end: date };
      }
      return null;
    }

    function periodInfo(period, company) {
      const meta = company?.period_metadata?.[period];
      if (meta?.end_date) {
        const start = new Date((meta.start_date || meta.end_date) + "T00:00:00");
        const end = new Date(meta.end_date + "T00:00:00");
        return {
          period,
          start,
          reference: end,
          date: end,
          year: Number(meta.year ?? end.getFullYear()),
          quarter: Number(meta.quarter ?? Math.floor(end.getMonth() / 3) + 1),
          startsYear: Boolean(meta.is_ytd),
          sameReferenceYear: end.getFullYear() === Number(meta.year ?? end.getFullYear()),
        };
      }
      const range = parsePeriod(period);
      if (!range || Number.isNaN(range.end.getTime())) return null;
      return {
        period,
        start: range.start,
        reference: range.reference || range.end,
        date: range.end,
        year: range.end.getFullYear(),
        quarter: Math.floor(range.end.getMonth() / 3) + 1,
        startsYear: range.start.getMonth() === 0 && range.start.getDate() === 1,
        sameReferenceYear: (range.reference || range.end).getFullYear() === range.end.getFullYear(),
      };
    }

    function pickOnePerYear(infos, preferFullYear) {
      const byYear = new Map();
      infos.forEach(info => {
        const current = byYear.get(info.year);
        const infoFull = info.startsYear && info.quarter === 4;
        const currentFull = current && current.startsYear && current.quarter === 4;
        const infoSameRef = Boolean(info.sameReferenceYear);
        const currentSameRef = current ? Boolean(current.sameReferenceYear) : false;
        const shouldReplace = !current
          || (infoSameRef && !currentSameRef)
          || (preferFullYear && infoFull && !currentFull)
          || (infoSameRef === currentSameRef && infoFull === currentFull && info.reference > current.reference)
          || (infoSameRef === currentSameRef && infoFull === currentFull && info.reference.getTime() === current.reference.getTime() && info.date > current.date);
        if (shouldReplace) byYear.set(info.year, info);
      });
      return Array.from(byYear.values()).sort((a, b) => a.year - b.year);
    }

    function pickOnePerQuarter(infos) {
      const byQuarter = new Map();
      infos.forEach(info => {
        const key = `${info.year}-${info.quarter}`;
        const current = byQuarter.get(key);
        const infoSameRef = Boolean(info.sameReferenceYear);
        const currentSameRef = current ? Boolean(current.sameReferenceYear) : false;
        const shouldReplace = !current
          || (infoSameRef && !currentSameRef)
          || (infoSameRef === currentSameRef && info.reference > current.reference);
        if (shouldReplace) byQuarter.set(key, info);
      });
      return Array.from(byQuarter.values()).sort((a, b) => a.year - b.year || a.quarter - b.quarter);
    }

    function periodsByView(statementKey, company, view) {
      const periods = company?.periods || [];
      const infos = periods.map(period => periodInfo(period, company)).filter(Boolean).sort((a, b) => a.date - b.date);
      if (!infos.length) return { periods, labels: {}, supported: ["annual"] };

      if (statementKey !== "balanco") {
        const primaryInfos = infos.filter(info => info.sameReferenceYear);
        const usableInfos = primaryInfos.length ? primaryInfos : infos;
        const fullYearInfos = usableInfos.filter(info => info.startsYear && info.quarter === 4);
        const latestYtdInfos = pickOnePerYear(usableInfos.filter(info => info.startsYear), false);
        const explicitQuarterInfos = usableInfos.filter(info => (info.quarter === 1 && info.startsYear) || (!info.startsYear && info.quarter <= 4));
        const hasExplicitAfterQ1 = explicitQuarterInfos.some(info => !info.startsYear && info.quarter > 1);
        if (view === "annual") {
          const selected = fullYearInfos.length
            ? pickOnePerYear(fullYearInfos, true)
            : latestYtdInfos;
          return {
            periods: selected.map(info => info.period),
            labels: Object.fromEntries(selected.map(info => [
              info.period,
              info.quarter === 4 ? String(info.year) : `${compactQuarterLabel(info.year, info.quarter)} acumulado`
            ])),
            supported: ["annual", "quarterly"],
          };
        }
        const selected = pickOnePerQuarter(
          hasExplicitAfterQ1
            ? explicitQuarterInfos
            : usableInfos.filter(info => info.startsYear)
        );
        return {
          periods: selected.map(info => info.period),
          labels: Object.fromEntries(selected.map(info => [info.period, compactQuarterLabel(info.year, info.quarter)])),
          supported: ["annual", "quarterly"],
          deriveQuarter: !hasExplicitAfterQ1,
        };
      }

      const yearEndInfos = infos.filter(info => info.quarter === 4);
      if (view === "annual") {
        const selected = yearEndInfos.length
          ? pickOnePerYear(yearEndInfos, true)
          : pickOnePerYear(infos, false);
        return {
          periods: selected.map(info => info.period),
          labels: Object.fromEntries(selected.map(info => [
            info.period,
            info.quarter === 4 ? String(info.year) : compactQuarterLabel(info.year, info.quarter)
          ])),
          supported: ["annual", "quarterly"],
        };
      }
      return {
        periods: pickOnePerQuarter(infos).map(info => info.period),
        labels: Object.fromEntries(pickOnePerQuarter(infos).map(info => [info.period, compactQuarterLabel(info.year, info.quarter)])),
        supported: ["annual", "quarterly"],
      };
    }

    function recordPeriodInfo(record) {
      const meta = record?.metadata || {};
      if (meta.end_date) {
        const end = new Date(meta.end_date + "T00:00:00");
        const start = new Date((meta.start_date || meta.end_date) + "T00:00:00");
        return {
          record,
          period: record.periodo || record.date || meta.end_date,
          start,
          reference: end,
          date: end,
          year: Number(meta.year ?? end.getFullYear()),
          quarter: Number(meta.quarter ?? Math.floor(end.getMonth() / 3) + 1),
          startsYear: Boolean(meta.is_ytd),
          sameReferenceYear: true,
        };
      }
      const period = record?.periodo?.dre || record?.periodo || record?.date;
      const range = parsePeriod(period);
      const endDate = record?.periodo?.fim || record?.date;
      const end = endDate ? new Date(endDate + "T00:00:00") : range?.end;
      if (!end || Number.isNaN(end.getTime())) return null;
      const start = record?.periodo?.inicio ? new Date(record.periodo.inicio + "T00:00:00") : (range?.start || end);
      return {
        record,
        period,
        start,
        reference: end,
        date: end,
        year: end.getFullYear(),
        quarter: Math.floor(end.getMonth() / 3) + 1,
        startsYear: start.getMonth() === 0 && start.getDate() === 1,
        sameReferenceYear: true,
      };
    }

    function filterIndicatorRecords(records, view) {
      const infos = (records || []).map(recordPeriodInfo).filter(Boolean);
      if (view === "annual") {
        return infos
          .filter(info => info.startsYear && info.quarter === 4)
          .sort((a, b) => a.year - b.year)
          .map(info => info.record);
      }
      return pickOnePerQuarter(infos.filter(info => !info.startsYear || info.quarter === 1))
        .map(info => info.record);
    }

    function periodKeyFromInfo(info) {
      if (!info) return "";
      return `${info.year}-T${info.quarter}-${info.startsYear ? "ytd" : "q"}`;
    }

    function compactQuarterLabel(year, quarter) {
      return `${quarter}T${String(year).slice(-2)}`;
    }

    function statementPeriodKey(period, company, view) {
      const info = periodInfo(period, company);
      if (!info) return "";
      const startsYear = view === "annual" ? true : info.startsYear;
      return `${info.year}-T${info.quarter}-${startsYear ? "ytd" : "q"}`;
    }

    function indicatorRecordsMap(ticker, view) {
      const records = filterIndicatorRecords(DATA.indicators?.indicadores?.companies?.[ticker]?.periodos || [], view);
      return Object.fromEntries(records.map(record => [periodKeyFromInfo(recordPeriodInfo(record)), record]));
    }

    function cycleRecordsMap(ticker, view) {
      const records = filterIndicatorRecords(DATA.indicators?.ciclo_financeiro?.companies?.[ticker] || [], view);
      return Object.fromEntries(records.map(record => [periodKeyFromInfo(recordPeriodInfo(record)), record]));
    }

    function valueForView(row, basePeriods, period, statementKey, view, deriveQuarter) {
      const current = row.values?.[period];
      if (current === null || current === undefined || current === "") return null;
      if (view !== "quarterly" || statementKey === "balanco" || !deriveQuarter) return current;
      const info = periodInfo(period, null);
      if (!info || info.quarter === 1) return current;
      const previous = basePeriods
        .map(period => periodInfo(period, null))
        .filter(candidate => candidate && candidate.year === info.year && candidate.date < info.date)
        .sort((a, b) => b.date - a.date)[0];
      const previousValue = previous ? row.values?.[previous.period] : null;
      return typeof current === "number" && typeof previousValue === "number" ? current - previousValue : current;
    }

    function renderTabs() {
      const mainTabs = document.getElementById("main-tabs");
      mainTabs.innerHTML = "";
      Object.keys(mainLabels).forEach(key => {
        mainTabs.appendChild(button(mainLabels[key], key === currentMain, () => {
          currentMain = key;
          render();
        }));
      });

      const companyTabs = document.getElementById("company-tabs");
      companyTabs.innerHTML = "";
      companyTabs.style.display = currentMain === "dados" || currentMain === "auditoria" ? "flex" : "none";
      DATA.tickers.forEach(ticker => {
        companyTabs.appendChild(button(ticker, ticker === currentTicker, () => {
          currentTicker = ticker;
          render();
        }));
      });

      const statementTabs = document.getElementById("statement-tabs");
      statementTabs.innerHTML = "";
      statementTabs.style.display = currentMain === "dados" ? "flex" : "none";
      Object.keys(labels).forEach(key => {
        statementTabs.appendChild(button(labels[key], key === currentStatement, () => {
          currentStatement = key;
          render();
        }));
      });
    }

    function renderViewTabs(company) {
      const viewTabs = document.getElementById("view-tabs");
      viewTabs.innerHTML = "";
      viewTabs.style.display = currentMain === "dados" ? "flex" : "none";
      const supported = ["dashboard", "operacional"].includes(currentStatement)
        ? ["annual", "quarterly"]
        : periodsByView(currentStatement, company, currentView).supported;
      if (!supported.includes(currentView)) currentView = supported[0];
      supported.forEach(key => {
        viewTabs.appendChild(button(viewLabels[key], key === currentView, () => {
          currentView = key;
          render();
        }));
      });
      if (!window.__STATIC_DATA__) {
        viewTabs.appendChild(button("Recarregar JSONs", false, isRemoteConfigured() ? refreshRemoteData : loadData));
        const exportButton = button("Exportar HTML", false, () => {
          window.location.href = "/export/dashboard.html";
        });
        viewTabs.appendChild(exportButton);
        renderUpdateButtons().forEach(updateButton => viewTabs.appendChild(updateButton));
      }
    }

    function dashboardRecords(ticker, view) {
      return filterIndicatorRecords(DATA.indicators?.indicadores?.companies?.[ticker]?.periodos || [], view);
    }

    function latestByDate(records) {
      return (records || [])
        .map(record => ({ record, info: recordPeriodInfo(record) }))
        .filter(item => item.info)
        .sort((a, b) => b.info.date - a.info.date)[0]?.record || null;
    }

    function cagr(first, last, years) {
      if (typeof first !== "number" || typeof last !== "number" || first <= 0 || last <= 0 || years <= 0) return null;
      return (Math.pow(last / first, 1 / years) - 1) * 100;
    }

    function cagrPeriodSuffix(firstInfo, lastInfo) {
      const firstYear = Number(firstInfo?.year);
      const lastYear = Number(lastInfo?.year);
      if (!Number.isFinite(firstYear) || !Number.isFinite(lastYear)) return "";
      return ` ${firstYear}–${lastYear}`;
    }

    function dashboardAnnualRecords(ticker) {
      return dashboardRecords(ticker, "annual")
        .map(record => ({ record, info: recordPeriodInfo(record) }))
        .filter(item => item.info)
        .sort((a, b) => a.info.year - b.info.year)
        .map(item => item.record);
    }

    function renderSummaryTable(ticker) {
      const annual = dashboardAnnualRecords(ticker);
      const first = annual[0];
      const last = annual[annual.length - 1];
      const firstInfo = recordPeriodInfo(first);
      const lastInfo = recordPeriodInfo(last);
      const years = firstInfo && lastInfo ? lastInfo.year - firstInfo.year : 0;
      const cagrPeriod = cagrPeriodSuffix(firstInfo, lastInfo);
      const market = DATA.indicators?.market_cap?.companies?.[ticker];
      const netDebt = latestByDate(DATA.indicators?.divida_liquida?.companies?.[ticker] || []);
      const latestEbitda = last?.ebitda;
      const latestWorkingCapital = latestByDate(DATA.indicators?.indicadores?.companies?.[ticker]?.periodos || []);
      const ev = typeof market?.market_cap === "number" && typeof netDebt?.value === "number"
        ? market.market_cap + netDebt.value
        : null;
      const evEbitda = typeof ev === "number" && typeof latestEbitda === "number" && latestEbitda !== 0
        ? ev / latestEbitda
        : null;
      const rows = [
        [`CAGR receitas${cagrPeriod} (%)`, formatPercent(cagr(first?.receita_liquida, last?.receita_liquida, years))],
        [`CAGR lucros${cagrPeriod} (%)`, formatPercent(cagr(first?.lucro_liquido, last?.lucro_liquido, years))],
        ["Dívida líquida (R$ mi)", formatMillions(netDebt?.value)],
        ["Capital de giro (R$ mi)", formatMillions(latestWorkingCapital?.capital_giro)],
        ["Capital de giro / receita (%)", formatPercent(latestWorkingCapital?.capital_giro_percentual_receita)],
        ["EV/EBITDA LTM atual (x)", evEbitda === null ? "" : evEbitda.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })],
      ];
      const body = rows.map(([label, value]) => `<tr><td class="desc">${escapeHtml(label)}</td><td class="num">${escapeHtml(value)}</td></tr>`).join("");
      return `<h2>Resumo</h2><div class="table-wrap"><table>${matrixColgroup(1)}<thead><tr><th>Indicador</th><th>Valor</th></tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function renderQuote(ticker) {
      const quote = DATA.indicators?.market_cap?.companies?.[ticker];
      const el = document.getElementById("quote");
      if (!el) return;
      if (!quote || typeof quote.ultimo_preco !== "number") {
        el.innerHTML = `
          <div class="quote-logo-card"><img src="/logos/${escapeHtml(ticker)}.png" alt="${escapeHtml(ticker)}"></div>
          <div class="quote-price-card"><strong>${escapeHtml(ticker)}</strong><span>Cotação indisponível</span></div>
        `;
        return;
      }
      el.innerHTML = `
        <div class="quote-logo-card"><img src="/logos/${escapeHtml(ticker)}.png" alt="${escapeHtml(ticker)}"></div>
        <div class="quote-price-card">
          <strong>${escapeHtml(ticker)} ${escapeHtml(quote.ultimo_preco.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }))}</strong>
          <div>30 dias: ${escapeHtml(formatPercent(quote.variacao_30d_pct))}%</div>
          <div>360 dias: ${escapeHtml(formatPercent(quote.variacao_360d_pct))}%</div>
        </div>
      `;
    }

    function chartPointLabel(record) {
      const info = recordPeriodInfo(record);
      if (!info) return record?.periodo || "";
      return info.startsYear && info.quarter === 4 ? String(info.year) : compactQuarterLabel(info.year, info.quarter);
    }

    function renderSecondarySeriesTable(label, data) {
      if (!data.length) return "";
      const headers = ["", ...data.map(item => item.label)]
        .map(value => `<th>${escapeHtml(value)}</th>`)
        .join("");
      const values = [
        `<td>${escapeHtml(label)}</td>`,
        ...data.map(item => `<td class="num">${escapeHtml(formatPercent(item.margin))}%</td>`),
      ].join("");
      return `<div class="table-wrap series-table"><table><thead><tr>${headers}</tr></thead><tbody><tr>${values}</tr></tbody></table></div>`;
    }

    function renderPyplotChart(chartKey, title, ticker, view) {
      const staticKey = `${ticker}|${view}|${chartKey}`;
      const assetKey = `${view}_${chartKey}`;
      const remoteAsset = DATA.chart_assets?.individual?.[ticker]?.[assetKey]?.url;
      const localVersion = DATA.chart_assets?.version || DATA.files?.indicadores?.modified_at || "";
      const dynamicSrc = DATA.data_source_mode === "local"
        ? `/chart/${encodeURIComponent(ticker)}/${encodeURIComponent(view)}/${encodeURIComponent(chartKey)}${localVersion ? `?v=${encodeURIComponent(localVersion)}` : ""}`
        : "";
      const src = window.__STATIC_CHARTS__?.[staticKey] || remoteAsset || dynamicSrc;
      if (!src) {
        return `<h2>${escapeHtml(title)}</h2><div class="empty">Gráfico indisponível para esta atualização.</div>`;
      }
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><img class="chart-img" src="${src}" loading="lazy" alt="${escapeHtml(title)}"></div>`;
    }

    function renderComboChart(title, records, valueGetter, marginGetter, secondaryLabel = "Margem (%)") {
      const data = records.map(record => ({
        label: chartPointLabel(record),
        value: valueGetter(record),
        margin: marginGetter(record),
      })).filter(item => typeof item.value === "number" && typeof item.margin === "number");
      if (!data.length) return "";

      const width = Math.max(820, data.length * 112 + 160);
      const height = data.length > 8 ? 360 : 320;
      const left = 92;
      const right = 58;
      const top = 42;
      const bottom = 54;
      const plotW = width - left - right;
      const plotH = height - top - bottom;
      const rawMinValue = Math.min(0, ...data.map(item => item.value));
      const rawMaxValue = Math.max(0, ...data.map(item => item.value));
      const rawMinMargin = Math.min(0, ...data.map(item => item.margin));
      const rawMaxMargin = Math.max(0, ...data.map(item => item.margin));
      const valuePad = Math.max(1, (rawMaxValue - rawMinValue) * 0.18);
      const marginPad = Math.max(1, (rawMaxMargin - rawMinMargin) * 0.22);
      const crossesValueZero = data.some(item => item.value < 0) && data.some(item => item.value > 0);
      const crossesMarginZero = data.some(item => item.margin < 0) && data.some(item => item.margin > 0);
      const minValue = crossesValueZero ? rawMinValue - valuePad : Math.min(0, rawMinValue - valuePad);
      const maxValue = rawMaxValue + valuePad;
      let minMargin = crossesMarginZero ? rawMinMargin - marginPad : Math.min(0, rawMinMargin - marginPad);
      let maxMargin = rawMaxMargin + marginPad;
      const valueSpan = maxValue === minValue ? 1 : maxValue - minValue;
      const zeroRatio = (maxValue - 0) / valueSpan;
      if (zeroRatio > 0 && zeroRatio < 1) {
        const upperNeeded = Math.max(maxMargin, Math.abs(minMargin) * zeroRatio / (1 - zeroRatio));
        const lowerNeeded = Math.max(Math.abs(minMargin), upperNeeded * (1 - zeroRatio) / zeroRatio);
        maxMargin = upperNeeded;
        minMargin = -lowerNeeded;
      }
      const marginSpan = maxMargin === minMargin ? 1 : maxMargin - minMargin;
      const xStep = plotW / data.length;
      const barW = Math.min(34, xStep * 0.38);
      const valueY = value => top + (maxValue - value) / valueSpan * plotH;
      const marginY = value => top + (maxMargin - value) / marginSpan * plotH;
      const zeroY = valueY(0);
      const xAxisY = zeroY;
      const points = data.map((item, index) => ({
        x: left + index * xStep + xStep / 2,
        y: marginY(item.margin),
        item,
      }));
      const line = points.map(point => `${point.x},${point.y}`).join(" ");
      const bars = data.map((item, index) => {
        const x = left + index * xStep + (xStep - barW) / 2;
        const y = valueY(Math.max(item.value, 0));
        const h = Math.max(1, Math.abs(valueY(item.value) - xAxisY));
        const barY = item.value >= 0 ? Math.min(valueY(item.value), xAxisY) : xAxisY;
        return `<rect x="${x}" y="${barY}" width="${barW}" height="${h}" fill="#23AC81"></rect>`;
      }).join("");
      const barLabels = data.map((item, index) => {
        const x = left + index * xStep + xStep / 2;
        const h = Math.max(1, Math.abs(valueY(item.value) - xAxisY));
        const barY = item.value >= 0 ? Math.min(valueY(item.value), xAxisY) : xAxisY;
        const y = item.value >= 0 ? barY + 14 : barY + h - 6;
        return `<text x="${x}" y="${y}" text-anchor="middle" font-size="10" fill="#F4F1E6" font-weight="700">${escapeHtml(formatMillions(item.value))}</text>`;
      }).join("");
      const labels = data.map((item, index) => {
        const x = left + index * xStep + xStep / 2;
        return `<text x="${x}" y="${height - 18}" text-anchor="middle" font-size="11">${escapeHtml(item.label)}</text>`;
      }).join("");
      const dots = points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="4" fill="#006341"><title>${escapeHtml(formatPercent(point.item.margin))}%</title></circle>`).join("");
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><svg width="${width}" height="${height}" role="img" aria-label="${escapeHtml(title)}">
        <line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" stroke="#DDD5B3"></line>
        <line x1="${width - right}" y1="${top}" x2="${width - right}" y2="${height - bottom}" stroke="#DDD5B3"></line>
        <line x1="${left}" y1="${xAxisY}" x2="${width - right}" y2="${xAxisY}" stroke="#d8d0b0"></line>
        ${bars}${barLabels}
        <polyline points="${line}" fill="none" stroke="#006341" stroke-width="2"></polyline>
        ${dots}${labels}
      </svg></div>${renderSecondarySeriesTable(secondaryLabel, data)}`;
    }

    function renderSingleLineChart(title, records, valueGetter, formatter = formatNumber) {
      const data = records.map(record => ({
        label: chartPointLabel(record),
        value: valueGetter(record),
      })).filter(item => typeof item.value === "number" && Number.isFinite(item.value));
      if (!data.length) return "";

      const width = Math.max(820, data.length * 112 + 160);
      const height = 260;
      const left = 104;
      const right = 56;
      const top = 42;
      const bottom = 54;
      const plotW = width - left - right;
      const plotH = height - top - bottom;
      const rawMinValue = Math.min(0, ...data.map(item => item.value));
      const rawMaxValue = Math.max(0, ...data.map(item => item.value));
      const pad = Math.max(1, (rawMaxValue - rawMinValue) * 0.22);
      const crossesZero = data.some(item => item.value < 0) && data.some(item => item.value > 0);
      const minValue = crossesZero ? rawMinValue - pad : Math.min(0, rawMinValue - pad);
      const maxValue = rawMaxValue + pad;
      const span = maxValue === minValue ? 1 : maxValue - minValue;
      const xStep = plotW / data.length;
      const y = value => top + (maxValue - value) / span * plotH;
      const xAxisY = y(0);
      const points = data.map((item, index) => ({
        x: left + index * xStep + xStep / 2,
        y: y(item.value),
        item,
      }));
      const line = points.map(point => `${point.x},${point.y}`).join(" ");
      const labels = points.map(point => `<text x="${point.x}" y="${height - 18}" text-anchor="middle" font-size="11">${escapeHtml(point.item.label)}</text>`).join("");
      const dots = points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="4" fill="#006341"><title>${escapeHtml(formatter(point.item.value))}</title></circle>`).join("");
      const lineLabels = points.map((point, index) => {
        const labelY = Math.max(top + 12, point.y - 10);
        const x = point.x + (index % 2 === 0 ? -10 : 10);
        return `<text x="${x}" y="${labelY}" text-anchor="middle" font-size="9" fill="#00513F" font-weight="700">${escapeHtml(formatter(point.item.value))}</text>`;
      }).join("");
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><svg width="${width}" height="${height}" role="img" aria-label="${escapeHtml(title)}">
        <line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" stroke="#DDD5B3"></line>
        <line x1="${left}" y1="${xAxisY}" x2="${width - right}" y2="${xAxisY}" stroke="#d8d0b0"></line>
        <polyline points="${line}" fill="none" stroke="#006341" stroke-width="2"></polyline>
        ${dots}${lineLabels}${labels}
      </svg></div>`;
    }

    function renderDashboard(ticker, view) {
      const records = dashboardRecords(ticker, view);
      const topGrid = `<div class="dashboard-grid"><section class="dashboard-card">${renderSummaryTable(ticker)}</section><section class="dashboard-card">${renderCycleMatrix(ticker, view)}</section></div>`;
      const comboData = (valueGetter, marginGetter) => records.map(record => ({
        label: chartPointLabel(record),
        value: valueGetter(record),
        margin: marginGetter(record),
      })).filter(item => typeof item.value === "number" && typeof item.margin === "number");
      const charts = [
        renderPyplotChart("ev_ebitda", "EV/EBITDA LTM histórico", ticker, view),
        renderPyplotChart("capital_giro", "Capital de giro e % da receita", ticker, view) + renderSecondarySeriesTable("CG / receita", comboData(row => row.capital_giro, row => row.capital_giro_percentual_receita)),
        renderPyplotChart("resultado_bruto", "Resultado bruto e margem bruta", ticker, view) + renderSecondarySeriesTable("Margem bruta", comboData(row => row.resultado_bruto, row => row.margens_percentual?.margem_bruta)),
        renderPyplotChart("ebit", "EBIT e margem operacional", ticker, view) + renderSecondarySeriesTable("Margem operacional", comboData(row => row.ebit, row => row.margens_percentual?.margem_operacional)),
        renderPyplotChart("ebitda", "EBITDA contábil calculado e margem", ticker, view) + renderSecondarySeriesTable("Margem EBITDA contábil", comboData(row => row.ebitda, row => row.margens_percentual?.margem_ebitda)),
        renderPyplotChart("lucro_liquido", "Lucro líquido e margem líquida", ticker, view) + renderSecondarySeriesTable("Margem líquida", comboData(row => row.lucro_liquido, row => row.margens_percentual?.margem_liquida)),
      ].filter(Boolean);
      const wideCharts = view === "quarterly" || records.length > 8;
      const chartsGrid = charts.length
        ? `<div class="charts-grid">${charts.map(chart => `<section class="chart-card${wideCharts ? " wide" : ""}">${chart}</section>`).join("")}</div>`
        : "";
      const sections = [topGrid, chartsGrid].filter(Boolean);
      return sections.length ? sections.join("") : '<div class="empty">Nenhum dado disponível para os gráficos.</div>';
    }

    function tableColgroup(periodCount) {
      return `<colgroup><col style="width:120px"><col style="width:360px">${Array.from({ length: periodCount }, () => '<col style="width:140px">').join("")}</colgroup>`;
    }

    function matrixColgroup(periodCount) {
      return `<colgroup><col style="width:480px">${Array.from({ length: periodCount }, () => '<col style="width:140px">').join("")}</colgroup>`;
    }

    function isDreCode(row, code) {
      return String(row.code || "").trim() === code;
    }

    function prefixedDescription(row, statementKey, periods, basePeriods, viewData, view) {
      const description = String(row.description || "");
      if (new RegExp("^\\\\((\\\\+|-|=|\\\\+/-)\\\\)\\\\s").test(description)) return description;
      if (!["dre", "dfc"].includes(statementKey)) return description;
      const code = String(row.code || "");
      const values = periods
        .map(period => rowValue(row, basePeriods, period, statementKey, view, viewData))
        .filter(value => typeof value === "number");
      const hasPositive = values.some(value => value > 0);
      const hasNegative = values.some(value => value < 0);
      let sign = hasPositive && hasNegative ? "+/-" : hasNegative ? "-" : "+";
      if (statementKey === "dre") {
        if (["3.02", "3.03", "3.05", "3.07", "3.09", "3.11"].some(root => code === root || code.startsWith(root + "."))) {
          sign = "=";
        } else if (["3.04", "3.06", "3.08", "3.10"].some(root => code === root || code.startsWith(root + "."))) {
          sign = "+/-";
        }
      }
      if (statementKey === "dfc" && (row.depth || 0) <= 1) {
        sign = "=";
      }
      return `(${sign}) ${description}`;
    }

    function dreAugmentedRows(rows, periods, company, view, viewData, basePeriods) {
      if (currentStatement !== "dre") return rows;
      const indicators = indicatorRecordsMap(currentTicker, view);
      const extraRows = [];
      rows.forEach(row => {
        extraRows.push(row);
        if (isDreCode(row, "3.02")) {
          extraRows.push({
            code: "",
            description: "(=) Margem bruta (%)",
            depth: (row.depth || 0) + 1,
            is_percent: true,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              return [period, indicators[key]?.margens_percentual?.margem_bruta];
            })),
          });
        }
        if (isDreCode(row, "3.05")) {
          extraRows.push({
            code: "",
            description: "(=) Margem operacional (%)",
            depth: (row.depth || 0) + 1,
            is_percent: true,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              return [period, indicators[key]?.margens_percentual?.margem_operacional];
            })),
          });
          extraRows.push({
            code: "",
            description: "(+) Depreciação e amortização do período",
            depth: (row.depth || 0) + 1,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              const value = indicators[key]?.depreciacao_amortizacao;
              return [period, typeof value === "number" ? Math.abs(value) : value];
            })),
          });
          extraRows.push({
            code: "",
            description: "(=) EBITDA contábil calculado",
            depth: (row.depth || 0) + 1,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              return [period, indicators[key]?.ebitda];
            })),
          });
          extraRows.push({
            code: "",
            description: "(=) Margem EBITDA contábil (%)",
            depth: (row.depth || 0) + 1,
            is_percent: true,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              return [period, indicators[key]?.margens_percentual?.margem_ebitda];
            })),
          });
          extraRows.push({
            code: "",
            description: "(-) Depreciação e amortização do período",
            depth: (row.depth || 0) + 1,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              const value = indicators[key]?.depreciacao_amortizacao;
              return [period, typeof value === "number" ? -Math.abs(value) : value];
            })),
          });
        }
        if (isDreCode(row, "3.11")) {
          extraRows.push({
            code: "",
            description: "(=) Margem líquida (%)",
            depth: (row.depth || 0) + 1,
            is_percent: true,
            is_aggregator: true,
            values: Object.fromEntries(periods.map(period => {
              const key = statementPeriodKey(period, company, view);
              return [period, indicators[key]?.margens_percentual?.margem_liquida];
            })),
          });
        }
      });
      return extraRows;
    }

    function selectedRows(company, statementKey, view) {
      const basePeriods = company.periods || [];
      const viewData = periodsByView(statementKey, company, view);
      const periods = viewData.periods;
      const rows = dreAugmentedRows(company.rows || [], periods, company, view, viewData, basePeriods).filter(row =>
        periods.some(period => {
          const value = row.is_percent
            ? row.values?.[period]
            : valueForView(row, basePeriods, period, statementKey, view, viewData.deriveQuarter);
          return value !== null && value !== undefined && value !== "";
        })
      );
      return { basePeriods, viewData, periods, rows };
    }

    function renderTable(company, statementKey, view) {
      const { basePeriods, viewData, periods, rows } = selectedRows(company, statementKey, view);
      if (!periods.length) return '<div class="empty">Sem período disponível para esta seleção.</div>';
      if (!rows.length) return '<div class="empty">Sem dados para esta seleção.</div>';
      const headers = ["Código", "Descrição", ...periods.map(period => viewData.labels[period] || period)]
        .map(h => `<th>${escapeHtml(h)}</th>`)
        .join("");
      const visibleRows = rows.filter(row => isRowVisibleByToggle(row, statementKey, rows));
      const body = visibleRows.map(row => {
        const indent = Math.min(row.depth || 0, 8) * 16;
        const rowClass = row.is_aggregator || (row.depth || 0) <= 1 ? "aggregator" : "";
        const canToggle = hasToggleChildren(row, rows);
        const expanded = expandedRows.has(expansionKey(statementKey, currentTicker, row.code));
        const toggle = canToggle
          ? `<button class="row-toggle" title="${expanded ? "Ocultar detalhes" : "Mostrar detalhes"}" onclick="toggleRow('${escapeHtml(statementKey)}','${escapeHtml(currentTicker)}','${escapeHtml(row.code)}')">${expanded ? "−" : "+"}</button>`
          : "";
        const values = periods
          .map(period => {
            const value = row.is_percent
              ? row.values?.[period]
              : valueForView(row, basePeriods, period, statementKey, view, viewData.deriveQuarter);
            const formatted = row.is_percent ? formatPercent(value) : formatMillions(value);
            return `<td class="num">${escapeHtml(formatted)}</td>`;
          })
          .join("");
        const description = prefixedDescription(row, statementKey, periods, basePeriods, viewData, view);
        return `<tr class="${rowClass}"><td>${escapeHtml(row.code)}</td><td class="desc" style="padding-left:${indent + 8}px">${toggle}${escapeHtml(description)}</td>${values}</tr>`;
      }).join("");
      return `<div class="table-wrap"><table class="statement-table">${tableColgroup(periods.length)}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function operationalMetricItem(ticker, metricName) {
      const items = DATA.operational?.companies?.[ticker]?.metricas?.[metricName] || [];
      return items.find(item => item?.serie && Object.keys(item.serie).length) || null;
    }

    function operationalMoneyToMillions(value, unit) {
      if (typeof value !== "number") return value;
      const normalizedUnit = String(unit || "").toLowerCase();
      if (normalizedUnit.includes("milh")) return value;
      if (normalizedUnit.includes("milhar")) return value / 1000;
      return Math.abs(value) > 100000 ? value / 1000000 : value;
    }

    function renderOperationalDreTable(company, view) {
      const viewData = periodsByView("dre", company, view);
      const periods = viewData.periods || [];
      if (!periods.length) return "";
      const receita = operationalMetricItem(currentTicker, "Receita Bruta");
      const glosa = operationalMetricItem(currentTicker, "Glosa/PCLD");
      const labelsByPeriod = Object.fromEntries(periods.map(period => [period, viewData.labels[period] || period]));
      const valueFor = (item, period) => {
        if (!item) return null;
        const label = labelsByPeriod[period];
            const raw = item.serie?.[label] ?? item.serie?.[period];
            return operationalMoneyToMillions(raw, item.unidade);
      };
      const rows = [
        {
          code: "",
          description: "(+) Receita Bruta",
          isPercent: false,
          values: periods.map(period => valueFor(receita, period)),
        },
        {
          code: "",
          description: "(-) Glosa e PCLD",
          isPercent: false,
          values: periods.map(period => valueFor(glosa, period)),
        },
        {
          code: "",
          description: "(=) Glosa/PCLD / Receita Bruta (%)",
          isPercent: true,
          values: periods.map(period => {
            const revenue = valueFor(receita, period);
            const deductions = valueFor(glosa, period);
            return typeof revenue === "number" && revenue !== 0 && typeof deductions === "number"
              ? deductions / revenue * 100
              : null;
          }),
        },
      ];
      const headers = ["Código", "Descrição", ...periods.map(period => labelsByPeriod[period])]
        .map(h => `<th>${escapeHtml(h)}</th>`)
        .join("");
      const body = rows.map(row => {
        const values = row.values.map(value => {
          const formatted = row.isPercent ? formatPercent(value) : formatNumber(value);
          return `<td class="num">${escapeHtml(formatted)}</td>`;
        }).join("");
        return `<tr class="aggregator"><td>${escapeHtml(row.code)}</td><td class="desc">${escapeHtml(row.description)}</td>${values}</tr>`;
      }).join("");
      return `<h2>Receita Bruta e Glosa/PCLD</h2><div class="table-wrap"><table class="statement-table">${tableColgroup(periods.length)}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function renderFlatTable(title, records, columns) {
      const visible = (records || []).filter(row =>
        columns.slice(1).some(col => {
          const value = col.get ? col.get(row) : row[col.key];
          return value !== null && value !== undefined && value !== "";
        })
      );
      if (!visible.length) return "";
      const headers = columns.map(col => `<th>${escapeHtml(col.label)}</th>`).join("");
      const body = visible.map(row => {
        const cells = columns.map(col => {
          const value = col.get ? col.get(row) : row[col.key];
          const cls = typeof value === "number" ? "num" : "";
          const formatted = col.format === "percent" ? formatPercent(value) : formatNumber(value);
          return `<td class="${cls}">${escapeHtml(formatted)}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
      }).join("");
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><table>${matrixColgroup(records.length)}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function indicatorPeriodLabel(record) {
      const info = recordPeriodInfo(record);
      if (!info) return record?.periodo?.dre || record?.periodo || record?.date || "";
      return info.startsYear && info.quarter === 4 ? String(info.year) : compactQuarterLabel(info.year, info.quarter);
    }

    function renderIndicatorMatrix(title, records, metrics) {
      if (!records?.length) return "";
      const visibleMetrics = metrics.filter(metric =>
        records.some(record => {
          const value = metric.get(record);
          return value !== null && value !== undefined && value !== "";
        })
      );
      if (!visibleMetrics.length) return "";
      const headers = ["Indicador", ...records.map(indicatorPeriodLabel)]
        .map(h => `<th>${escapeHtml(h)}</th>`)
        .join("");
      const body = visibleMetrics.map(metric => {
        const values = records.map(record => {
          const value = metric.get(record);
          const formatted = metric.format === "percent" ? formatPercent(value) : formatNumber(value);
          const cls = typeof value === "number" ? "num" : "";
          return `<td class="${cls}">${escapeHtml(formatted)}</td>`;
        }).join("");
        return `<tr><td class="desc">${escapeHtml(metric.label)}</td>${values}</tr>`;
      }).join("");
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><table><thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function rowValue(row, basePeriods, period, statementKey, view, viewData) {
      if (row.is_percent) return row.values?.[period];
      return valueForView(row, basePeriods, period, statementKey, view, viewData.deriveQuarter);
    }

    function analysisBaseValue(rows, periods, basePeriods, period, statementKey, view, viewData, row) {
      if (statementKey === "dre") {
        const receita = rows.find(candidate => candidate.code === "3.01");
        return receita ? rowValue(receita, basePeriods, period, statementKey, view, viewData) : null;
      }
      const sideCode = String(row.code || "").startsWith("2") ? "2" : "1";
      const total = rows.find(candidate => String(candidate.code || "") === sideCode);
      return total ? rowValue(total, basePeriods, period, statementKey, view, viewData) : null;
    }

    function renderAvAhTable(company, statementKey, view) {
      if (!["balanco", "dre"].includes(statementKey)) return "";
      const { basePeriods, viewData, periods, rows } = selectedRows(company, statementKey, view);
      if (!periods.length || !rows.length) return "";
      const headers = ["Código", "Descrição", ...periods.map(period => viewData.labels[period] || period)]
        .map(h => `<th>${escapeHtml(h)}</th>`)
        .join("");
      const visibleRows = rows.filter(row => isRowVisibleByToggle(row, statementKey, rows));
      const body = visibleRows.map(row => {
        const indent = Math.min(row.depth || 0, 8) * 16;
        const rowClass = row.is_aggregator || (row.depth || 0) <= 1 ? "aggregator" : "";
        const canToggle = hasToggleChildren(row, rows);
        const expanded = expandedRows.has(expansionKey(statementKey, currentTicker, row.code));
        const toggle = canToggle
          ? `<button class="row-toggle" title="${expanded ? "Ocultar detalhes" : "Mostrar detalhes"}" onclick="toggleRow('${escapeHtml(statementKey)}','${escapeHtml(currentTicker)}','${escapeHtml(row.code)}')">${expanded ? "−" : "+"}</button>`
          : "";
        const values = periods.map((period, index) => {
          if (row.is_percent) return '<td class="num"></td>';
          const value = rowValue(row, basePeriods, period, statementKey, view, viewData);
          const base = analysisBaseValue(rows, periods, basePeriods, period, statementKey, view, viewData, row);
          const previousPeriod = periods[index - 1];
          const previousValue = previousPeriod
            ? rowValue(row, basePeriods, previousPeriod, statementKey, view, viewData)
            : null;
          const av = typeof value === "number" && typeof base === "number" && base !== 0 ? value / base * 100 : null;
          const ah = typeof value === "number" && typeof previousValue === "number" && previousValue !== 0
            ? (value / previousValue - 1) * 100
            : null;
          const text = `${formatPercent(av)} / ${formatPercent(ah)}`;
          return `<td class="num">${escapeHtml(text)}</td>`;
        }).join("");
        const description = prefixedDescription(row, statementKey, periods, basePeriods, viewData, view);
        return `<tr class="${rowClass}"><td>${escapeHtml(row.code)}</td><td class="desc" style="padding-left:${indent + 8}px">${toggle}${escapeHtml(description)}</td>${values}</tr>`;
      }).join("");
      return `<h2>AV / AH (%)</h2><div class="table-wrap"><table class="statement-table">${tableColgroup(periods.length)}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function renderCycleMatrix(ticker, view) {
      const cycleRecords = filterIndicatorRecords(DATA.indicators?.ciclo_financeiro?.companies?.[ticker] || [], view);
      return renderIndicatorMatrix("Ciclo financeiro", cycleRecords, [
        { label: "PMR", get: row => row.indicadores_dias?.PMR },
        { label: "PME", get: row => row.indicadores_dias?.PME },
        { label: "PMP", get: row => row.indicadores_dias?.PMP },
        { label: "Ciclo financeiro", get: row => row.indicadores_dias?.ciclo_financeiro },
      ]);
    }

    function operationalPeriodInfo(period) {
      const text = String(period || "").trim();
      const annual = text.match(/^20(\\d{2})$/);
      if (annual) {
        const year = Number(text);
        return { period: text, year, quarter: 4, annual: true, sort: year * 10 + 5, label: text };
      }
      const quarterly = text.match(/^([1-4])T(\\d{2}|\\d{4})$/i);
      if (quarterly) {
        const quarter = Number(quarterly[1]);
        const year = Number(quarterly[2].length === 2 ? `20${quarterly[2]}` : quarterly[2]);
        return { period: text, year, quarter, annual: false, sort: year * 10 + quarter, label: `${quarter}T${String(year).slice(-2)}` };
      }
      return { period: text, year: 0, quarter: 0, annual: false, sort: 0, label: text };
    }

    function operationalRows(company, view) {
      const metricas = company?.metricas || {};
      const defaultMetrics = [
        "Ticket Médio",
        "N. Atendimentos",
        "N. Unidades",
        "N. Pacientes",
      ];
      const selectedMetrics = defaultMetrics;
      return selectedMetrics.map(metric => {
        const items = metricas[metric] || [];
        const validItems = (items || []).filter(candidate => candidate?.confidence !== "low");
        const item = validItems.find(candidate => candidate?.serie && Object.keys(candidate.serie).length) || validItems[0] || null;
        const values = {};
        if (item?.serie) {
          Object.entries(item.serie).forEach(([period, value]) => {
            const info = operationalPeriodInfo(period);
            if (view === "annual" && !info.annual) return;
            if (view === "quarterly" && info.annual) return;
            values[period] = value;
          });
        }
        return {
          metric,
          source: item?.escopo || item?.fonte_linha || "",
          unit: item?.unidade || "",
          calculated: Boolean(item?.calculado),
          values,
          order: 0,
        };
      });
    }

    function fixedOperationalPeriods(_company, view) {
      const periods = new Set();
      Object.values(DATA.operational?.companies || {}).forEach(company => {
        const metricas = company?.metricas || {};
        Object.entries(metricas).forEach(([metric, items]) => {
        (items || []).filter(item => String(item?.confidence || "").toLowerCase() !== "low").forEach((item, index) => {
          const serie = item?.serie || {};
          Object.entries(serie).forEach(([period, value]) => {
            const info = operationalPeriodInfo(period);
            if (view === "annual" && info.annual) periods.add(period);
            if (view === "quarterly" && !info.annual) periods.add(period);
          });
        });
      });
      });
      const sorted = Array.from(periods).map(operationalPeriodInfo).sort((a, b) => a.sort - b.sort);
      const currentYear = new Date().getFullYear();
      if (view === "annual") {
        const annual = sorted.slice(-5).map(info => info.period);
        return annual.length ? annual : Array.from({ length: 5 }, (_, i) => String(currentYear - 4 + i));
      }
      const latestYears = Array.from(new Set(sorted.map(info => info.year))).filter(Boolean).sort((a, b) => a - b).slice(-5);
      const quarterly = sorted.filter(info => latestYears.includes(info.year)).map(info => info.period);
      return quarterly.length ? quarterly : Array.from({ length: 20 }, (_, i) => {
        const year = currentYear - 4 + Math.floor(i / 4);
        const quarter = i % 4 + 1;
        return `${quarter}T${String(year).slice(-2)}`;
      });
    }

    function operationalRowsResolved(company, view) {
      const metricas = company?.metricas || {};
      return operationalMetrics.map(metric => {
        const items = metricas[metric] || [];
        const values = {};
        const meta = {};
        const priority = item => {
          const confidence = String(item?.confidence || "").toLowerCase();
          if (confidence === "high") return 3;
          if (confidence === "medium") return 2;
          if (item?.manual || item?.confidence === "MANUAL") return 1;
          return 0;
        };
        const validItems = (items || []).filter(candidate => String(candidate?.confidence || "").toLowerCase() !== "low");
        validItems.forEach(item => {
          Object.entries(item?.serie || {}).forEach(([period, value]) => {
            const info = operationalPeriodInfo(period);
            if (view === "annual" && !info.annual) return;
            if (view === "quarterly" && info.annual) return;
            const existing = meta[period];
            if (!existing || priority(item) > priority(existing.item)) {
              values[period] = value;
              meta[period] = { item };
            }
          });
        });
        const item = validItems.find(candidate => candidate?.serie && Object.keys(candidate.serie).length) || validItems[0] || null;
        return {
          metric,
          source: item?.escopo || item?.fonte_linha || "",
          unit: item?.unidade || "",
          calculated: Boolean(item?.calculado),
          manualByPeriod: Object.fromEntries(Object.entries(meta).map(([period, entry]) => [period, Boolean(entry.item?.manual || entry.item?.confidence === "MANUAL")])),
          values,
          order: 0,
        };
      });
    }

    function formatOperationalValue(value, unit) {
      if (value === null || value === undefined || value === "") return "";
      if (typeof value !== "number") return value;
      const normalizedUnit = String(unit || "").toLowerCase();
      if (normalizedUnit.includes("fra") || normalizedUnit.includes("%")) {
        const percent = Math.abs(value) <= 1 ? value * 100 : value;
        return `${formatPercent(percent)}%`;
      }
      if (normalizedUnit.includes("r$")) {
        return value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
      }
      return value.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
    }

    function renderOperationalTable(ticker, view) {
      let company = DATA.operational?.companies?.[ticker];
      if (!company) company = { metricas: {} };
      const rows = operationalRowsResolved(company, view);
      const periods = fixedOperationalPeriods(company, view);
      const labelsByPeriod = Object.fromEntries(periods.map(period => [period, operationalPeriodInfo(period).label]));
      const headers = ["Indicador", "Escopo / fonte", "Unidade", ...periods.map(period => labelsByPeriod[period])]
        .map(value => `<th>${escapeHtml(value)}</th>`)
        .join("");
      const body = rows.map(row => {
        const values = periods.map(period => {
          const isManual = row.manualByPeriod?.[period];
          const title = isManual ? ' title="Valor inserido manualmente. Será substituído automaticamente caso o extrator encontre esta métrica/período com confiança média ou alta."' : "";
          const badge = isManual ? '<span class="manual-badge">Manual</span>' : "";
          const cls = isManual ? "num manual-value" : "num";
          return `<td class="${cls}"${title}>${escapeHtml(formatOperationalValue(row.values[period], row.unit))}${badge}</td>`;
        }).join("");
        const source = row.calculated ? `${row.source} (calculado)` : row.source;
        return `<tr><td class="desc">${escapeHtml(row.metric)}</td><td class="desc">${escapeHtml(source)}</td><td>${escapeHtml(row.unit)}</td>${values}</tr>`;
      }).join("");
      const colgroup = `<colgroup><col style="width:220px"><col style="width:300px"><col style="width:150px">${periods.map(() => '<col style="width:130px">').join("")}</colgroup>`;
      const disclaimer = '<div class="disclaimer"><strong>Aviso:</strong> os dados operacionais são capturados de forma experimental a partir de planilhas de fundamentos, releases e documentos convertidos para Markdown. Eles podem estar incompletos, classificados incorretamente ou conter erros de leitura. Use estes dados como apoio exploratório e valide contra os documentos originais antes de qualquer decisão.</div>';
      const manualToolbar = window.__STATIC_DATA__ ? "" : '<div class="manual-toolbar"><button class="update-button" onclick="openManualModal()">Adicionar dado manual</button></div>';
      return `<h2>Dados Operacionais</h2>${disclaimer}${manualToolbar}<div class="table-wrap"><table class="fixed-layout operational-table">${colgroup}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>${renderOperationalWarnings(company)}${renderManualAudit(company)}`;
    }

    function renderOperationalWarnings(company) {
      const warnings = company?.warnings || [];
      if (!warnings.length) return "";
      const rows = warnings.map(item => {
        const status = item.status === "not_found" ? "Não encontrado" : item.status === "medium_confidence" ? "Confiança média" : item.status === "low_confidence_rejected" ? "LOW rejeitado" : item.status;
        return `<tr><td class="desc">${escapeHtml(item.metric || "")}</td><td>${escapeHtml(status)}</td><td class="desc">${escapeHtml(item.message || "")}</td></tr>`;
      }).join("");
      return `<h3>Avisos sobre os dados operacionais</h3><div class="table-wrap"><table class="fixed-layout operational-table"><colgroup><col style="width:220px"><col style="width:160px"><col style="width:620px"></colgroup><thead><tr><th>Indicador</th><th>Status</th><th>Mensagem</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    function renderManualAudit(company) {
      const ticker = company?.ticker || currentTicker;
      const overrides = (DATA.manual_operational?.overrides || []).filter(item => item.ticker === ticker);
      if (!overrides.length) return "";
      const rows = overrides.map(item => {
        const status = item.status === "active" ? "MANUAL_ACTIVE" : item.status === "superseded" ? "MANUAL_SUPERSEDED" : item.status;
        const auto = item.automatic_confidence ? `${item.automatic_confidence}: ${formatOperationalValue(item.automatic_value, item.unit)}` : "";
        const actions = !window.__STATIC_DATA__ && item.status === "active"
          ? `<button onclick="editManualOverride('${escapeHtml(item.id)}')">Editar</button> <button onclick="deleteManualOverride('${escapeHtml(item.id)}')">Excluir</button>`
          : "";
        return `<tr><td>${escapeHtml(item.metric)}</td><td>${escapeHtml(item.period)}</td><td class="num">${escapeHtml(formatOperationalValue(item.value, item.unit))}</td><td>${escapeHtml(status)}</td><td>${escapeHtml(item.updated_at || "")}</td><td>${escapeHtml(auto)}</td><td>${actions}</td></tr>`;
      }).join("");
      return `<h3>Auditoria manual operacional</h3><div class="table-wrap"><table class="fixed-layout operational-table"><colgroup><col style="width:220px"><col style="width:120px"><col style="width:150px"><col style="width:170px"><col style="width:240px"><col style="width:180px"><col style="width:170px"></colgroup><thead><tr><th>Indicador</th><th>Período</th><th>Valor</th><th>Status</th><th>Atualizado em</th><th>Automático</th><th>Ações</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    function formatComparisonValue(value, format) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "N/A";
      if (format === "percent") return `${formatPercent(value)}%`;
      if (format === "signed_percent") return `${value >= 0 ? "+" : ""}${formatPercent(value)}%`;
      if (format === "days") return `${value.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} dias`;
      if (format === "multiple") return `${value.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}x`;
      if (format === "integer") return value.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
      return value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
    }

    function comparisonCellHtml(cell, format, predominantPeriod = "") {
      const value = formatComparisonValue(cell?.value, format);
      const period = cell?.period && cell.period !== predominantPeriod ? `<div class="muted">${escapeHtml(cell.period)}</div>` : "";
      const confidence = cell?.confidence === "medium" ? '<div class="muted">Confiança média</div>' : "";
      const manual = cell?.confidence === "MANUAL" ? '<div class="manual-badge">Manual</div>' : "";
      const quality = cell?.quality?.status && !["validated", "ok"].includes(cell.quality.status)
        ? `<div class="muted">${escapeHtml(cell.quality.status)}</div>`
        : "";
      const title = [
        cell?.quality?.message,
        ...(cell?.quality?.warnings || []),
        cell?.source ? `Fonte: ${cell.source}` : "",
      ].filter(Boolean).join(" | ");
      return `<td class="num" title="${escapeHtml(title)}"><strong>${escapeHtml(value)}</strong>${period}${confidence}${manual}${quality}</td>`;
    }

    function normalizeComparisonSelection() {
      const available = DATA.tickers || [];
      const seen = new Set();
      comparisonSelectedTickers = comparisonSelectedTickers.filter(ticker => available.includes(ticker) && !seen.has(ticker) && seen.add(ticker));
      available.forEach(ticker => {
        if (comparisonSelectedTickers.length < Math.min(7, available.length) && !seen.has(ticker)) {
          comparisonSelectedTickers.push(ticker);
          seen.add(ticker);
        }
      });
      return comparisonSelectedTickers.slice(0, Math.min(7, available.length));
    }

    function comparisonTickerSelectHtml(selectedTicker, columnIndex) {
      const selected = new Set(normalizeComparisonSelection());
      const options = (DATA.tickers || [])
        .filter(ticker => ticker === selectedTicker || !selected.has(ticker))
        .map(ticker => `<option value="${escapeHtml(ticker)}"${ticker === selectedTicker ? " selected" : ""}>${escapeHtml(ticker)}</option>`)
        .join("");
      return `<select class="comparison-ticker-select" data-column="${columnIndex}" onchange="changeComparisonTicker(${columnIndex}, this.value)">${options}</select>`;
    }

    function changeComparisonTicker(columnIndex, ticker) {
      if (!DATA.tickers?.includes(ticker) || comparisonSelectedTickers.includes(ticker)) return;
      comparisonSelectedTickers[columnIndex] = ticker;
      render();
    }

    function renderComparisonTable() {
      const comparison = DATA.comparison || {};
      const tickers = normalizeComparisonSelection();
      const metrics = comparison.metrics || [];
      const headers = ["Métrica", ...tickers.map((ticker, index) => comparisonTickerSelectHtml(ticker, index))].map(value => `<th>${value}</th>`).join("");
      const body = metrics.map(metric => {
        const periods = tickers
          .map(ticker => comparison.companies?.[ticker]?.[metric.key]?.period)
          .filter(Boolean);
        const counts = periods.reduce((acc, period) => {
          acc[period] = (acc[period] || 0) + 1;
          return acc;
        }, {});
        const predominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
        const predominantPeriod = predominant && predominant[1] > periods.length / 2 ? predominant[0] : "";
        const label = predominantPeriod ? `${metric.label} (${predominantPeriod})` : metric.label;
        const cells = tickers.map(ticker => comparisonCellHtml(comparison.companies?.[ticker]?.[metric.key], metric.format, predominantPeriod)).join("");
        return `<tr><td class="desc">${escapeHtml(label)}</td>${cells}</tr>`;
      }).join("");
      const colgroup = `<colgroup><col style="width:260px">${tickers.map(() => '<col style="width:150px">').join("")}</colgroup>`;
      return `<h2>Quadro Comparativo</h2><div class="table-wrap"><table class="fixed-layout comparison-table">${colgroup}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function comparisonPeriodSort(period) {
      const text = String(period || "");
      const fy = text.match(/^FY(20\\d{2})$/);
      if (fy) return Number(fy[1]) * 10 + 5;
      const q = text.match(/^([1-4])T(\\d{2}|\\d{4})$/);
      if (q) {
        const year = Number(q[2].length === 2 ? `20${q[2]}` : q[2]);
        return year * 10 + Number(q[1]);
      }
      return 0;
    }

    function renderComparison() {
      const charts = DATA.comparison?.charts || {};
      const chartOrder = ["ciclo_financeiro", "margem_bruta", "margem_operacional", "margem_ebitda", "margem_liquida"];
      const chartHtml = chartOrder.map(key => renderComparisonChartImage(key, charts[key] || {})).filter(Boolean);
      return `${renderComparisonTable()}<h2>Evolução Histórica</h2><div class="charts-grid">${chartHtml.map(chart => `<section class="chart-card">${chart}</section>`).join("")}</div>`;
    }

    function renderComparisonChartImage(chartKey, chart) {
      const asset = DATA.chart_assets?.comparison?.[chartKey]?.url;
      if (!asset) {
        return `<h2>${escapeHtml(chart.title || chartKey)}</h2><div class="empty">Gráfico indisponível para esta atualização.</div>`;
      }
      return `<h2>${escapeHtml(chart.title || chartKey)}</h2><div class="table-wrap"><img class="chart-img" src="${asset}" loading="lazy" alt="${escapeHtml(chart.title || chartKey)}"></div>`;
    }

    function renderInlineMarkdown(text) {
      return escapeHtml(text)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
    }

    function renderMarkdownTable(lines, start) {
      const tableLines = [];
      let i = start;
      while (i < lines.length && /^\\s*\\|/.test(lines[i])) {
        tableLines.push(lines[i]);
        i += 1;
      }
      const rows = tableLines
        .filter((line, index) => index !== 1 || !/^\\s*\\|?\\s*:?-{3,}/.test(line))
        .map(line => line.trim().replace(/^\\|/, "").replace(/\\|$/, "").split("|").map(cell => renderInlineMarkdown(cell.trim())));
      if (!rows.length) return ["", i];
      const header = rows[0].map(cell => `<th>${cell}</th>`).join("");
      const body = rows.slice(1).map(row => `<tr>${row.map(cell => `<td class="desc">${cell}</td>`).join("")}</tr>`).join("");
      return [`<div class="table-wrap methodology-table"><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`, i];
    }

    function markdownToHtml(markdown) {
      const lines = String(markdown || "").replace(/\\r\\n/g, "\\n").split("\\n");
      const html = [];
      let inCode = false;
      let codeLines = [];
      let inList = false;
      let skipFrontMatter = false;
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i];
        if (i === 0 && line.trim() === "---") {
          skipFrontMatter = true;
          continue;
        }
        if (skipFrontMatter) {
          if (line.trim() === "---") skipFrontMatter = false;
          continue;
        }
        if (line.trim().startsWith("```")) {
          if (inCode) {
            html.push(`<pre><code>${escapeHtml(codeLines.join("\\n"))}</code></pre>`);
            codeLines = [];
            inCode = false;
          } else {
            if (inList) { html.push("</ul>"); inList = false; }
            inCode = true;
          }
          continue;
        }
        if (inCode) {
          codeLines.push(line);
          continue;
        }
        if (/^\\s*\\|/.test(line) && i + 1 < lines.length && /^\\s*\\|?\\s*:?-{3,}/.test(lines[i + 1])) {
          if (inList) { html.push("</ul>"); inList = false; }
          const [tableHtml, nextIndex] = renderMarkdownTable(lines, i);
          html.push(tableHtml);
          i = nextIndex - 1;
          continue;
        }
        const heading = line.match(/^(#{1,6})\\s+(.*)$/);
        if (heading) {
          if (inList) { html.push("</ul>"); inList = false; }
          const level = Math.min(heading[1].length + 1, 6);
          html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
          continue;
        }
        const bullet = line.match(/^\\s*[-*]\\s+(.*)$/);
        const numbered = line.match(/^\\s*\\d+\\.\\s+(.*)$/);
        if (bullet || numbered) {
          if (!inList) { html.push("<ul>"); inList = true; }
          html.push(`<li>${renderInlineMarkdown((bullet || numbered)[1])}</li>`);
          continue;
        }
        if (!line.trim()) {
          if (inList) { html.push("</ul>"); inList = false; }
          continue;
        }
        html.push(`<p>${renderInlineMarkdown(line)}</p>`);
      }
      if (inList) html.push("</ul>");
      if (inCode) html.push(`<pre><code>${escapeHtml(codeLines.join("\\n"))}</code></pre>`);
      return html.join("");
    }

    function renderMethodology() {
      const markdown = DATA.methodology_markdown || "";
      if (!markdown.trim()) {
        return '<div class="empty">Arquivo metodologia.md não encontrado.</div>';
      }
      return `<section class="methodology-content">${markdownToHtml(markdown)}</section>`;
    }

    function renderAudit(ticker) {
      const op = DATA.operational?.companies?.[ticker] || {};
      const indicatorErrors = DATA.indicators?.indicadores?.errors?.[ticker] || {};
      const auditRow = (block, item, status, period, code, source, note) => ({ block, item, status, period, code, source, note });
      const financialRows = [];
      Object.entries(DATA.statements || {}).forEach(([statementKey, payload]) => {
        const company = payload?.companies?.[ticker];
        const file = DATA.files?.[statementKey]?.path || "";
        if (!company) {
          financialRows.push(auditRow("Demonstrações", labels[statementKey] || statementKey, "Dado faltante", "", "", file || "Arquivo não carregado", ""));
          return;
        }
        const periods = company.periods?.length || 0;
        const rows = company.rows?.length || 0;
        const denoms = company.denom_cvm?.join(" / ") || "";
        financialRows.push(auditRow("Demonstrações", labels[statementKey] || statementKey, "OK", `${periods} períodos`, "", file, `${rows} contas; ${denoms}`));
        (company.rows || []).filter(row => row.is_aggregator || String(row.code || "").length <= 7).slice(0, 80).forEach(row => {
          financialRows.push(auditRow("Contas CVM", labels[statementKey] || statementKey, "Conta CVM", "", row.code || "", file, row.description || ""));
        });
      });
      ["indicadores", "divida_liquida", "ciclo_financeiro", "market_cap"].forEach(key => {
        const source = DATA.indicators?.[key];
        const file = DATA.files?.[key]?.path || "";
        const companyData = source?.companies?.[ticker];
        financialRows.push(auditRow("Cálculos", key, companyData ? "OK" : "Dado faltante", "", "", file, ""));
      });
      const opRows = Object.entries(op.metricas || {}).map(([metric, items]) => {
        const sources = (items || []).map(item => item.fonte_documento || item.fonte_linha || item.escopo || "").filter(Boolean).join(" | ");
        const validItems = (items || []).filter(item => item?.confidence !== "low");
        const missing = !validItems.some(item => item?.serie && Object.keys(item.serie).length);
        const status = missing ? "NOT_FOUND" : validItems.some(item => item?.confidence === "medium") ? "MEDIUM" : "HIGH";
        const note = validItems.map(item => `${item.nature || "reported"} / ${item.confidence || ""} / ${item.fonte_linha || ""}`).join(" | ");
        return auditRow("Operacional", metric, status, "", "", sources || op.fonte_planilha || op.fonte_alternativa || "", note || op.erro_planilha || "");
      });
      (op.warnings || []).forEach(item => {
        const status = item.status === "not_found" ? "NOT_FOUND" : item.status === "medium_confidence" ? "MEDIUM" : item.status;
        opRows.push(auditRow("Operacional", item.metric || "", status, item.period || "", "", item.fonte_linha || item.escopo || op.fonte_planilha || op.fonte_alternativa || "", item.message || ""));
      });
      const defaultOperationalMetrics = ["Ticket Médio", "N. Atendimentos", "N. Unidades", "N. Pacientes", "Receita Bruta", "Glosa/PCLD"];
      const existingOp = new Set(Object.keys(op.metricas || {}));
      defaultOperationalMetrics.forEach(metric => {
        if (!existingOp.has(metric)) opRows.push(auditRow("Operacional", metric, "Dado faltante", "", "", op.fonte_alternativa || "", ""));
      });
      const errorRows = Object.entries(indicatorErrors).map(([period, message]) => auditRow("Erros", "Indicadores", "Erro", period, "", DATA.files?.indicadores?.path || "", message));
      const rows = [...financialRows, ...opRows, ...errorRows];
      if (!rows.length) return `<div class="empty">Sem mensagens de auditoria para ${escapeHtml(ticker)}.</div>`;
      const body = rows.map(row => `<tr><td>${escapeHtml(row.block)}</td><td class="desc">${escapeHtml(row.item)}</td><td>${escapeHtml(row.status)}</td><td>${escapeHtml(row.period)}</td><td>${escapeHtml(row.code)}</td><td class="desc">${escapeHtml(row.source)}</td><td class="desc">${escapeHtml(row.note)}</td></tr>`).join("");
      const colgroup = '<colgroup><col style="width:150px"><col style="width:260px"><col style="width:130px"><col style="width:120px"><col style="width:130px"><col style="width:460px"><col style="width:460px"></colgroup>';
      const disclaimer = '<div class="disclaimer"><strong>Aviso:</strong> a auditoria dos dados operacionais reflete uma captura experimental e pode conter classificações ou leituras incorretas. A origem informada deve ser usada para validação manual nos documentos originais.</div>';
      return `<h2>Auditoria - ${escapeHtml(ticker)}</h2>${disclaimer}<div class="table-wrap"><table class="fixed-layout audit-table">${colgroup}<thead><tr><th>Bloco</th><th>Item</th><th>Status</th><th>Período</th><th>Conta/código</th><th>Origem</th><th>Observação</th></tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function render() {
      if (!DATA) return;
      renderTabs();
      renderQuote(currentTicker);
      if (currentMain === "metodologia") {
        document.getElementById("meta").textContent = "Metodologia";
        document.getElementById("content").innerHTML = renderMethodology();
        return;
      }
      if (currentMain === "comparativo") {
        document.getElementById("view-tabs").innerHTML = "";
        document.getElementById("view-tabs").style.display = "none";
        document.getElementById("meta").textContent = "Comparativo | 7 empresas";
        document.getElementById("content").innerHTML = renderComparison();
        return;
      }
      if (currentMain === "auditoria") {
        document.getElementById("meta").textContent = `Auditoria | ${currentTicker}`;
        document.getElementById("content").innerHTML = renderAudit(currentTicker);
        return;
      }
      if (currentMain === "dados" && DATA.has_data === false) {
        const viewTabs = document.getElementById("view-tabs");
        viewTabs.innerHTML = "";
        viewTabs.style.display = "flex";
        if (!window.__STATIC_DATA__) {
          renderUpdateButtons().forEach(updateButton => viewTabs.appendChild(updateButton));
        }
        document.getElementById("meta").textContent = "Sem dados carregados";
        document.getElementById("content").innerHTML = '<div class="empty">Nenhum dado carregado. Execute a atualização para gerar os dados.</div>';
        return;
      }
      const statement = DATA.statements[currentStatement] || {};
      const company = statement.companies?.[currentTicker];
      renderViewTabs(company);
      if (currentStatement === "dashboard") {
        document.getElementById("meta").textContent = `${labels[currentStatement]} | ${viewLabels[currentView]} | ${currentTicker}`;
        document.getElementById("content").innerHTML = renderDashboard(currentTicker, currentView);
        return;
      }
      if (currentStatement === "operacional") {
        document.getElementById("meta").textContent = `${labels[currentStatement]} | ${viewLabels[currentView]} | ${currentTicker}`;
        document.getElementById("content").innerHTML = renderOperationalTable(currentTicker, currentView);
        return;
      }
      document.getElementById("meta").textContent = company
        ? `${labels[currentStatement]} | ${viewLabels[currentView]} | ${currentTicker} | ${company.denom_cvm?.join(" / ") || ""} | valores em R$ milhões`
        : `${labels[currentStatement]} | ${currentTicker}`;
      if (!company) {
        document.getElementById("content").innerHTML = '<div class="empty">JSON não encontrado ou empresa ausente.</div>';
        return;
      }
      const sections = [];
      if (currentStatement === "dre" && DATA.operational_enabled === true) {
        sections.push(renderOperationalDreTable(company, currentView));
      }
      sections.push(renderTable(company, currentStatement, currentView));
      if (["balanco", "dre"].includes(currentStatement)) {
        sections.push(renderAvAhTable(company, currentStatement, currentView));
      }
      document.getElementById("content").innerHTML = sections.filter(Boolean).join("");
    }

    // O carregamento começa somente após a seleção explícita do setor.
  </script>
</body>
</html>
"""


def create_app(resultados: Path, anos: list[int] | None = None) -> Flask:
    resultados.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__)

    @app.get("/")
    def index() -> Response:
        response = Response(HTML, mimetype="text/html")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/data")
    def api_data() -> Response:
        try:
            sector = validate_sector(request.args.get("sector", "saude"))
            if sector == "all":
                raise ValueError("Setor all nao e valido para visualizacao.")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            response = jsonify(dashboard_payload(resultados, sector=sector))
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/update")
    def api_update() -> Response:
        if configured_data_source_mode() == "remote":
            return jsonify(
                {
                    "error": "Atualizacao ETL desabilitada em modo remoto. Os dados sao publicados pelo GitHub Actions.",
                }
            ), 409
        payload = request.get_json(silent=True) or {}
        try:
            update_scope = validate_update_scope(str(payload.get("scope") or "all"))
            update_mode = validate_update_mode(str(payload.get("mode") or "full"))
            update_sector = validate_sector(str(payload.get("sector") or "saude"))
            if update_sector == "construcao_civil" and update_scope == "operational":
                raise ValueError("O setor construcao_civil ainda não possui atualização operacional.")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        with UPDATE_LOCK:
            if UPDATE_STATE.get("running"):
                return jsonify({"started": False, "status": UPDATE_STATE}), 409
            UPDATE_STATE.update(
                {
                    "running": True,
                    "status": "running",
                    "current_step": "Preparando atualização",
                    "scope": update_scope,
                    "sector": update_sector,
                    "mode": update_mode,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": None,
                    "logs": [],
                    "error": None,
                }
            )

        def worker() -> None:
            try:
                update_result = run_update(resultados, anos, mode=update_mode, scope=update_scope, sector=update_sector)
                with UPDATE_LOCK:
                    UPDATE_STATE.update(
                        {
                            "running": False,
                            "status": update_result.get("status", "success"),
                            "current_step": None,
                            "scope": update_result.get("scope", update_scope),
                            "sector": update_result.get("sector", update_sector),
                            "mode": update_result.get("mode", update_mode),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error": None,
                        }
                    )
                append_update_log(f"Atualização {update_scope} concluída.")
            except Exception as exc:
                append_update_log(traceback.format_exc()[-8000:])
                with UPDATE_LOCK:
                    UPDATE_STATE.update(
                        {
                            "running": False,
                            "status": "error",
                            "current_step": None,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error": sanitize_log_message(str(exc)),
                        }
                    )

        threading.Thread(target=worker, daemon=True).start()
        return jsonify({"started": True, "status": UPDATE_STATE})

    @app.post("/api/refresh-data")
    def api_refresh_data() -> Response:
        clear_remote_cache()
        try:
            body = request.get_json(silent=True) or {}
            sector = validate_sector(str(body.get("sector") or request.args.get("sector") or "saude"))
            payload = dashboard_payload(resultados, sector=sector, force_remote_refresh=True)
            return jsonify(
                {
                    "refreshed": True,
                    "has_data": payload.get("has_data", False),
                    "data_source": payload.get("data_source"),
                    "remote_metadata": payload.get("remote_metadata"),
                }
            )
        except Exception as exc:
            return jsonify({"refreshed": False, "error": sanitize_log_message(str(exc))}), 500

    @app.get("/api/update-status")
    def api_update_status() -> Response:
        with UPDATE_LOCK:
            return jsonify(dict(UPDATE_STATE))

    @app.get("/api/operational/manual")
    def api_manual_operational_get() -> Response:
        try:
            source = DashboardDataSource(resultados)
            payload, _files = load_manual_overrides_from_source(source, resultados)
            return jsonify({**payload, "write_enabled": manual_admin_token_configured()})
        except Exception as exc:
            return jsonify({"error": sanitize_log_message(str(exc))}), 500

    @app.post("/api/operational/manual")
    def api_manual_operational_post() -> Response:
        if not manual_auth_ok():
            return jsonify({"error": "Escrita manual desabilitada ou token admin invalido."}), 403
        try:
            payload = request.get_json(silent=True) or {}
            record = validate_manual_record(payload)
            current = current_manual_payload_for_write(resultados)
            updated = upsert_manual_override(current, record)
            storage = persist_manual_payload(
                resultados,
                updated,
                f"Update manual operational override: {record['ticker']} {record['metric']} {record['period']}",
            )
            return jsonify({"saved": True, "record": record, "storage": storage})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": sanitize_log_message(str(exc))}), 500

    @app.put("/api/operational/manual/<record_id>")
    def api_manual_operational_put(record_id: str) -> Response:
        if not manual_auth_ok():
            return jsonify({"error": "Escrita manual desabilitada ou token admin invalido."}), 403
        try:
            payload = request.get_json(silent=True) or {}
            current = current_manual_payload_for_write(resultados)
            existing = next((item for item in current.get("overrides", []) if str(item.get("id")) == str(record_id)), {})
            merged = {**existing, **payload, "id": record_id, "created_at": existing.get("created_at")}
            record = validate_manual_record(merged, existing_id=record_id)
            updated = upsert_manual_override(current, record)
            storage = persist_manual_payload(
                resultados,
                updated,
                f"Update manual operational override: {record['ticker']} {record['metric']} {record['period']}",
            )
            return jsonify({"saved": True, "record": record, "storage": storage})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": sanitize_log_message(str(exc))}), 500

    @app.delete("/api/operational/manual/<record_id>")
    def api_manual_operational_delete(record_id: str) -> Response:
        if not manual_auth_ok():
            return jsonify({"error": "Escrita manual desabilitada ou token admin invalido."}), 403
        try:
            current = current_manual_payload_for_write(resultados)
            updated = delete_manual_override(current, record_id)
            storage = persist_manual_payload(resultados, updated, f"Delete manual operational override: {record_id}")
            return jsonify({"deleted": True, "storage": storage})
        except KeyError:
            return jsonify({"error": "Override manual nao encontrado."}), 404
        except Exception as exc:
            return jsonify({"error": sanitize_log_message(str(exc))}), 500

    @app.get("/export/dashboard.html")
    def export_dashboard() -> Response:
        try:
            sector = validate_sector(request.args.get("sector", "saude"))
            response = Response(static_export_html(resultados, sector=sector), mimetype="text/html")
            response.headers["Content-Disposition"] = "attachment; filename=acompanhador_de_mercado.html"
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/logos/<path:filename>")
    def logos(filename: str) -> Response:
        response = send_from_directory(BASE_DIR / "Logos", filename)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/chart/<ticker>/<view>/<chart_key>")
    def chart(ticker: str, view: str, chart_key: str) -> Response:
        """Rota legada para desenvolvimento local; produção usa PNGs publicados."""
        sector = validate_sector(request.args.get("sector", "saude"))
        if ticker not in tickers_for_sector(sector) or view not in {"annual", "quarterly"} or chart_key not in CHARTS:
            return jsonify({"error": "chart_not_found"}), 404
        try:
            response = Response(make_chart_png(resultados, ticker, view, chart_key, sector), mimetype="image/png")
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return app


def main() -> int:
    args = parse_args()
    args.resultados = resolve_app_path(args.resultados)
    if args.export_html:
        args.export_html = resolve_app_path(args.export_html)
    args.resultados.mkdir(parents=True, exist_ok=True)
    paths = {
        "dre": args.resultados / "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": args.resultados / "DFC_ITR_CVM.json",
    }

    if args.atualizar:
        run_update(args.resultados, args.anos, mode=args.update_mode, scope=args.update_scope, sector=args.update_sector)

    if args.export_html:
        html = static_export_html(args.resultados, sector=args.sector)
        args.export_html.parent.mkdir(parents=True, exist_ok=True)
        args.export_html.write_text(html, encoding="utf-8")
        print(f"HTML exportado em {args.export_html}")
        return 0

    if not args.nao_liberar_porta:
        liberar_porta_dashboard(args.port)

    app = create_app(args.resultados, args.anos)
    print(f"Acompanhador de Mercado em http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

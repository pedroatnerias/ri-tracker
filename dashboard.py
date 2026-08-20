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
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


TICKERS = ("AALR3", "DASA3", "FLRY3", "HAPV3", "MATD3", "ONCO3", "RDOR3")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8050


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


def run_command(command: list[str]) -> None:
    print("Rodando:", " ".join(command))
    subprocess.run(command, cwd=BASE_DIR, check=True)


UPDATE_STATE: dict[str, object] = {
    "running": False,
    "status": "idle",
    "current_step": None,
    "started_at": None,
    "finished_at": None,
    "logs": [],
    "error": None,
}
UPDATE_LOCK = threading.Lock()


def append_update_log(message: str) -> None:
    message = sanitize_log_message(message)
    with UPDATE_LOCK:
        logs = list(UPDATE_STATE.get("logs") or [])
        logs.append(message)
        UPDATE_STATE["logs"] = logs[-250:]


def run_update_command(label: str, command: list[str]) -> None:
    append_update_log(f"Iniciando: {label}")
    with UPDATE_LOCK:
        UPDATE_STATE["current_step"] = label
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
        raise RuntimeError(f"{label} falhou com codigo {result.returncode}")
    append_update_log(f"Concluido: {label}")


def run_full_update(resultados: Path, anos: list[int] | None = None) -> None:
    resultados = resultados.expanduser().resolve()
    resultados.mkdir(parents=True, exist_ok=True)
    operational_dir = resultados / "dados_operacionais"
    operational_dir.mkdir(parents=True, exist_ok=True)
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
    append_update_log(f"Anos da atualizacao CVM: {', '.join(year_args)}")

    balanco_cmd = [sys.executable, script_path("app_balancos.py"), "--output-dir", str(resultados)]
    if year_args:
        balanco_cmd.extend(["--years", *year_args])
    balanco_cmd.append("--force-download")
    run_update_command("Balanço Patrimonial CVM", balanco_cmd)
    balanco_path = find_balanco_json(resultados)

    dre_cmd = [sys.executable, script_path("app_dre.py"), "--saida", str(dre_path)]
    if year_args:
        dre_cmd.extend(["--anos", *year_args])
    dre_cmd.append("--sobrescrever-zips")
    run_update_command("DRE CVM", dre_cmd)

    dfc_cmd = [sys.executable, script_path("app_dfc.py"), "--diretorio", str(resultados), "--saida", str(dfc_path)]
    if year_args:
        dfc_cmd.extend(["--anos", *year_args])
    dfc_cmd.append("--sobrescrever-downloads")
    run_update_command("DFC CVM", dfc_cmd)

    run_update_command("Releases e relatorios operacionais", [sys.executable, script_path("app_parser_operacional.py")])
    run_update_command(
        "Dados operacionais",
        [sys.executable, script_path("app_extrator_operacional.py"), "--output-dir", str(operational_dir)],
    )
    run_update_command("Divida liquida", [sys.executable, script_path("app_divida_liquida.py"), "calculate", str(balanco_path), "--output", str(divida_path)])
    run_update_command("Ciclo financeiro", [sys.executable, script_path("app_ciclo_financeiro.py"), str(balanco_path), str(ciclo_path), "--dre", str(dre_path)])
    run_update_command("Market cap atual", [sys.executable, script_path("app_market_cap.py"), "--saida", str(market_path)])
    run_update_command("Market cap historico", [sys.executable, script_path("app_market_cap_historico.py"), "--saida", str(market_hist_path)])
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


def dashboard_payload(resultados: Path) -> dict:
    resultados.mkdir(parents=True, exist_ok=True)
    paths = {
        "balanco": find_optional_balanco_json(resultados),
        "dre": resultados / "DRE_ITR_CVM_ultimos_5_anos.json",
        "dfc": resultados / "DFC_ITR_CVM.json",
    }
    expected_paths = {
        "balanco": resultados / "balancos_itr_cvm_*.json",
        "dre": paths["dre"],
        "dfc": paths["dfc"],
    }
    indicator_paths = {
        "indicadores": resultados / "indicadores.json",
        "divida_liquida": resultados / "divida_liquida.json",
        "ciclo_financeiro": resultados / "ciclo_financeiro.json",
        "market_cap": resultados / "market_cap.json",
    }
    operational_data, operational_files = load_operational_data(resultados)
    statements = {
        "balanco": load_optional_statement(paths["balanco"]),
        "dre": load_optional_statement(paths["dre"]),
        "dfc": load_optional_statement(paths["dfc"]),
    }
    # Primeiro boot em cloud pode nao ter JSONs; has_data so fica true quando
    # os tres demonstrativos financeiros minimos ja foram gerados.
    has_data = all(bool(statements[key]) for key in ("balanco", "dre", "dfc"))
    return {
        "tickers": TICKERS,
        "has_data": has_data,
        "statements": statements,
        "indicators": {
            key: load_optional_json(path)
            for key, path in indicator_paths.items()
        },
        "operational": operational_data,
        "methodology_markdown": load_methodology_markdown(),
        "update_status": dict(UPDATE_STATE),
        "files": {
            key: file_metadata(path, expected_paths.get(key))
            for key, path in paths.items()
        } | {
            key: {
                "path": str(path),
                "modified_at": path.stat().st_mtime if path.exists() else None,
                "exists": path.exists(),
            }
            for key, path in indicator_paths.items()
        } | operational_files,
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


def chart_dataframe(resultados: Path, ticker: str, view: str, chart_key: str) -> pd.DataFrame:
    payload = dashboard_payload(resultados)
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


def make_chart_png(resultados: Path, ticker: str, view: str, chart_key: str) -> bytes:
    config = CHARTS[chart_key]
    df = chart_dataframe(resultados, ticker, view, chart_key)
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


def static_export_html(resultados: Path) -> str:
    payload = dashboard_payload(resultados)
    charts: dict[str, str] = {}
    for ticker in TICKERS:
        for view in ("annual", "quarterly"):
            for chart_key in CHARTS:
                try:
                    png = make_chart_png(resultados, ticker, view, chart_key)
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
  <div class="topbar">
    <div class="brand-title">
      <img class="nerias-logo" src="/logos/Nerias.png" alt="Nerias">
      <h1>Acompanhador de Mercado</h1>
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
  <script>
    let DATA = null;
    let currentTicker = "AALR3";
    let currentMain = "dados";
    let currentStatement = "dashboard";
    let currentView = "annual";
    let updatePolling = null;
    const expandedRows = new Set();
    const labels = { dashboard: "Dashboard", operacional: "Dados Operacionais", balanco: "Balanço", dre: "DRE", dfc: "DFC" };
    const mainLabels = { dados: "Dados", metodologia: "Metodologia", auditoria: "Auditoria" };
    const viewLabels = { annual: "Anual", quarterly: "Trimestral" };

    async function loadData() {
      if (window.__STATIC_DATA__) {
        DATA = window.__STATIC_DATA__;
        currentTicker = DATA.tickers.includes(currentTicker) ? currentTicker : DATA.tickers[0];
        render();
        updateStatusText(DATA.update_status);
        return;
      }
      const response = await fetch("/api/data", { cache: "no-store" });
      if (!response.ok) throw new Error(await response.text());
      DATA = await response.json();
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
        el.innerHTML = `<strong>Atualizando tudo...</strong> ${escapeHtml(state.current_step || "")}`;
        return;
      }
      if (state.status === "success") {
        el.innerHTML = "<strong>Atualização concluída.</strong> Dados recarregados.";
        return;
      }
      if (state.status === "error") {
        el.innerHTML = `<strong>Erro na atualização:</strong> ${escapeHtml(state.error || "verifique o terminal/logs")}`;
        return;
      }
      el.textContent = "";
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
        if (state.status === "success") await loadData();
      }
    }

    async function startFullUpdate() {
      const confirmed = window.confirm("Atualizar tudo do zero? Isso pode demorar alguns minutos e fará downloads/CVM/Yahoo/parser.");
      if (!confirmed) return;
      const response = await fetch("/api/update", { method: "POST", cache: "no-store" });
      const payload = await response.json().catch(() => ({}));
      updateStatusText(payload.status);
      if (!response.ok && response.status !== 409) {
        throw new Error(payload.error || "Falha ao iniciar atualização.");
      }
      if (!updatePolling) updatePolling = setInterval(pollUpdateStatus, 2500);
      await pollUpdateStatus();
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
        viewTabs.appendChild(button("Recarregar JSONs", false, loadData));
        const exportButton = button("Exportar HTML", false, () => {
          window.location.href = "/export/dashboard.html";
        });
        viewTabs.appendChild(exportButton);
        const updateButton = button("Atualizar tudo", false, () => {
          startFullUpdate().catch(error => {
            const el = document.getElementById("update-status");
            if (el) el.innerHTML = `<strong>Erro:</strong> ${escapeHtml(error.message)}`;
          });
        });
        updateButton.classList.add("update-button");
        updateButton.disabled = Boolean(DATA.update_status?.running);
        viewTabs.appendChild(updateButton);
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
        ["CAGR receitas (%)", formatPercent(cagr(first?.receita_liquida, last?.receita_liquida, years))],
        ["CAGR lucros (%)", formatPercent(cagr(first?.lucro_liquido, last?.lucro_liquido, years))],
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
      const cacheBust = DATA.files?.indicadores?.modified_at || Date.now();
      const staticKey = `${ticker}|${view}|${chartKey}`;
      const src = window.__STATIC_CHARTS__?.[staticKey]
        || `/chart/${encodeURIComponent(ticker)}/${encodeURIComponent(view)}/${encodeURIComponent(chartKey)}?v=${encodeURIComponent(cacheBust)}`;
      return `<h2>${escapeHtml(title)}</h2><div class="table-wrap"><img class="chart-img" src="${src}" alt="${escapeHtml(title)}"></div>`;
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
      const zeroIfMissing = value => typeof value === "number" ? value : 0;
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
          values: periods.map(period => zeroIfMissing(valueFor(receita, period))),
        },
        {
          code: "",
          description: "(-) Glosa e PCLD",
          isPercent: false,
          values: periods.map(period => zeroIfMissing(valueFor(glosa, period))),
        },
        {
          code: "",
          description: "(=) Glosa/PCLD / Receita Bruta (%)",
          isPercent: true,
          values: periods.map(period => {
            const revenue = zeroIfMissing(valueFor(receita, period));
            const deductions = zeroIfMissing(valueFor(glosa, period));
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
      const defaultMetrics = ["Ticket Médio", "N. Atendimentos", "N. Unidades", "N. Pacientes"];
      const selectedMetrics = defaultMetrics;
      return selectedMetrics.map(metric => {
        const items = metricas[metric] || [];
        const item = (items || []).find(candidate => candidate?.serie && Object.keys(candidate.serie).length) || items[0] || null;
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
          if (["Receita Bruta", "Glosa/PCLD"].includes(metric)) return;
        (items || []).forEach((item, index) => {
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
      const rows = operationalRows(company, view);
      const periods = fixedOperationalPeriods(company, view);
      const labelsByPeriod = Object.fromEntries(periods.map(period => [period, operationalPeriodInfo(period).label]));
      const headers = ["Indicador", "Escopo / fonte", "Unidade", ...periods.map(period => labelsByPeriod[period])]
        .map(value => `<th>${escapeHtml(value)}</th>`)
        .join("");
      const body = rows.map(row => {
        const values = periods.map(period =>
          `<td class="num">${escapeHtml(formatOperationalValue(row.values[period], row.unit))}</td>`
        ).join("");
        const source = row.calculated ? `${row.source} (calculado)` : row.source;
        return `<tr><td class="desc">${escapeHtml(row.metric)}</td><td class="desc">${escapeHtml(source)}</td><td>${escapeHtml(row.unit)}</td>${values}</tr>`;
      }).join("");
      const colgroup = `<colgroup><col style="width:220px"><col style="width:300px"><col style="width:150px">${periods.map(() => '<col style="width:130px">').join("")}</colgroup>`;
      const disclaimer = '<div class="disclaimer"><strong>Aviso:</strong> os dados operacionais são capturados de forma experimental a partir de planilhas de fundamentos, releases e documentos convertidos para Markdown. Eles podem estar incompletos, classificados incorretamente ou conter erros de leitura. Use estes dados como apoio exploratório e valide contra os documentos originais antes de qualquer decisão.</div>';
      return `<h2>Dados Operacionais</h2>${disclaimer}<div class="table-wrap"><table class="fixed-layout operational-table">${colgroup}<thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
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
        const missing = !(items || []).some(item => item?.serie && Object.keys(item.serie).length);
        return auditRow("Operacional", metric, missing ? "Dado faltante" : "OK", "", "", sources || op.fonte_planilha || op.fonte_alternativa || "", op.erro_planilha || "");
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
      if (currentMain === "auditoria") {
        document.getElementById("meta").textContent = `Auditoria | ${currentTicker}`;
        document.getElementById("content").innerHTML = renderAudit(currentTicker);
        return;
      }
      if (currentMain === "dados" && DATA.has_data === false) {
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
      if (currentStatement === "dre") {
        sections.push(renderOperationalDreTable(company, currentView));
      }
      sections.push(renderTable(company, currentStatement, currentView));
      if (["balanco", "dre"].includes(currentStatement)) {
        sections.push(renderAvAhTable(company, currentStatement, currentView));
      }
      document.getElementById("content").innerHTML = sections.filter(Boolean).join("");
    }

    loadData().catch(error => {
      document.getElementById("meta").textContent = "Erro ao carregar JSONs.";
      document.getElementById("content").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    });
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
            response = jsonify(dashboard_payload(resultados))
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/update")
    def api_update() -> Response:
        with UPDATE_LOCK:
            if UPDATE_STATE.get("running"):
                return jsonify({"started": False, "status": UPDATE_STATE}), 409
            UPDATE_STATE.update(
                {
                    "running": True,
                    "status": "running",
                    "current_step": "Preparando atualização",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": None,
                    "logs": [],
                    "error": None,
                }
            )

        def worker() -> None:
            try:
                run_full_update(resultados, anos)
                with UPDATE_LOCK:
                    UPDATE_STATE.update(
                        {
                            "running": False,
                            "status": "success",
                            "current_step": None,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error": None,
                        }
                    )
                append_update_log("Atualização completa concluída.")
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

    @app.get("/api/update-status")
    def api_update_status() -> Response:
        with UPDATE_LOCK:
            return jsonify(dict(UPDATE_STATE))

    @app.get("/export/dashboard.html")
    def export_dashboard() -> Response:
        try:
            response = Response(static_export_html(resultados), mimetype="text/html")
            response.headers["Content-Disposition"] = "attachment; filename=acompanhador_de_mercado.html"
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/logos/<path:filename>")
    def logos(filename: str) -> Response:
        return send_from_directory(BASE_DIR / "Logos", filename)

    @app.get("/chart/<ticker>/<view>/<chart_key>")
    def chart(ticker: str, view: str, chart_key: str) -> Response:
        if ticker not in TICKERS or view not in {"annual", "quarterly"} or chart_key not in CHARTS:
            return jsonify({"error": "chart_not_found"}), 404
        try:
            response = Response(make_chart_png(resultados, ticker, view, chart_key), mimetype="image/png")
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
        run_full_update(args.resultados, args.anos)

    if args.export_html:
        html = static_export_html(args.resultados)
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

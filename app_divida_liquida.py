#!/usr/bin/env python3
"""Calculadora genérica de dívida líquida para balanços ITR/CVM em JSON."""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

from metric_definitions import METHODOLOGY_VERSION, company_rule, net_debt_options


DEFAULT_CODES = {
    "cash": ("1.01.01",),
    "financial_investments": ("1.01.02",),
    "short_term_debt": ("2.01.04",),
    "long_term_debt": ("2.02.01",),
}

CODE_KEYS = ("cd_conta", "code", "account_code", "codigo_conta")
DESC_KEYS = ("ds_conta", "description", "account_description", "descricao_conta")
VALUE_KEYS = ("vl_conta", "value", "account_value", "valor_conta")


class CalculationError(ValueError):
    """Erro de validação do payload ou das contas."""


@dataclass(frozen=True)
class Account:
    code: str
    description: str
    value: Decimal


def _normalise_key(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def _normalised_mapping(row: dict[str, Any]) -> dict[str, Any]:
    return {_normalise_key(str(k)): v for k, v in row.items()}


def _pick(row: dict[str, Any], keys: Iterable[str]) -> Any:
    normal = _normalised_mapping(row)
    for key in keys:
        if key in normal:
            return normal[key]
    return None


def _decimal(value: Any, account_code: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CalculationError(f"Valor ausente/inválido na conta {account_code}.")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculationError(f"Valor não finito na conta {account_code}.")
    text = str(value).strip().replace(" ", "")
    # Aceita número JSON, '1234.56' e formato brasileiro '1.234,56'.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CalculationError(f"Valor não numérico na conta {account_code}: {value!r}") from exc


def _parse_accounts(payload: dict[str, Any]) -> list[Account]:
    raw = payload.get("accounts")
    if not isinstance(raw, list) or not raw:
        raise CalculationError("'accounts' deve ser uma lista JSON não vazia.")
    accounts: list[Account] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise CalculationError(f"accounts[{i}] deve ser um objeto JSON.")
        code_raw = _pick(row, CODE_KEYS)
        desc_raw = _pick(row, DESC_KEYS)
        value_raw = _pick(row, VALUE_KEYS)
        if code_raw is None:
            raise CalculationError(f"Código da conta ausente em accounts[{i}].")
        code = str(code_raw).strip()
        accounts.append(Account(code, "" if desc_raw is None else str(desc_raw).strip(), _decimal(value_raw, code)))
    return accounts


def _root_value(accounts: list[Account], roots: Iterable[str]) -> tuple[Decimal, list[Account]]:
    """Retorna raízes agregadas; se ausentes, usa folhas descendentes sem duplicar."""
    total = Decimal(0)
    selected: list[Account] = []
    for root in roots:
        exact = [a for a in accounts if a.code == root]
        if exact:
            # Um ITR deveria ter uma linha por conta no período já filtrado.
            # Duplicatas exatas são rejeitadas para não gerar um resultado silenciosamente incorreto.
            if len(exact) > 1:
                raise CalculationError(
                    f"Conta {root} aparece {len(exact)} vezes. Filtre o JSON para um único período/escopo."
                )
            total += exact[0].value
            selected.extend(exact)
            continue

        descendants = [a for a in accounts if a.code.startswith(root + ".")]
        if not descendants:
            continue
        descendant_codes = {a.code for a in descendants}
        leaves = [
            a for a in descendants
            if not any(other != a.code and other.startswith(a.code + ".") for other in descendant_codes)
        ]
        total += sum((a.value for a in leaves), Decimal(0))
        selected.extend(leaves)
    return total, selected


def _lease_accounts(accounts: list[Account], excluded_codes: set[str]) -> list[Account]:
    """Detecta apenas folhas cuja descrição identifica explicitamente arrendamento."""
    tokens = re.compile(r"\b(arrendamento|arrendamentos|leasing)\b", re.IGNORECASE)
    candidates = [
        a for a in accounts
        if a.code.startswith("2.") and a.code not in excluded_codes and tokens.search(_normalise_key(a.description))
    ]
    codes = {a.code for a in candidates}
    return [a for a in candidates if not any(c != a.code and c.startswith(a.code + ".") for c in codes)]


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral() else float(value)


def _audit(accounts: list[Account]) -> list[dict[str, Any]]:
    return [
        {"cd_conta": a.code, "ds_conta": a.description, "vl_conta": _json_number(a.value)}
        for a in accounts
    ]


def _is_bp_json(payload: dict[str, Any]) -> bool:
    return (
        payload.get("kind") == "balanco_patrimonial_itr_cvm"
        and isinstance(payload.get("companies"), dict)
    )


def _period_accounts(company_payload: dict[str, Any], period: str) -> list[dict[str, Any]]:
    accounts = []
    for row in company_payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        value = (row.get("values") or {}).get(period)
        if value is None:
            continue
        accounts.append(
            {
                "cd_conta": row.get("code"),
                "ds_conta": row.get("description"),
                "vl_conta": value,
            }
        )
    return accounts


def _calculate_bp_json(payload: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    results: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    for ticker, company_payload in payload.get("companies", {}).items():
        if not isinstance(company_payload, dict):
            continue
        company_results = []
        company_options = {**net_debt_options(ticker), **options}
        for period in company_payload.get("periods", []):
            adapted = {
                "company": ticker,
                "date": period,
                "unit": company_payload.get("unit") or payload.get("unit"),
                "accounts": _period_accounts(company_payload, period),
                "options": company_options,
            }
            try:
                company_results.append(calculate_net_debt(adapted))
            except CalculationError as exc:
                errors.setdefault(ticker, {})[period] = str(exc)
        results[ticker] = company_results

    return {
        "source_kind": payload.get("kind"),
        "metric": "net_debt",
        "methodology_version": METHODOLOGY_VERSION,
        "unit": "Reais integrais",
        "companies": results,
        "errors": errors,
    }


def calculate_net_debt(payload: dict[str, Any]) -> dict[str, Any]:
    """Calcula dívida líquida a partir de um payload JSON já desserializado."""
    if not isinstance(payload, dict):
        raise CalculationError("O corpo da requisição deve ser um objeto JSON.")
    if _is_bp_json(payload):
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        return _calculate_bp_json(payload, options)
    accounts = _parse_accounts(payload)
    options = payload.get("options") or {}
    if not isinstance(options, dict):
        raise CalculationError("'options' deve ser um objeto JSON.")

    custom_codes = options.get("codes") or {}
    if not isinstance(custom_codes, dict):
        raise CalculationError("options.codes deve ser um objeto JSON.")

    codes: dict[str, tuple[str, ...]] = {}
    for category, defaults in DEFAULT_CODES.items():
        supplied = custom_codes.get(category, defaults)
        if isinstance(supplied, str):
            supplied = [supplied]
        if not isinstance(supplied, list) and not isinstance(supplied, tuple):
            raise CalculationError(f"options.codes.{category} deve ser texto ou lista.")
        codes[category] = tuple(str(x).strip() for x in supplied if str(x).strip())

    cash, cash_rows = _root_value(accounts, codes["cash"])
    investments, investment_rows = _root_value(accounts, codes["financial_investments"])
    short_debt, short_rows = _root_value(accounts, codes["short_term_debt"])
    long_debt, long_rows = _root_value(accounts, codes["long_term_debt"])

    if not (short_rows or long_rows):
        raise CalculationError("Nenhuma conta de empréstimos/financiamentos foi encontrada.")
    if not cash_rows:
        raise CalculationError("Nenhuma conta de caixa e equivalentes foi encontrada.")

    deduct_investments = bool(options.get("deduct_financial_investments", False))
    include_leases = bool(options.get("include_leases", False))

    already_debt = {a.code for a in short_rows + long_rows}
    lease_rows = _lease_accounts(accounts, already_debt) if include_leases else []
    leases = sum((a.value for a in lease_rows), Decimal(0))

    gross_debt = short_debt + long_debt + leases
    cash_deductions = cash + (investments if deduct_investments else Decimal(0))
    net_debt = gross_debt - cash_deductions

    return {
        "company": payload.get("company"),
        "date": payload.get("date"),
        "unit": payload.get("unit"),
        "metric": "divida_liquida_padronizada",
        "value": _json_number(net_debt),
        "divida_bruta": _json_number(gross_debt),
        "caixa_equivalentes": _json_number(cash),
        "aplicacoes_financeiras_identificadas": _json_number(investments),
        "aplicacoes_financeiras_deduzidas": _json_number(investments if deduct_investments else Decimal(0)),
        "arrendamentos_incluidos": _json_number(leases),
        "divida_liquida_padronizada": _json_number(net_debt),
        "divida_liquida_divulgada": None,
        "diferenca": None,
        "metodologia": {
            "methodology_version": METHODOLOGY_VERSION,
            "formula": "divida_bruta - caixa_equivalentes - aplicacoes_financeiras_deduzidas",
            "net_debt_include_leases": include_leases,
            "deduct_financial_investments": deduct_investments,
            "fonte": "Balanço Patrimonial CVM",
        },
        "quality": {
            "status": "validated",
            "warnings": [],
        },
        "components": {
            "short_term_debt": _json_number(short_debt),
            "long_term_debt": _json_number(long_debt),
            "leases_included": _json_number(leases),
            "gross_debt": _json_number(gross_debt),
            "cash_and_cash_equivalents": _json_number(cash),
            "financial_investments_identified": _json_number(investments),
            "financial_investments_deducted": _json_number(investments if deduct_investments else Decimal(0)),
        },
        "formula": "gross_debt - cash_and_cash_equivalents - financial_investments_deducted",
        "options_applied": {
            "deduct_financial_investments": deduct_investments,
            "include_leases": include_leases,
        },
        "audit": {
            "short_term_debt": _audit(short_rows),
            "long_term_debt": _audit(long_rows),
            "cash": _audit(cash_rows),
            "financial_investments": _audit(investment_rows),
            "leases": _audit(lease_rows),
        },
    }


INDEX_HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dívida Líquida CVM</title><style>
body{font:15px system-ui,sans-serif;margin:0;background:#f4f6f8;color:#17202a}main{max-width:1100px;margin:36px auto;padding:0 18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}textarea,pre{box-sizing:border-box;width:100%;height:510px;padding:14px;border:1px solid #ccd3da;border-radius:8px;background:white;overflow:auto}
textarea{font:13px ui-monospace,monospace;resize:vertical}pre{white-space:pre-wrap}button{border:0;border-radius:7px;background:#173f73;color:white;padding:10px 18px;font-weight:650;cursor:pointer;margin:12px 0}
.muted{color:#637083}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style></head><body><main><h1>Dívida Líquida — ITR/CVM</h1>
<p class="muted">Cole um balanço em JSON. O cálculo preserva a unidade informada no arquivo.</p>
<div class="grid"><section><h2>Entrada</h2><textarea id="input"></textarea><button id="calc">Calcular</button></section>
<section><h2>Resultado</h2><pre id="output">Aguardando cálculo.</pre></section></div>
<script>
const sample={company:"EMPRESA EXEMPLO",date:"2026-03-31",unit:"BRL_thousands",accounts:[
{cd_conta:"1.01.01",ds_conta:"Caixa e Equivalentes de Caixa",vl_conta:100000},
{cd_conta:"1.01.02",ds_conta:"Aplicações Financeiras",vl_conta:20000},
{cd_conta:"2.01.04",ds_conta:"Empréstimos e Financiamentos",vl_conta:250000},
{cd_conta:"2.02.01",ds_conta:"Empréstimos e Financiamentos",vl_conta:500000}],
options:{deduct_financial_investments:false,include_leases:false}};
input.value=JSON.stringify(sample,null,2);
calc.onclick=async()=>{output.textContent="Calculando...";try{const r=await fetch('/api/calculate',{method:'POST',headers:{'content-type':'application/json'},body:input.value});const x=await r.json();output.textContent=JSON.stringify(x,null,2)}catch(e){output.textContent=String(e)}};
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode())
        elif self.path == "/health":
            self._send(200, "application/json", b'{"status":"ok"}')
        else:
            self._send(404, "application/json", b'{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/calculate":
            self._send(404, "application/json", b'{"error":"not_found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000_000:
                raise CalculationError("Tamanho do corpo inválido (máximo: 10 MB).")
            payload = json.loads(self.rfile.read(length))
            result = calculate_net_debt(payload)
            body = json.dumps(result, ensure_ascii=False, indent=2).encode()
            self._send(200, "application/json; charset=utf-8", body)
        except (CalculationError, json.JSONDecodeError) as exc:
            body = json.dumps({"error": "invalid_input", "message": str(exc)}, ensure_ascii=False).encode()
            self._send(400, "application/json; charset=utf-8", body)
        except Exception:
            body = b'{"error":"internal_error","message":"Erro interno inesperado."}'
            self._send(500, "application/json", body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[http] {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcula dívida líquida em balanços ITR/CVM.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Inicia app e API HTTP.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    calc = sub.add_parser("calculate", help="Calcula um arquivo JSON.")
    calc.add_argument("json_file", type=Path)
    calc.add_argument("--output", "-o", type=Path, help="Arquivo JSON de saida.")
    args = parser.parse_args()

    if args.command == "calculate":
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
        result = calculate_net_debt(payload)
        body = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(body, encoding="utf-8")
            print(f"Arquivo salvo em {args.output}")
        else:
            print(body)
        return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dívida Líquida CVM em http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

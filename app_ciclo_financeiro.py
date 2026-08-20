#!/usr/bin/env python3
"""Calcula PMP, PME, PMR e ciclo financeiro a partir de ITRs da CVM em JSON.

O parser aceita um JSON plano (lista de registros) ou registros aninhados em
listas/dicionarios. Ele reconhece os nomes de campos usados nos dados abertos
da CVM (CD_CONTA, DS_CONTA, VL_CONTA, DT_INI_EXERC, DT_FIM_EXERC etc.).

Formulas:
    PMR = contas a receber medias / receita liquida * dias do periodo
    PME = estoques medios / CMV * dias do periodo
    Compras = CMV + estoque final - estoque inicial
    PMP = fornecedores medios / compras * dias do periodo
    Ciclo financeiro = PMR + PME - PMP

Valores de CMV negativos na DRE sao convertidos para modulo. Saldos medios
usam inicio e fim do periodo; a ausencia de saldo inicial causa erro, pois usar
apenas o saldo final introduziria uma aproximacao silenciosa.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional


class CalculationError(ValueError):
    """Erro de dados insuficientes ou inconsistentes para o calculo."""


def _first(record: dict[str, Any], *names: str) -> Any:
    upper = {str(k).upper(): v for k, v in record.items()}
    for name in names:
        value = upper.get(name.upper())
        if value is not None and value != "":
            return value
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def _number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if value is None:
        raise CalculationError("Registro de conta sem valor.")
    s = str(value).strip().replace(" ", "")
    # Suporta tanto 1234.56 quanto 1.234,56.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError as exc:
        raise CalculationError(f"Valor numerico invalido: {value!r}") from exc


def _date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _scale_multiplier(record: dict[str, Any]) -> float:
    scale = _text(_first(record, "ESCALA_MOEDA", "ESCALA", "SCALE"))
    if not scale:
        return 1.0
    if "milhao" in scale:
        return 1_000_000.0
    if scale == "mil" or "milhar" in scale:
        return 1_000.0
    return 1.0


def _looks_like_account(record: dict[str, Any]) -> bool:
    keys = {str(k).upper() for k in record}
    has_value = bool(keys & {"VL_CONTA", "VALOR", "VALUE", "VL"})
    has_account = bool(keys & {"CD_CONTA", "COD_CONTA", "CONTA", "ACCOUNT_CODE", "DS_CONTA", "DESCRICAO"})
    return has_value and has_account


def flatten_records(node: Any) -> list[dict[str, Any]]:
    """Extrai registros de conta de qualquer estrutura JSON razoavelmente aninhada."""
    out: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(flatten_records(item))
    elif isinstance(node, dict):
        if _looks_like_account(node):
            out.append(node)
        else:
            for value in node.values():
                if isinstance(value, (dict, list)):
                    out.extend(flatten_records(value))
    return out


def _is_bp_json(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("kind") == "balanco_patrimonial_itr_cvm"
        and isinstance(data.get("companies"), dict)
    )


def _is_dre_json(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("kind") == "dre_itr_cvm"
        and isinstance(data.get("companies"), dict)
    )


def _bp_period_records(company_payload: dict[str, Any], period: str) -> list[dict[str, Any]]:
    records = []
    for row in company_payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        value = (row.get("values") or {}).get(period)
        if value is None:
            continue
        records.append(
            {
                "CD_CONTA": row.get("code"),
                "DS_CONTA": row.get("description"),
                "VL_CONTA": value,
                "DT_REFER": period,
                "ESCOPO": company_payload.get("scope"),
            }
        )
    return records


def _dre_period_records(company_payload: dict[str, Any], period: str) -> list[dict[str, Any]]:
    records = []
    meta = (company_payload.get("period_metadata") or {}).get(period, {})
    for row in company_payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        value = (row.get("values") or {}).get(period)
        if value is None:
            continue
        records.append(
            {
                "CD_CONTA": row.get("code"),
                "DS_CONTA": row.get("description"),
                "VL_CONTA": value,
                "DT_INI_EXERC": meta.get("start_date"),
                "DT_FIM_EXERC": meta.get("end_date"),
                "DT_REFER": meta.get("end_date"),
                "ORDEM_EXERC": "ULTIMO",
                "ESCOPO": company_payload.get("tipo_dre"),
            }
        )
    return records


def _balance_value(rows: list[AccountRow], kind: str) -> float | None:
    matches = _matching(rows, kind, current_only=False)
    if not matches:
        return None
    return matches[0].value


def _bp_value(company_payload: dict[str, Any], kind: str, period: str, scope: str) -> float:
    rows = _choose_scope([normalise(r) for r in _bp_period_records(company_payload, period)], scope)
    value = _balance_value(rows, kind)
    if value is None:
        raise CalculationError(f"Conta de {kind} ausente no BP em {period}.")
    return value


def _nearest_bp_period(periods: list[str], target: date) -> str | None:
    dated = [(p, _date(p)) for p in periods]
    valid = [(p, d) for p, d in dated if d and d <= target]
    if not valid:
        return None
    return max(valid, key=lambda item: item[1])[0]


def calculate_bp_json(data: dict[str, Any], scope: str = "auto", dre_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    for ticker, company_payload in data.get("companies", {}).items():
        company_results = []
        if _is_dre_json(dre_payload) and ticker in dre_payload.get("companies", {}):
            dre_company = dre_payload["companies"][ticker]
            for dre_period in dre_company.get("periods", []):
                meta = (dre_company.get("period_metadata") or {}).get(dre_period, {})
                start = _date(meta.get("start_date"))
                end = _date(meta.get("end_date"))
                if not start or not end:
                    continue
                opening_period = _nearest_bp_period(company_payload.get("periods", []), start - timedelta(days=1))
                closing_period = _nearest_bp_period(company_payload.get("periods", []), end)
                if not opening_period or not closing_period:
                    continue
                try:
                    dre_rows = [normalise(r) for r in _dre_period_records(dre_company, dre_period)]
                    revenue = _pick_flow(dre_rows, "revenue", end)
                    cogs_row = _pick_flow(dre_rows, "cogs", end)
                    net_revenue = revenue.value
                    cogs = abs(cogs_row.value)
                    inv0 = _bp_value(company_payload, "inventory", opening_period, scope)
                    inv1 = _bp_value(company_payload, "inventory", closing_period, scope)
                    ar0 = _bp_value(company_payload, "receivables", opening_period, scope)
                    ar1 = _bp_value(company_payload, "receivables", closing_period, scope)
                    ap0 = _bp_value(company_payload, "payables", opening_period, scope)
                    ap1 = _bp_value(company_payload, "payables", closing_period, scope)
                    days = (end - start).days + 1
                    purchases = cogs + inv1 - inv0
                    pmr = _safe_days((ar0 + ar1) / 2, net_revenue, days, "PMR")
                    pme = _safe_days((inv0 + inv1) / 2, cogs, days, "PME")
                    pmp = _safe_days((ap0 + ap1) / 2, purchases, days, "PMP")
                    company_results.append(
                        {
                            "periodo": {
                                "dre": dre_period,
                                "inicio": start.isoformat(),
                                "fim": end.isoformat(),
                                "bp_inicial": opening_period,
                                "bp_final": closing_period,
                                "dias": days,
                            },
                            "indicadores_dias": {
                                "PMP": round(pmp, 4),
                                "PME": round(pme, 4),
                                "PMR": round(pmr, 4),
                                "ciclo_financeiro": round(pmr + pme - pmp, 4),
                            },
                            "bases_calculo": {
                                "receita_liquida": net_revenue,
                                "CMV": cogs,
                                "compras_estimadas": purchases,
                                "contas_a_receber_medio": (ar0 + ar1) / 2,
                                "estoque_medio": (inv0 + inv1) / 2,
                                "fornecedores_medio": (ap0 + ap1) / 2,
                            },
                        }
                    )
                except CalculationError as exc:
                    errors.setdefault(ticker, {})[dre_period] = str(exc)
            results[ticker] = company_results
            continue

        for period in company_payload.get("periods", []):
            try:
                rows = _choose_scope([normalise(r) for r in _bp_period_records(company_payload, period)], scope)
                company_results.append(
                    {
                        "periodo": {"fim": period, "escopo_solicitado": scope},
                        "indicadores_dias": {
                            "PMP": None,
                            "PME": None,
                            "PMR": None,
                            "ciclo_financeiro": None,
                        },
                        "bases_patrimoniais": {
                            "contas_a_receber": _balance_value(rows, "receivables"),
                            "estoques": _balance_value(rows, "inventory"),
                            "fornecedores": _balance_value(rows, "payables"),
                        },
                        "observacao": "Para calcular PMP/PME/PMR e ciclo financeiro, informe tambem o JSON da DRE com --dre.",
                    }
                )
            except CalculationError as exc:
                errors.setdefault(ticker, {})[period] = str(exc)
        results[ticker] = company_results

    return {
        "source_kind": data.get("kind"),
        "unit": "Reais integrais",
        "companies": results,
        "errors": errors,
    }


@dataclass(frozen=True)
class AccountRow:
    code: str
    description: str
    value: float
    start: Optional[date]
    end: Optional[date]
    order: str
    scope: str
    raw: dict[str, Any]


def normalise(record: dict[str, Any]) -> AccountRow:
    code = str(_first(record, "CD_CONTA", "COD_CONTA", "ACCOUNT_CODE", "CONTA") or "").strip()
    desc = str(_first(record, "DS_CONTA", "DESCRICAO", "ACCOUNT_DESCRIPTION") or "").strip()
    value = _number(_first(record, "VL_CONTA", "VALOR", "VALUE", "VL")) * _scale_multiplier(record)
    start = _date(_first(record, "DT_INI_EXERC", "DT_INICIO", "START_DATE"))
    end = _date(_first(record, "DT_FIM_EXERC", "DT_REFER", "DT_REFERENCIA", "END_DATE"))
    order = _text(_first(record, "ORDEM_EXERC", "ORDEM", "PERIOD_ORDER"))
    scope = _text(_first(record, "GRUPO_DFP", "GRUPO_ITR", "ESCOPO", "SCOPE"))
    return AccountRow(code, desc, value, start, end, order, scope, record)


# Contas agregadoras padrao do plano de contas das demonstracoes padronizadas CVM.
ACCOUNT_RULES = {
    "receivables": {
        "codes": ("1.01.03",),
        "descriptions": (r"contas? a receber", r"clientes"),
    },
    "inventory": {
        "codes": ("1.01.04",),
        "descriptions": (r"estoques?",),
    },
    "payables": {
        # 2.01.02 = Fornecedores. 2.01.04 e Emprestimos e Financiamentos.
        "codes": ("2.01.02",),
        "descriptions": (r"fornecedores?",),
    },
    "revenue": {
        "codes": ("3.01",),
        "descriptions": (r"receita de venda", r"receita liquida"),
    },
    "cogs": {
        "codes": ("3.02",),
        "descriptions": (r"custo dos bens", r"custo dos produtos", r"custo dos servicos", r"cmv"),
    },
}


def _is_current(row: AccountRow) -> bool:
    # Evita duplicar a coluna comparativa quando ORDEM_EXERC existe.
    return not row.order or "ultimo" in row.order or row.order in {"1", "atual", "current"}


def _matching(rows: Iterable[AccountRow], kind: str, *, current_only: bool = True) -> list[AccountRow]:
    rule = ACCOUNT_RULES[kind]
    rows = list(rows)
    exact = [r for r in rows if r.code in rule["codes"]]
    candidates = exact or [
        r for r in rows
        if any(re.search(pattern, _text(r.description), re.I) for pattern in rule["descriptions"])
    ]
    if current_only:
        current = [r for r in candidates if _is_current(r)]
        return current or candidates
    return candidates


def _choose_scope(rows: list[AccountRow], requested: str) -> list[AccountRow]:
    if requested == "auto":
        consolidated = [r for r in rows if "consolid" in r.scope]
        return consolidated or rows
    needle = "consolid" if requested == "consolidado" else "individual"
    chosen = [r for r in rows if needle in r.scope]
    if not chosen:
        raise CalculationError(f"Nao foram encontrados registros no escopo {requested!r}.")
    return chosen


def _pick_flow(rows: list[AccountRow], kind: str, target_end: Optional[date]) -> AccountRow:
    candidates = [r for r in _matching(rows, kind) if r.end]
    if target_end:
        candidates = [r for r in candidates if r.end == target_end]
    if not candidates:
        raise CalculationError(f"Conta de {kind} nao encontrada para o periodo solicitado.")
    latest_end = max(r.end for r in candidates if r.end)
    same_end = [r for r in candidates if r.end == latest_end]
    # Se houver periodo trimestral e acumulado com o mesmo fim, usa o de maior duracao.
    # Isso torna receita, CMV e dias internamente consistentes em ITRs acumulados.
    return min(same_end, key=lambda r: r.start or date.max)


def _pick_balance(rows: list[AccountRow], kind: str, when: date, *, opening: bool) -> AccountRow:
    # Colunas comparativas (ORDEM_EXERC=PENULTIMO) sao essenciais para o saldo inicial.
    candidates = [r for r in _matching(rows, kind, current_only=False) if r.end]
    if opening:
        candidates = [r for r in candidates if r.end <= when]
        if not candidates:
            raise CalculationError(
                f"Saldo inicial de {kind} ausente. Inclua um BP com data <= {when.isoformat()}."
            )
        chosen_date = max(r.end for r in candidates if r.end)
    else:
        candidates = [r for r in candidates if r.end == when]
        if not candidates:
            raise CalculationError(f"Saldo final de {kind} ausente em {when.isoformat()}.")
        chosen_date = when
    same_date = [r for r in candidates if r.end == chosen_date]
    return same_date[0]


def _safe_days(numerator: float, denominator: float, days: int, label: str) -> float:
    if denominator <= 0:
        raise CalculationError(f"{label}: denominador deve ser positivo; recebido {denominator}.")
    return numerator / denominator * days


def calculate(
    data: Any,
    target_end: Optional[date] = None,
    scope: str = "auto",
    dre_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if _is_bp_json(data):
        return calculate_bp_json(data, scope=scope, dre_payload=dre_payload)

    raw_records = flatten_records(data)
    if not raw_records:
        raise CalculationError("Nenhum registro de conta reconhecivel foi encontrado no JSON.")
    rows = _choose_scope([normalise(r) for r in raw_records], scope)

    revenue = _pick_flow(rows, "revenue", target_end)
    cogs_row = _pick_flow(rows, "cogs", revenue.end)
    if not revenue.start or not revenue.end:
        raise CalculationError("A DRE precisa informar DT_INI_EXERC e DT_FIM_EXERC/DT_REFER.")
    if cogs_row.start and cogs_row.start != revenue.start:
        raise CalculationError("Receita e CMV encontrados pertencem a periodos iniciais diferentes.")

    start = revenue.start
    end = revenue.end
    days = (end - start).days + 1
    if days <= 0:
        raise CalculationError("Periodo da DRE invalido.")
    opening_date = start - timedelta(days=1)

    ar0 = _pick_balance(rows, "receivables", opening_date, opening=True)
    ar1 = _pick_balance(rows, "receivables", end, opening=False)
    inv0 = _pick_balance(rows, "inventory", opening_date, opening=True)
    inv1 = _pick_balance(rows, "inventory", end, opening=False)
    ap0 = _pick_balance(rows, "payables", opening_date, opening=True)
    ap1 = _pick_balance(rows, "payables", end, opening=False)

    net_revenue = revenue.value
    cogs = abs(cogs_row.value)
    avg_ar = (ar0.value + ar1.value) / 2
    avg_inventory = (inv0.value + inv1.value) / 2
    avg_payables = (ap0.value + ap1.value) / 2
    purchases = cogs + inv1.value - inv0.value

    pmr = _safe_days(avg_ar, net_revenue, days, "PMR")
    pme = _safe_days(avg_inventory, cogs, days, "PME")
    pmp = _safe_days(avg_payables, purchases, days, "PMP")
    financial_cycle = pmr + pme - pmp

    def r(value: float) -> float:
        if not math.isfinite(value):
            raise CalculationError("Resultado nao finito.")
        return round(value, 4)

    return {
        "periodo": {
            "inicio": start.isoformat(),
            "fim": end.isoformat(),
            "dias": days,
            "escopo_solicitado": scope,
        },
        "indicadores_dias": {
            "PMP": r(pmp),
            "PME": r(pme),
            "PMR": r(pmr),
            "ciclo_financeiro": r(financial_cycle),
        },
        "bases_calculo": {
            "receita_liquida": r(net_revenue),
            "CMV": r(cogs),
            "compras_estimadas": r(purchases),
            "contas_a_receber_medio": r(avg_ar),
            "estoque_medio": r(avg_inventory),
            "fornecedores_medio": r(avg_payables),
            "estoque_inicial": r(inv0.value),
            "estoque_final": r(inv1.value),
        },
        "formulas": {
            "PMR": "contas_a_receber_medio / receita_liquida * dias",
            "PME": "estoque_medio / CMV * dias",
            "compras_estimadas": "CMV + estoque_final - estoque_inicial",
            "PMP": "fornecedores_medio / compras_estimadas * dias",
            "ciclo_financeiro": "PMR + PME - PMP",
        },
        "premissas": [
            "Saldos patrimoniais sao calculados pela media entre inicio e fim do periodo.",
            "Compras sao estimadas porque essa rubrica nao e divulgada diretamente na DRE padrao da CVM.",
            "CMV e tratado em modulo, pois custos podem ser apresentados com sinal negativo.",
            "ESCALA_MOEDA=Mil e Milhao, quando presentes, sao convertidas para unidades monetarias.",
        ],
        "contas_selecionadas": {
            "receita": {"codigo": revenue.code, "descricao": revenue.description},
            "CMV": {"codigo": cogs_row.code, "descricao": cogs_row.description},
            "contas_a_receber": {"codigo": ar1.code, "descricao": ar1.description},
            "estoques": {"codigo": inv1.code, "descricao": inv1.description},
            "fornecedores": {"codigo": ap1.code, "descricao": ap1.description},
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Calcula PMP, PME, PMR e ciclo financeiro a partir de ITR CVM em JSON.")
    parser.add_argument("input", type=Path, help="JSON de entrada")
    parser.add_argument("output", type=Path, help="JSON de saida")
    parser.add_argument("--target-end", type=str, help="Data final desejada (AAAA-MM-DD); padrao: periodo mais recente")
    parser.add_argument("--scope", choices=("auto", "consolidado", "individual"), default="auto")
    parser.add_argument("--dre", type=Path, help="JSON gerado pelo app_dre para receita e CMV")
    args = parser.parse_args(argv)

    try:
        with args.input.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        dre_payload = None
        if args.dre:
            with args.dre.open("r", encoding="utf-8-sig") as fh:
                dre_payload = json.load(fh)
        target = _date(args.target_end) if args.target_end else None
        if args.target_end and target is None:
            raise CalculationError("--target-end deve estar no formato AAAA-MM-DD.")
        result = calculate(data, target_end=target, scope=args.scope, dre_payload=dre_payload)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except (OSError, json.JSONDecodeError, CalculationError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

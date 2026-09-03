#!/usr/bin/env python3
"""Indicadores financeiros a partir de JSONs estruturados como ITR/DFP da CVM.

Calcula EBITDA, margens bruta/operacional/EBITDA/liquida e CAGR de
receita liquida e lucro liquido. Nao depende de bibliotecas externas.

Formato recomendado de entrada:
{
  "periodos_por_ano": 1,
  "periodos": [
    {
      "periodo": "2025",
      "dre": [{"CD_CONTA": "3.01", "DS_CONTA": "Receita...", "VL_CONTA": 100}],
      "dva": [{"CD_CONTA": "7.04.01", "DS_CONTA": "Depreciacao...", "VL_CONTA": 5}]
    }
  ]
}

A lista ``dfc`` pode substituir ``dva`` para depreciacao/amortizacao.
Também sao aceitas chaves minusculas ``cd_conta``, ``ds_conta`` e
``vl_conta`` (ou ``codigo``, ``descricao`` e ``valor``).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from metric_definitions import (
    EBITDA_AJUSTADO_SOURCE_RULE,
    EBITDA_CONTABIL_FORMULA,
    EBITDA_LTM_FORMULA,
    EV_EBITDA_LTM_FORMULA,
    EV_FORMULA,
    MATERIALITY_THRESHOLDS,
    METHODOLOGY_VERSION,
    company_rule,
)


# Codigos padronizados da DRE CVM.
COD_RECEITA_LIQUIDA = "3.01"
COD_RESULTADO_BRUTO = "3.03"
COD_EBIT = "3.05"
COD_LUCRO_LIQUIDO = "3.11"
COD_ATIVO_CIRCULANTE = "1.01"
COD_PASSIVO_CIRCULANTE = "2.01"

# Na DVA padronizada, 7.04.01 e depreciacao, amortizacao e exaustao.
COD_DA_DVA = "7.04.01"


class DadosInsuficientesError(ValueError):
    """Indica que uma conta indispensavel nao foi encontrada no JSON."""


def _primeiro(d: dict[str, Any], nomes: Iterable[str], padrao: Any = None) -> Any:
    for nome in nomes:
        if nome in d:
            return d[nome]
    return padrao


def _codigo(linha: dict[str, Any]) -> str:
    valor = _primeiro(linha, ("CD_CONTA", "cd_conta", "codigo", "conta"), "")
    return str(valor).strip()


def _descricao(linha: dict[str, Any]) -> str:
    valor = _primeiro(linha, ("DS_CONTA", "ds_conta", "descricao"), "")
    return str(valor).strip()


def _numero(valor: Any) -> float:
    if isinstance(valor, bool) or valor is None:
        raise ValueError("valor financeiro ausente ou invalido")
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "")
    # Aceita tanto 1.234,56 como 1234.56.
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _valor(linha: dict[str, Any]) -> float:
    bruto = _primeiro(linha, ("VL_CONTA", "vl_conta", "valor"))
    return _numero(bruto)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _parse_period_text(periodo: str) -> tuple[str, str] | None:
    iso = re.findall(r"(20\d{2}-\d{2}-\d{2})", str(periodo))
    if len(iso) >= 3:
        return iso[1], iso[2]
    if len(iso) >= 2:
        return iso[0], iso[-1]
    br = re.findall(r"(\d{2}/\d{2}/20\d{2})", str(periodo))
    if len(br) >= 2:
        start = _parse_date(br[0])
        end = _parse_date(br[-1])
        if start and end:
            return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    return None


def _period_key_from_meta(periodo: str, meta: dict[str, Any] | None) -> tuple[str, str] | None:
    if meta and meta.get("start_date") and meta.get("end_date"):
        return str(meta["start_date"]), str(meta["end_date"])
    return _parse_period_text(periodo)


def _conta_por_codigo(linhas: list[dict[str, Any]], codigo: str) -> float:
    encontrados = [linha for linha in linhas if _codigo(linha) == codigo]
    if not encontrados:
        raise DadosInsuficientesError(f"conta CVM {codigo} nao encontrada")
    if len(encontrados) > 1:
        raise DadosInsuficientesError(
            f"conta CVM {codigo} apareceu {len(encontrados)} vezes no mesmo periodo; "
            "filtre previamente a demonstracao para um unico valor comparavel"
        )
    return _valor(encontrados[0])


def _conta_por_codigo_ou_none(linhas: list[dict[str, Any]], codigo: str) -> float | None:
    try:
        return _conta_por_codigo(linhas, codigo)
    except DadosInsuficientesError:
        return None


def _linha_dre_json(row: dict[str, Any], periodo: str) -> dict[str, Any] | None:
    value = (row.get("values") or {}).get(periodo)
    if value is None:
        return None
    return {
        "CD_CONTA": row.get("code"),
        "DS_CONTA": row.get("description"),
        "VL_CONTA": value,
    }


def _dre_json_periodos(company_payload: dict[str, Any]) -> list[dict[str, Any]]:
    periodos = []
    for periodo in company_payload.get("periods", []):
        linhas = [
            linha
            for row in company_payload.get("rows", [])
            for linha in [_linha_dre_json(row, periodo)]
            if linha is not None
        ]
        if not linhas:
            continue
        meta = (company_payload.get("period_metadata") or {}).get(periodo, {})
        periodos.append(
            {
                "periodo": periodo,
                "dre": linhas,
                "metadata": meta,
            }
        )
    return periodos


def _dfc_da_candidates(company_payload: dict[str, Any]) -> dict[tuple[str, str], float]:
    rows = []
    for row in company_payload.get("rows", []):
        desc = _normalizar(str(row.get("description") or ""))
        if ("depreci" in desc or "depreciac" in desc) and "amort" in desc:
            rows.append(row)
    synthetic_rows = [row for row in rows if row.get("synthetic")]
    if synthetic_rows:
        rows = synthetic_rows
    if not rows:
        return {}

    result: dict[tuple[str, str], float] = {}
    for periodo in company_payload.get("periods", []):
        key = _parse_period_text(periodo)
        if not key:
            continue
        values = [
            (row.get("values") or {}).get(periodo)
            for row in rows
            if (row.get("values") or {}).get(periodo) is not None
        ]
        if not values:
            continue
        result[key] = abs(sum(_numero(value) for value in values))
    return result


def _quarter_number(end_date: str) -> int:
    return (int(end_date[5:7]) - 1) // 3 + 1


def _period_info(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("metadata") or {}
    end_date = meta.get("end_date")
    start_date = meta.get("start_date")
    year = int(meta.get("year") or str(end_date or "0000")[:4] or 0)
    quarter = int(meta.get("quarter") or (_quarter_number(str(end_date)) if end_date else 0))
    is_ytd = bool(meta.get("is_ytd"))
    if start_date and str(start_date).endswith("-01-01"):
        is_ytd = True
    return {"end_date": end_date, "start_date": start_date, "year": year, "quarter": quarter, "is_ytd": is_ytd}


def _quarter_key(year: int, quarter: int) -> tuple[int, int]:
    return year, quarter


def _previous_quarter_key(year: int, quarter: int) -> tuple[int, int] | None:
    if quarter <= 1:
        return None
    return year, quarter - 1


def _metric_value(item: dict[str, Any], metric: str) -> float | None:
    value = item.get(metric)
    return float(value) if value is not None else None


def _build_isolated_quarter_metrics(items: list[dict[str, Any]]) -> None:
    metrics = (
        "receita_contabil_cvm",
        "resultado_bruto",
        "ebit",
        "lucro_liquido",
        "depreciacao_amortizacao",
        "ebitda_contabil",
    )
    ytd_by_q: dict[tuple[int, int], dict[str, Any]] = {}
    sorted_items = sorted(items, key=lambda item: (_period_info(item)["year"], _period_info(item)["quarter"], str(item.get("periodo"))))
    for item in sorted_items:
        info = _period_info(item)
        if info["is_ytd"]:
            ytd_by_q[_quarter_key(info["year"], info["quarter"])] = item

    isolated_by_q: dict[tuple[int, int], dict[str, float | None]] = {}
    for item in sorted_items:
        info = _period_info(item)
        key = _quarter_key(info["year"], info["quarter"])
        item["periodo_individual"] = {
            "year": info["year"],
            "quarter": info["quarter"],
            "label": f"{info['quarter']}T{str(info['year'])[-2:]}",
            "source": "periodo_isolado" if not info["is_ytd"] or info["quarter"] == 1 else "ytd_menos_ytd_anterior",
        }
        isolated: dict[str, float | None] = {}
        previous_key = _previous_quarter_key(info["year"], info["quarter"])
        previous_ytd = ytd_by_q.get(previous_key) if previous_key else None
        for metric in metrics:
            current = _metric_value(item, metric)
            if current is None:
                isolated[metric] = None
                continue
            if info["is_ytd"] and info["quarter"] > 1:
                previous = _metric_value(previous_ytd or {}, metric)
                isolated[metric] = current - previous if previous is not None else None
            else:
                isolated[metric] = current
        item["periodo_individual"]["metrics"] = isolated
        isolated_by_q[key] = isolated

        latest_four = []
        year, quarter = info["year"], info["quarter"]
        for _ in range(4):
            candidate = isolated_by_q.get((year, quarter), {})
            value = candidate.get("ebitda_contabil")
            if value is None:
                latest_four = []
                break
            latest_four.append(float(value))
            quarter -= 1
            if quarter == 0:
                year -= 1
                quarter = 4
        if len(latest_four) == 4:
            item["ebitda_contabil_ltm"] = sum(latest_four)
            item["ebitda_ltm"] = item["ebitda_contabil_ltm"]
            item["quality_flags"] = item.get("quality_flags") or []
        else:
            item["ebitda_contabil_ltm"] = None
            item["ebitda_ltm"] = None
            flags = item.get("quality_flags") or []
            flags.append({"metric": "ebitda_contabil_ltm", "status": "incomplete", "message": "Faltam quatro trimestres individuais comparaveis."})
            item["quality_flags"] = flags


def _da_from_dfc_map(dfc_map: dict[tuple[str, str], float], periodo: str, meta: dict[str, Any] | None) -> float | None:
    key = _period_key_from_meta(periodo, meta)
    if not key:
        return None
    if key in dfc_map:
        return dfc_map[key]

    start, end = key
    if not start.endswith("-01-01"):
        year = end[:4]
        q = _quarter_number(end)
        ytd_current = (f"{year}-01-01", end)
        previous_end_by_quarter = {
            2: f"{year}-03-31",
            3: f"{year}-06-30",
            4: f"{year}-09-30",
        }
        previous_end = previous_end_by_quarter.get(q)
        if previous_end and ytd_current in dfc_map:
            previous = dfc_map.get((f"{year}-01-01", previous_end), 0.0)
            return abs(dfc_map[ytd_current] - previous)
    return None


def calcular_periodo_dre(
    periodo: dict[str, Any],
    dfc_map: dict[tuple[str, str], float] | None = None,
    ev_ebitda_map: dict[str, dict[str, Any]] | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    dre = periodo.get("dre") or periodo.get("DRE") or []
    if not isinstance(dre, list) or not dre:
        raise DadosInsuficientesError("DRE ausente ou vazia")

    receita = _conta_por_codigo(dre, COD_RECEITA_LIQUIDA)
    bruto = _conta_por_codigo_ou_none(dre, COD_RESULTADO_BRUTO)
    ebit = _conta_por_codigo_ou_none(dre, COD_EBIT)
    lucro = _conta_por_codigo_ou_none(dre, COD_LUCRO_LIQUIDO)
    da = _da_from_dfc_map(dfc_map or {}, str(periodo.get("periodo")), periodo.get("metadata"))
    ebitda_contabil = ebit + da if ebit is not None and da is not None else None
    end_date = (periodo.get("metadata") or {}).get("end_date")
    ev_data = (ev_ebitda_map or {}).get(str(end_date), {}) if end_date else {}
    rule = company_rule(ticker or "")

    return {
        "periodo": periodo.get("periodo") or periodo.get("DT_REFER") or periodo.get("dt_refer"),
        "metadata": periodo.get("metadata"),
        "methodology_version": METHODOLOGY_VERSION,
        "receita_liquida": receita,
        "receita_contabil_cvm": receita,
        "receita_operacional_divulgada": None,
        "receita_para_margens": receita if not rule.revenue.ifrs17 else None,
        "denominador_margens": "receita_contabil_cvm" if not rule.revenue.ifrs17 else "receita_operacional_divulgada_indisponivel",
        "resultado_bruto": bruto,
        "ebit": ebit,
        "depreciacao_amortizacao": da,
        "fonte_depreciacao_amortizacao": "DFC_descricao" if da is not None else "nao_encontrado_no_json_dfc",
        "ebitda": ebitda_contabil,
        "ebitda_contabil": ebitda_contabil,
        "ebitda_ajustado_divulgado": None,
        "diferenca_ebitda_ajustado_vs_contabil": None,
        "diferenca_pct_ebitda_ajustado_vs_contabil": None,
        "market_cap_historico": ev_data.get("market_cap_historico"),
        "divida_liquida": ev_data.get("divida_liquida"),
        "divida_liquida_padronizada": ev_data.get("divida_liquida"),
        "divida_liquida_divulgada": None,
        "enterprise_value": ev_data.get("enterprise_value"),
        "ev": ev_data.get("enterprise_value"),
        "ev_ebitda": None,
        "ev_ebitda_ltm": None,
        "fonte_ev_ebitda": ev_data.get("fonte"),
        "lucro_liquido": lucro,
        "margens_percentual": {
            "margem_bruta": _percentual(bruto, receita) if bruto is not None and not rule.revenue.ifrs17 else None,
            "margem_operacional": _percentual(ebit, receita) if ebit is not None and not rule.revenue.ifrs17 else None,
            "margem_ebitda_contabil": _percentual(ebitda_contabil, receita) if ebitda_contabil is not None and not rule.revenue.ifrs17 else None,
            "margem_ebitda": _percentual(ebitda_contabil, receita) if ebitda_contabil is not None and not rule.revenue.ifrs17 else None,
            "margem_liquida": _percentual(lucro, receita) if lucro is not None and not rule.revenue.ifrs17 else None,
        },
        "methodology": {
            "ebitda_contabil": {
                "formula": EBITDA_CONTABIL_FORMULA,
                "components": {
                    "ebit": {"codigo": COD_EBIT, "valor": ebit, "fonte": "DRE CVM"},
                    "depreciacao_amortizacao": {"valor": da, "fonte": "DFC CVM"},
                },
            },
            "ebitda_ajustado_divulgado": {
                "source_rule": EBITDA_AJUSTADO_SOURCE_RULE,
                "fonte": None,
            },
            "receita": {
                "receita_contabil_cvm": {"codigo": COD_RECEITA_LIQUIDA, "valor": receita},
                "ifrs17": rule.revenue.ifrs17,
                "denominador_margens": rule.revenue.denominator_label,
            },
        },
        "quality_flags": (
            [{"metric": "margens", "status": "not_comparable", "message": "HAPV3/IFRS 17: denominador gerencial nao disponivel automaticamente no JSON operacional."}]
            if rule.revenue.ifrs17
            else []
        ),
    }


def _da_por_descricao(dfc: list[dict[str, Any]]) -> float:
    """Localiza uma linha explicita de D&A na DFC sem somar subtotais duplicados."""
    candidatos: list[dict[str, Any]] = []
    for linha in dfc:
        desc = _normalizar(_descricao(linha))
        menciona_dep = "depreci" in desc or "deple" in desc or "exaust" in desc
        menciona_amort = "amortiza" in desc
        if menciona_dep or menciona_amort:
            candidatos.append(linha)

    if not candidatos:
        raise DadosInsuficientesError(
            "depreciacao/amortizacao nao encontrada: forneca DVA 7.04.01, "
            "campo 'depreciacao_amortizacao' ou uma linha explicita na DFC"
        )

    # Se houver uma linha que explicitamente contem depreciacao E amortizacao,
    # ela e preferida para evitar dupla contagem com linhas analiticas.
    combinados = []
    for linha in candidatos:
        desc = _normalizar(_descricao(linha))
        if "depreci" in desc and "amortiza" in desc:
            combinados.append(linha)
    if len(combinados) == 1:
        return abs(_valor(combinados[0]))
    if len(candidatos) == 1:
        return abs(_valor(candidatos[0]))

    raise DadosInsuficientesError(
        "ha varias linhas de depreciacao/amortizacao na DFC e nao e seguro soma-las; "
        "informe 'depreciacao_amortizacao' explicitamente"
    )


def obter_da(periodo: dict[str, Any]) -> tuple[float, str]:
    """Retorna D&A e a fonte usada, em ordem de confiabilidade."""
    if "depreciacao_amortizacao" in periodo:
        return abs(_numero(periodo["depreciacao_amortizacao"])), "campo_explicito"

    dva = periodo.get("dva") or periodo.get("DVA") or []
    if dva:
        try:
            return abs(_conta_por_codigo(dva, COD_DA_DVA)), "DVA_7.04.01"
        except DadosInsuficientesError:
            pass

    dfc = periodo.get("dfc") or periodo.get("DFC") or []
    return _da_por_descricao(dfc), "DFC_descricao"


def _percentual(numerador: float, receita: float) -> float | None:
    if receita == 0:
        return None
    return numerador / receita * 100.0


def calcular_periodo(periodo: dict[str, Any]) -> dict[str, Any]:
    dre = periodo.get("dre") or periodo.get("DRE") or []
    if not isinstance(dre, list) or not dre:
        raise DadosInsuficientesError("DRE ausente ou vazia")

    receita = _conta_por_codigo(dre, COD_RECEITA_LIQUIDA)
    bruto = _conta_por_codigo(dre, COD_RESULTADO_BRUTO)
    ebit = _conta_por_codigo(dre, COD_EBIT)
    lucro = _conta_por_codigo(dre, COD_LUCRO_LIQUIDO)
    da, fonte_da = obter_da(periodo)
    ebitda = ebit + da

    return {
        "periodo": periodo.get("periodo") or periodo.get("DT_REFER") or periodo.get("dt_refer"),
        "receita_liquida": receita,
        "resultado_bruto": bruto,
        "ebit": ebit,
        "depreciacao_amortizacao": da,
        "fonte_depreciacao_amortizacao": fonte_da,
        "ebitda": ebitda,
        "lucro_liquido": lucro,
        "margens_percentual": {
            "margem_bruta": _percentual(bruto, receita),
            "margem_operacional": _percentual(ebit, receita),
            "margem_ebitda": _percentual(ebitda, receita),
            "margem_liquida": _percentual(lucro, receita),
        },
    }


def calcular_cagr(valores: list[float], periodos_por_ano: float = 1.0) -> tuple[float | None, str | None]:
    """CAGR percentual. Cinco observacoes implicam quatro intervalos."""
    if len(valores) < 2:
        return None, "sao necessarios pelo menos 2 periodos"
    inicial, final = valores[0], valores[-1]
    if inicial <= 0 or final <= 0:
        return None, "CAGR padrao nao e definido quando o valor inicial ou final e <= 0"
    anos = (len(valores) - 1) / periodos_por_ano
    if anos <= 0:
        return None, "intervalo temporal invalido"
    taxa = (math.pow(final / inicial, 1.0 / anos) - 1.0) * 100.0
    return taxa, None


def _market_cap_historico_map(payload: dict[str, Any] | None, ticker: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    empresa = (payload.get("empresas") or {}).get(ticker) or (payload.get("companies") or {}).get(ticker)
    if not isinstance(empresa, dict):
        return {}
    result = {}
    for periodo in empresa.get("periodos", []):
        data = periodo.get("data_referencia") or periodo.get("date") or periodo.get("periodo")
        market_cap = periodo.get("market_cap")
        if market_cap is None and periodo.get("preco_acao") is not None and periodo.get("quantidade_acoes_total") is not None:
            market_cap = _numero(periodo["preco_acao"]) * _numero(periodo["quantidade_acoes_total"])
        if data and market_cap is not None:
            result[str(data)] = {
                "market_cap": float(market_cap),
                "quantidade_acoes_yahoo": periodo.get("quantidade_acoes_yahoo"),
                "data_acoes_yahoo": periodo.get("data_acoes_yahoo"),
                "quantidade_acoes_cvm": periodo.get("quantidade_acoes_cvm"),
                "data_acoes_cvm": periodo.get("data_acoes_cvm"),
                "fonte_acoes_utilizada": periodo.get("fonte_acoes_utilizada"),
                "diferenca_acoes_pct": periodo.get("diferenca_acoes_pct"),
                "status_validacao_acoes": periodo.get("status_validacao_acoes"),
                "justificativa_acoes": periodo.get("justificativa_acoes"),
            }
    return result


def _divida_liquida_map(payload: dict[str, Any] | None, ticker: str) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    registros = (payload.get("companies") or {}).get(ticker)
    if not isinstance(registros, list):
        return {}
    result = {}
    for item in registros:
        data = item.get("date")
        value = item.get("divida_liquida_padronizada")
        if value is None:
            value = item.get("value")
        if data and value is not None:
            key = _period_key_from_meta(str(data), None)
            result[key[1] if key else str(data)] = float(value)
    return result


def _balanco_value_map(payload: dict[str, Any] | None, ticker: str, codigo: str) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    empresa = (payload.get("companies") or {}).get(ticker)
    if not isinstance(empresa, dict):
        return {}
    row = next((r for r in empresa.get("rows", []) if str(r.get("code") or "").strip() == codigo), None)
    if not row:
        return {}
    return {
        str(periodo): float(valor)
        for periodo, valor in (row.get("values") or {}).items()
        if valor is not None
    }


def _capital_giro_map(payload: dict[str, Any] | None, ticker: str) -> dict[str, float]:
    ativo = _balanco_value_map(payload, ticker, COD_ATIVO_CIRCULANTE)
    passivo = _balanco_value_map(payload, ticker, COD_PASSIVO_CIRCULANTE)
    return {
        data: ativo[data] - passivo[data]
        for data in ativo.keys() & passivo.keys()
    }


def _ev_ebitda_base_map(
    market_payload: dict[str, Any] | None,
    divida_payload: dict[str, Any] | None,
    ticker: str,
) -> dict[str, dict[str, Any]]:
    market = _market_cap_historico_map(market_payload, ticker)
    divida = _divida_liquida_map(divida_payload, ticker)
    result: dict[str, dict[str, Any]] = {}
    for data, market_data in market.items():
        if data not in divida:
            continue
        net_debt = divida[data]
        market_cap = market_data["market_cap"]
        result[data] = {
            "market_cap_historico": market_cap,
            "divida_liquida": net_debt,
            "enterprise_value": market_cap + net_debt,
            "data_market_cap": data,
            "data_divida_liquida": data,
            "fonte": "app_market_cap_historico + app_divida_liquida",
            "quality_flag": "validated",
            "shares_validation": {key: value for key, value in market_data.items() if key != "market_cap"},
        }
    return result


def calcular_indicadores(
    payload: dict[str, Any],
    dfc_payload: dict[str, Any] | None = None,
    market_cap_historico_payload: dict[str, Any] | None = None,
    divida_liquida_payload: dict[str, Any] | None = None,
    balanco_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload.get("kind") == "dre_itr_cvm" and isinstance(payload.get("companies"), dict):
        return calcular_indicadores_dre_json(
            payload,
            dfc_payload,
            market_cap_historico_payload,
            divida_liquida_payload,
            balanco_payload,
        )

    periodos = payload.get("periodos")
    if not isinstance(periodos, list) or not periodos:
        raise ValueError("o JSON deve conter uma lista nao vazia em 'periodos'")

    periodos_por_ano = _numero(payload.get("periodos_por_ano", 1))
    if periodos_por_ano <= 0:
        raise ValueError("'periodos_por_ano' deve ser maior que zero")

    resultados = [calcular_periodo(p) for p in periodos]
    ultimos = resultados[-5:]

    cagr_receita, erro_receita = calcular_cagr(
        [p["receita_liquida"] for p in ultimos], periodos_por_ano
    )
    cagr_lucro, erro_lucro = calcular_cagr(
        [p["lucro_liquido"] for p in ultimos], periodos_por_ano
    )

    return {
        "periodos": resultados,
        "cagr_ultimos_5_periodos_percentual": {
            "receita_liquida": cagr_receita,
            "lucro_liquido": cagr_lucro,
            "observacoes_utilizadas": len(ultimos),
            "periodos_por_ano": periodos_por_ano,
            "erros": {
                "receita_liquida": erro_receita,
                "lucro_liquido": erro_lucro,
            },
        },
        "metodologia": {
            "ebitda": "EBIT (DRE 3.05) + depreciacao e amortizacao",
            "margens": "indicador / receita liquida (DRE 3.01) * 100",
            "cagr": "(valor_final / valor_inicial) ** (1 / anos_decorridos) - 1",
        },
    }


def calcular_indicadores_dre_json(
    payload: dict[str, Any],
    dfc_payload: dict[str, Any] | None = None,
    market_cap_historico_payload: dict[str, Any] | None = None,
    divida_liquida_payload: dict[str, Any] | None = None,
    balanco_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    dfc_companies = (dfc_payload or {}).get("companies", {}) if isinstance(dfc_payload, dict) else {}

    for ticker, company_payload in payload.get("companies", {}).items():
        company_periods = _dre_json_periodos(company_payload)
        dfc_map = _dfc_da_candidates(dfc_companies.get(ticker, {})) if ticker in dfc_companies else {}
        ev_base = _ev_ebitda_base_map(market_cap_historico_payload, divida_liquida_payload, ticker)
        capital_giro = _capital_giro_map(balanco_payload, ticker)
        indicadores = []
        for periodo in company_periods:
            try:
                item = calcular_periodo_dre(periodo, dfc_map, ev_base, ticker)
                end_date = (item.get("metadata") or {}).get("end_date")
                item["capital_giro"] = capital_giro.get(str(end_date)) if end_date else None
                item["capital_giro_percentual_receita"] = (
                    _percentual(item["capital_giro"], item["receita_liquida"])
                    if item.get("capital_giro") is not None
                    else None
                )
                indicadores.append(item)
            except DadosInsuficientesError as exc:
                errors.setdefault(ticker, {})[periodo.get("periodo")] = str(exc)

        _build_isolated_quarter_metrics(indicadores)
        for item in indicadores:
            end_date = (item.get("metadata") or {}).get("end_date")
            ev_data = ev_base.get(str(end_date), {}) if end_date else {}
            enterprise_value = item.get("enterprise_value")
            ebitda_ltm = item.get("ebitda_contabil_ltm")
            flags = item.get("quality_flags") or []
            if enterprise_value is not None and ebitda_ltm not in (None, 0):
                item["ev_ebitda_ltm"] = enterprise_value / ebitda_ltm
                item["ev_ebitda"] = item["ev_ebitda_ltm"]
                item["data_market_cap"] = ev_data.get("data_market_cap")
                item["data_divida_liquida"] = ev_data.get("data_divida_liquida")
                item["data_ebitda_ltm"] = end_date
                item["quality_ev_ebitda_ltm"] = {
                    "status": ev_data.get("quality_flag", "validated"),
                    "warnings": [],
                }
            else:
                item["ev_ebitda_ltm"] = None
                item["ev_ebitda"] = None
                flags.append({"metric": "ev_ebitda_ltm", "status": "incomplete", "message": "EV ou EBITDA LTM indisponivel; nao ha anualizacao silenciosa."})
                item["quality_ev_ebitda_ltm"] = {"status": "incomplete", "warnings": [flags[-1]["message"]]}
            item["quality_flags"] = flags
            item.setdefault("methodology", {})["ev_ebitda_ltm"] = {
                "formula": EV_EBITDA_LTM_FORMULA,
                "ev_formula": EV_FORMULA,
                "ebitda_ltm_formula": EBITDA_LTM_FORMULA,
                "components": {
                    "enterprise_value": item.get("enterprise_value"),
                    "ebitda_contabil_ltm": item.get("ebitda_contabil_ltm"),
                },
            }

        annual = [
            item for item in indicadores
            if (item.get("metadata") or {}).get("is_ytd") and (item.get("metadata") or {}).get("quarter") == 4
        ]
        base_cagr = annual[-5:] if len(annual) >= 2 else indicadores[-5:]
        cagr_receita, erro_receita = calcular_cagr([p["receita_liquida"] for p in base_cagr])
        lucros = [p["lucro_liquido"] for p in base_cagr if p["lucro_liquido"] is not None]
        cagr_lucro, erro_lucro = calcular_cagr(lucros) if len(lucros) == len(base_cagr) else (None, "lucro liquido ausente em algum periodo")

        results[ticker] = {
            "periodos": indicadores,
            "cagr_ultimos_5_periodos_percentual": {
                "receita_liquida": cagr_receita,
                "lucro_liquido": cagr_lucro,
                "observacoes_utilizadas": len(base_cagr),
                "base": "anual_DFP_quando_disponivel",
                "erros": {
                    "receita_liquida": erro_receita,
                    "lucro_liquido": erro_lucro,
                },
            },
        }

    return {
        "source_kind": payload.get("kind"),
        "methodology_version": METHODOLOGY_VERSION,
        "unit": "Reais integrais",
        "companies": results,
        "errors": errors,
        "observacao": "EBITDA contabil calculado usa EBIT da DRE e depreciacao/amortizacao da DFC. EBITDA ajustado divulgado so e preenchido quando extraido explicitamente de fonte oficial de RI. EV/EBITDA principal e EV/EBITDA LTM.",
    }


def processar_json(
    entrada: str | Path,
    saida: str | Path,
    dfc: str | Path | None = None,
    market_cap_historico: str | Path | None = None,
    divida_liquida: str | Path | None = None,
    balanco: str | Path | None = None,
) -> None:
    with Path(entrada).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    dfc_payload = None
    if dfc:
        with Path(dfc).open("r", encoding="utf-8") as f:
            dfc_payload = json.load(f)
    market_cap_historico_payload = None
    if market_cap_historico:
        with Path(market_cap_historico).open("r", encoding="utf-8") as f:
            market_cap_historico_payload = json.load(f)
    divida_liquida_payload = None
    if divida_liquida:
        with Path(divida_liquida).open("r", encoding="utf-8") as f:
            divida_liquida_payload = json.load(f)
    balanco_payload = None
    if balanco:
        with Path(balanco).open("r", encoding="utf-8") as f:
            balanco_payload = json.load(f)
    resultado = calcular_indicadores(
        payload,
        dfc_payload,
        market_cap_historico_payload,
        divida_liquida_payload,
        balanco_payload,
    )
    with Path(saida).open("w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, allow_nan=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcula indicadores financeiros CVM a partir de JSON.")
    parser.add_argument("entrada", help="arquivo JSON de entrada")
    parser.add_argument("saida", help="arquivo JSON de saida")
    parser.add_argument("--dfc", help="arquivo JSON gerado pelo app_dfc para calcular D&A/EBITDA")
    parser.add_argument("--market-cap-historico", help="arquivo JSON gerado pelo app_market_cap_historico")
    parser.add_argument("--divida-liquida", help="arquivo JSON gerado pelo app_divida_liquida")
    parser.add_argument("--balanco", help="arquivo JSON gerado pelo app_balancos para calcular capital de giro")
    args = parser.parse_args()
    processar_json(args.entrada, args.saida, args.dfc, args.market_cap_historico, args.divida_liquida, args.balanco)


if __name__ == "__main__":
    main()

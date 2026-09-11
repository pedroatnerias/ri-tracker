#!/usr/bin/env python3
"""Calcula o market cap de empresas da B3 com dados do Yahoo Finance.

Instalacao:
    python -m pip install --upgrade yfinance pandas

Execucao:
    python market_cap_yahoo.py

Saida:
    Variaveis impressas diretamente no console.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import argparse
from company_registry import Company, SECTORS, financial_companies
import json
from pathlib import Path


FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")


def primeiro_valor_valido(*valores: Any) -> Any:
    """Retorna o primeiro valor que nao seja None/NaN."""
    for valor in valores:
        if valor is not None and not pd.isna(valor):
            return valor
    return None


def obter_preco(acao: yf.Ticker) -> tuple[float, str]:
    """Obtem o ultimo preco negociado, com fallback para o ultimo fechamento."""
    fast_info = acao.fast_info
    preco = primeiro_valor_valido(
        fast_info.get("last_price"),
        fast_info.get("previous_close"),
    )

    fonte = "fast_info.last_price"
    if preco is None:
        historico = acao.history(period="5d", auto_adjust=False)
        fechamentos = historico["Close"].dropna()
        if fechamentos.empty:
            raise ValueError("O Yahoo Finance nao retornou preco para o ativo.")
        preco = fechamentos.iloc[-1]
        fonte = "history.Close"

    return float(preco), fonte


def obter_variacoes_preco(acao: yf.Ticker, preco_atual: float) -> dict[str, Any]:
    historico = acao.history(period="400d", auto_adjust=True)
    if historico.empty or "Close" not in historico:
        return {
            "preco_30d": None,
            "data_30d": None,
            "variacao_30d_pct": None,
            "preco_90d": None,
            "data_90d": None,
            "variacao_90d_pct": None,
            "preco_360d": None,
            "data_360d": None,
            "variacao_360d_pct": None,
        }
    fechamentos = historico["Close"].dropna().sort_index()
    if fechamentos.empty:
        return {
            "preco_30d": None,
            "data_30d": None,
            "variacao_30d_pct": None,
            "preco_90d": None,
            "data_90d": None,
            "variacao_90d_pct": None,
            "preco_360d": None,
            "data_360d": None,
            "variacao_360d_pct": None,
        }

    preco_comparavel_atual = float(fechamentos.iloc[-1])

    def referencia(dias: int) -> tuple[float | None, str | None, float | None]:
        alvo = pd.Timestamp(fechamentos.index[-1]) - pd.Timedelta(days=dias)
        candidatos = fechamentos[fechamentos.index <= alvo]
        if candidatos.empty:
            return None, None, None
        preco_ref = float(candidatos.iloc[-1])
        data_ref = pd.Timestamp(candidatos.index[-1]).date().isoformat()
        variacao = None if preco_ref == 0 else (preco_comparavel_atual / preco_ref - 1.0) * 100.0
        return preco_ref, data_ref, variacao

    preco_30d, data_30d, variacao_30d = referencia(30)
    preco_90d, data_90d, variacao_90d = referencia(90)
    preco_360d, data_360d, variacao_360d = referencia(360)
    return {
        "preco_30d": preco_30d,
        "data_30d": data_30d,
        "variacao_30d_pct": variacao_30d,
        "preco_90d": preco_90d,
        "data_90d": data_90d,
        "variacao_90d_pct": variacao_90d,
        "preco_360d": preco_360d,
        "data_360d": data_360d,
        "variacao_360d_pct": variacao_360d,
        "metodologia_variacao": "Close auto_adjust=True; data final ancorada no ultimo pregao disponivel",
    }


def obter_acoes_em_circulacao(
    acao: yf.Ticker,
) -> tuple[int, pd.Timestamp | None, str]:
    """Obtem o ultimo total de acoes em circulacao disponivel no Yahoo."""
    try:
        serie = acao.get_shares_full(start="2020-01-01")
    except Exception:
        serie = None

    if serie is not None:
        serie = serie.dropna().sort_index()
        if not serie.empty:
            return int(round(float(serie.iloc[-1]))), pd.Timestamp(serie.index[-1]), "get_shares_full"

    # Fallback: campos pontuais do Yahoo. Nem sempre incluem a data de referencia.
    fast_info = acao.fast_info
    info = acao.get_info()
    quantidade = primeiro_valor_valido(
        fast_info.get("shares"),
        info.get("sharesOutstanding"),
        info.get("impliedSharesOutstanding"),
    )
    if quantidade is None:
        raise ValueError("O Yahoo Finance nao retornou o numero de acoes.")

    return int(round(float(quantidade))), None, "fast_info/info"


def _quantidades_classes_historico(payload: dict[str, Any] | None, company: Company) -> tuple[dict[str, int], str | None]:
    periodos = (((payload or {}).get("empresas") or {}).get(company.ticker) or {}).get("periodos") or []
    for periodo in reversed(periodos):
        if periodo.get("status_validacao_acoes") != "validated_class_sum":
            continue
        classes = periodo.get("classes_acoes") or []
        quantidades = {str(item.get("campo_quantidade_cvm")): int(item["quantidade_acoes"]) for item in classes if item.get("campo_quantidade_cvm") and item.get("quantidade_acoes")}
        if all(share_class.cvm_quantity_field in quantidades for share_class in company.share_classes):
            return quantidades, periodo.get("data_referencia")
    return {}, None


def _market_cap_classes_atual(company: Company, quantidades: dict[str, int], data_acoes: str | None) -> tuple[float, list[dict[str, Any]]]:
    componentes = []
    precos: dict[str, tuple[float, str]] = {}
    for share_class in company.share_classes:
        quantidade = quantidades.get(share_class.cvm_quantity_field)
        if not quantidade:
            raise ValueError(f"Quantidade CVM ausente para {share_class.cvm_quantity_field}")
        if share_class.yahoo_ticker not in precos:
            precos[share_class.yahoo_ticker] = obter_preco(yf.Ticker(share_class.yahoo_ticker))
        preco, fonte_preco = precos[share_class.yahoo_ticker]
        componentes.append({"classe": share_class.class_label, "ticker": share_class.ticker, "ticker_yahoo": share_class.yahoo_ticker, "campo_quantidade_cvm": share_class.cvm_quantity_field, "preco_acao": preco, "quantidade_acoes": quantidade, "peso_economico": share_class.economic_weight, "quantidade_acoes_equivalentes": quantidade * share_class.economic_weight, "data_acoes": data_acoes, "fonte_preco": fonte_preco, "fonte_acoes": "CVM por classe"})
    return sum(item["preco_acao"] * item["quantidade_acoes_equivalentes"] for item in componentes), componentes


def processar_ticker(company: Company, market_cap_historico: dict[str, Any] | None = None) -> dict[str, Any]:
    """Consulta um ticker e calcula preco x acoes em circulacao."""
    ultimo_erro: Exception | None = None
    for ticker_yahoo in company.yahoo_tickers:
        acao = yf.Ticker(ticker_yahoo)
        try:
            preco, fonte_preco = obter_preco(acao)
            variacoes = obter_variacoes_preco(acao, preco)
            if company.share_classes:
                quantidades, data_acoes_referencia = _quantidades_classes_historico(market_cap_historico, company)
                market_cap, classes_acoes = _market_cap_classes_atual(company, quantidades, data_acoes_referencia)
                acoes = sum(item["quantidade_acoes_equivalentes"] for item in classes_acoes)
                acoes_yahoo, _data_yahoo, _fonte_yahoo = obter_acoes_em_circulacao(acao)
                divergencia = abs(acoes_yahoo - acoes) / acoes
                status_validacao_market_cap = "validated_class_sum"
                if divergencia > 0.05:
                    market_cap = None
                    status_validacao_market_cap = "shares_discrepancy"
                data_acoes = pd.Timestamp(data_acoes_referencia) if data_acoes_referencia else None
                fonte_acoes = "CVM por classe"
            else:
                acoes, data_acoes, fonte_acoes = obter_acoes_em_circulacao(acao)
                market_cap = preco * acoes
                classes_acoes = []
                acoes_yahoo = None
                divergencia = None
                status_validacao_market_cap = "single_class"
            break
        except Exception as erro:
            ultimo_erro = erro
    else:
        raise ValueError(
            "O Yahoo Finance nao retornou dados para "
            f"{', '.join(company.yahoo_tickers)}: {ultimo_erro}"
        ) from ultimo_erro

    instante_extracao = datetime.now(timezone.utc)

    return {
        "ticker_b3": company.ticker,
        "ticker_yahoo": ticker_yahoo,
        "ticker_yahoo_alternativos": list(company.yahoo_tickers),
        "moeda": "BRL",
        "ultimo_preco": preco,
        "acoes_em_circulacao": acoes,
        "data_acoes": data_acoes.date().isoformat() if data_acoes is not None else None,
        "market_cap": market_cap,
        "classes_acoes": classes_acoes,
        "quantidade_acoes_yahoo": acoes_yahoo,
        "diferenca_acoes_pct": divergencia * 100.0 if divergencia is not None else None,
        "status_validacao_market_cap": status_validacao_market_cap,
        **variacoes,
        "fonte_preco": fonte_preco,
        "fonte_acoes": fonte_acoes,
        "timestamp_extracao_utc": instante_extracao.isoformat(timespec="seconds"),
        "timestamp_extracao_brasilia": instante_extracao.astimezone(FUSO_BRASILIA).isoformat(
            timespec="seconds"
        ),
        "erro": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcula market cap e historico de precos via Yahoo Finance.")
    parser.add_argument("--saida", "-o", type=Path, help="Arquivo JSON de saida.")
    parser.add_argument("--sector", choices=tuple(sorted(SECTORS)), default="saude")
    parser.add_argument("--market-cap-historico", type=Path, help="JSON historico usado para quantidades por classe.")
    args = parser.parse_args()
    market_cap_historico = json.loads(args.market_cap_historico.read_text(encoding="utf-8")) if args.market_cap_historico and args.market_cap_historico.exists() else None

    resultados: list[dict[str, Any]] = []

    for company in financial_companies(args.sector):
        ticker = company.ticker
        try:
            resultados.append(processar_ticker(company, market_cap_historico))
        except Exception as erro:
            instante_extracao = datetime.now(timezone.utc)
            resultados.append(
                {
                    "ticker_b3": ticker,
                    "ticker_yahoo": company.yahoo_ticker or f"{ticker}.SA",
                    "ticker_yahoo_alternativos": list(company.yahoo_tickers),
                    "moeda": "BRL",
                    "ultimo_preco": None,
                    "acoes_em_circulacao": None,
                    "data_acoes": None,
                    "market_cap": None,
                    "classes_acoes": [],
                    "quantidade_acoes_yahoo": None,
                    "diferenca_acoes_pct": None,
                    "status_validacao_market_cap": "error",
                    "preco_30d": None,
                    "data_30d": None,
                    "variacao_30d_pct": None,
                    "preco_90d": None,
                    "data_90d": None,
                    "variacao_90d_pct": None,
                    "preco_360d": None,
                    "data_360d": None,
                    "variacao_360d_pct": None,
                    "fonte_preco": None,
                    "fonte_acoes": None,
                    "timestamp_extracao_utc": instante_extracao.isoformat(timespec="seconds"),
                    "timestamp_extracao_brasilia": instante_extracao.astimezone(
                        FUSO_BRASILIA
                    ).isoformat(timespec="seconds"),
                    "erro": str(erro),
                }
            )

    if args.saida:
        payload = {
            "source": "Yahoo Finance",
            "unit": "BRL",
            "companies": {resultado["ticker_b3"]: resultado for resultado in resultados},
        }
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Arquivo salvo em {args.saida}")
        return

    for resultado in resultados:
        print("-" * 60)
        for nome, valor in resultado.items():
            print(f"{nome} = {valor!r}")


if __name__ == "__main__":
    main()

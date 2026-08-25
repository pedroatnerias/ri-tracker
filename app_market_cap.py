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
from company_registry import financial_companies
import json
from pathlib import Path


TICKERS = ["AALR3", "DASA3", "FLRY3", "HAPV3", "MATD3", "ONCO3", "RDOR3"]
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
    historico = acao.history(period="400d", auto_adjust=False)
    if historico.empty or "Close" not in historico:
        return {
            "preco_30d": None,
            "variacao_30d_pct": None,
            "preco_360d": None,
            "variacao_360d_pct": None,
        }
    fechamentos = historico["Close"].dropna().sort_index()
    if fechamentos.empty:
        return {
            "preco_30d": None,
            "variacao_30d_pct": None,
            "preco_360d": None,
            "variacao_360d_pct": None,
        }

    def referencia(dias: int) -> tuple[float | None, str | None, float | None]:
        alvo = pd.Timestamp.now(tz=fechamentos.index.tz) - pd.Timedelta(days=dias)
        candidatos = fechamentos[fechamentos.index <= alvo]
        if candidatos.empty:
            return None, None, None
        preco_ref = float(candidatos.iloc[-1])
        data_ref = pd.Timestamp(candidatos.index[-1]).date().isoformat()
        variacao = None if preco_ref == 0 else (preco_atual / preco_ref - 1.0) * 100.0
        return preco_ref, data_ref, variacao

    preco_30d, data_30d, variacao_30d = referencia(30)
    preco_360d, data_360d, variacao_360d = referencia(360)
    return {
        "preco_30d": preco_30d,
        "data_30d": data_30d,
        "variacao_30d_pct": variacao_30d,
        "preco_360d": preco_360d,
        "data_360d": data_360d,
        "variacao_360d_pct": variacao_360d,
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


def processar_ticker(ticker_b3: str) -> dict[str, Any]:
    """Consulta um ticker e calcula preco x acoes em circulacao."""
    ticker_yahoo = f"{ticker_b3}.SA"
    acao = yf.Ticker(ticker_yahoo)

    preco, fonte_preco = obter_preco(acao)
    variacoes = obter_variacoes_preco(acao, preco)
    acoes, data_acoes, fonte_acoes = obter_acoes_em_circulacao(acao)
    instante_extracao = datetime.now(timezone.utc)

    return {
        "ticker_b3": ticker_b3,
        "ticker_yahoo": ticker_yahoo,
        "moeda": "BRL",
        "ultimo_preco": preco,
        "acoes_em_circulacao": acoes,
        "data_acoes": data_acoes.date().isoformat() if data_acoes is not None else None,
        "market_cap": preco * acoes,
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
    parser.add_argument("--sector", choices=("saude", "construcao_civil", "all"), default="saude")
    args = parser.parse_args()

    resultados: list[dict[str, Any]] = []

    for company in financial_companies(args.sector):
        ticker = company.ticker
        try:
            resultados.append(processar_ticker(ticker))
        except Exception as erro:
            instante_extracao = datetime.now(timezone.utc)
            resultados.append(
                {
                    "ticker_b3": ticker,
                    "ticker_yahoo": f"{ticker}.SA",
                    "moeda": "BRL",
                    "ultimo_preco": None,
                    "acoes_em_circulacao": None,
                    "data_acoes": None,
                    "market_cap": None,
                    "preco_30d": None,
                    "data_30d": None,
                    "variacao_30d_pct": None,
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

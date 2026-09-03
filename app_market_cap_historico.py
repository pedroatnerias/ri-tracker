#!/usr/bin/env python3
"""Extrai da CVM o total de acoes e o preco historico por trimestre em JSON.

Fontes:
- Yahoo Finance, via yfinance: quantidade historica e preco de fechamento.
- CVM: validacao/fallback da quantidade em arquivos de composicao do capital.

Dependencia externa: yfinance (pip install yfinance).
"""

from __future__ import annotations

import argparse
from company_registry import company_by_ticker, financial_companies
import csv
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ANO_INICIAL = 2022
LIMITE_DIVERGENCIA_ACOES = 0.05

# O ticker nao faz parte dos CSVs de ITR/DFP. O CNPJ e a chave estavel usada
# para relacionar cada ticker solicitado a companhia nos arquivos da CVM.
EMPRESAS = {
    "AALR3": "42.771.949/0001-35",  # Centro de Imagem Diagnosticos / Alliar
    "DASA3": "61.486.650/0001-83",  # Diagnosticos da America S.A.
    "FLRY3": "60.840.055/0001-31",  # Fleury S.A.
    "HAPV3": "05.197.443/0001-38",  # Hapvida Participacoes e Investimentos S.A.
    "MATD3": "16.676.520/0001-59",  # Hospital Mater Dei S.A.
    "ONCO3": "12.104.241/0004-02",  # Oncoclinicas do Brasil Servicos Medicos S.A.
    "RDOR3": "06.047.087/0001-39",  # Rede D'Or Sao Luiz S.A.
}

URL_ZIP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS/{tipo_lower}_cia_aberta_{ano}.zip"


@dataclass(frozen=True)
class Registro:
    ticker: str
    cnpj: str
    data_referencia: str
    quantidade_acoes_total: int
    versao: int
    documento: str
    denominacao: str


def _quantidade_valida(valor: object) -> int | None:
    try:
        quantidade = int(round(float(valor)))
    except (TypeError, ValueError):
        return None
    return quantidade if quantidade > 0 else None


def _data_indice(indice: object) -> date | None:
    try:
        return pd.Timestamp(indice).date()
    except (TypeError, ValueError):
        return None


def baixar_zip(tipo: str, ano: int, timeout: int = 60) -> bytes | None:
    """Baixa um ZIP anual. Retorna None quando o ano ainda nao foi publicado."""
    url = URL_ZIP.format(tipo=tipo.upper(), tipo_lower=tipo.lower(), ano=ano)
    req = urllib.request.Request(url, headers={"User-Agent": "cvm-acoes-trimestrais/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resposta:
            return resposta.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"Erro HTTP {exc.code} ao baixar {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de rede ao baixar {url}: {exc.reason}") from exc


def localizar_csv_composicao(zf: zipfile.ZipFile, tipo: str, ano: int) -> str:
    esperado = f"{tipo.lower()}_cia_aberta_composicao_capital_{ano}.csv"
    nomes = zf.namelist()
    for nome in nomes:
        if Path(nome).name.lower() == esperado:
            return nome
    candidatos = [n for n in nomes if "composicao_capital" in n.lower() and n.lower().endswith(".csv")]
    if len(candidatos) == 1:
        return candidatos[0]
    raise FileNotFoundError(f"CSV de composicao do capital nao encontrado no ZIP {tipo}/{ano}")


def ler_csv(zf: zipfile.ZipFile, nome: str) -> Iterable[dict[str, str]]:
    bruto = zf.read(nome)
    # Os arquivos historicos da CVM costumam usar Windows-1252; utf-8-sig
    # tambem e aceito para manter compatibilidade caso a codificacao mude.
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252")
    return csv.DictReader(io.StringIO(texto), delimiter=";")


def inteiro(valor: str | None) -> int:
    if valor is None or not valor.strip():
        return 0
    # Quantidades de acoes sao inteiras; Decimal tolera eventual "123.0".
    from decimal import Decimal

    return int(Decimal(valor.strip().replace(",", ".")))


def extrair_ano(tipo: str, ano: int, conteudo_zip: bytes) -> list[Registro]:
    cnpj_para_ticker = {cnpj: ticker for ticker, cnpj in EMPRESAS.items()}
    registros: list[Registro] = []
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as zf:
        nome_csv = localizar_csv_composicao(zf, tipo, ano)
        for linha in ler_csv(zf, nome_csv):
            cnpj = (linha.get("CNPJ_CIA") or "").strip()
            ticker = cnpj_para_ticker.get(cnpj)
            if not ticker:
                continue
            dt = (linha.get("DT_REFER") or "").strip()
            if not dt.startswith(f"{ano}-"):
                continue
            registros.append(
                Registro(
                    ticker=ticker,
                    cnpj=cnpj,
                    data_referencia=dt,
                    quantidade_acoes_total=inteiro(linha.get("QT_ACAO_TOTAL_CAP_INTEGR")),
                    versao=inteiro(linha.get("VERSAO")),
                    documento=tipo.upper(),
                    denominacao=(linha.get("DENOM_CIA") or "").strip(),
                )
            )
    return registros


def datas_trimestrais(ano_inicial: int, hoje: date) -> list[str]:
    datas: list[str] = []
    for ano in range(ano_inicial, hoje.year + 1):
        for mes, dia in ((3, 31), (6, 30), (9, 30), (12, 31)):
            dt = date(ano, mes, dia)
            if dt <= hoje:
                datas.append(dt.isoformat())
    return datas


def consolidar(registros: Iterable[Registro], hoje: date) -> dict:
    # Havendo reapresentacao para a mesma data-base, fica a maior VERSAO.
    # Em 31/12, DFP tem precedencia sobre um eventual registro de ITR.
    escolhidos: dict[tuple[str, str], Registro] = {}
    for r in registros:
        chave = (r.ticker, r.data_referencia)
        atual = escolhidos.get(chave)
        ranking = (r.versao, r.documento == "DFP")
        if atual is None or ranking > (atual.versao, atual.documento == "DFP"):
            escolhidos[chave] = r

    periodos = datas_trimestrais(ANO_INICIAL, hoje)
    empresas: dict[str, dict] = {}
    for ticker, cnpj in EMPRESAS.items():
        serie = []
        for dt in periodos:
            r = escolhidos.get((ticker, dt))
            serie.append(
                {
                    "data_referencia": dt,
                    "quantidade_acoes_total": r.quantidade_acoes_total if r else None,
                    "quantidade_acoes_yahoo": None,
                    "data_acoes_yahoo": None,
                    "quantidade_acoes_cvm": r.quantidade_acoes_total if r else None,
                    "data_acoes_cvm": dt if r else None,
                    "quantidade_acoes_utilizada": r.quantidade_acoes_total if r else None,
                    "fonte_acoes_utilizada": "CVM" if r else None,
                    "diferenca_acoes_pct": None,
                    "status_validacao_acoes": "cvm_only" if r else "missing",
                    "justificativa_acoes": "Yahoo ainda nao consultado; CVM preservada como fallback inicial." if r else "Quantidade CVM ausente.",
                    "fonte_documento": r.documento if r else None,
                    "preco_acao": None,
                    "data_preco": None,
                    "market_cap": None,
                }
            )
        nomes = [r.denominacao for r in escolhidos.values() if r.ticker == ticker and r.denominacao]
        empresas[ticker] = {
            "cnpj": cnpj,
            "denominacao": nomes[-1] if nomes else None,
            "periodos": serie,
        }

    return {
        "metadata": {
            "fonte": "Yahoo Finance primario; CVM para validacao e fallback",
            "campo_cvm": "QT_ACAO_TOTAL_CAP_INTEGR",
            "fonte_acoes_primaria": "Yahoo Finance via yfinance.get_shares_full",
            "limite_divergencia_acoes": LIMITE_DIVERGENCIA_ACOES,
            "fonte_preco": "Yahoo Finance via yfinance",
            "campo_preco": "Close",
            "criterio_preco": "fechamento da data de referencia; se nao houver pregao, ultimo fechamento anterior",
            "data_inicial": f"{ANO_INICIAL}-01-01",
            "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        },
        "empresas": empresas,
    }


def buscar_preco_yfinance(yf, yahoo_ticker: str, referencia: date) -> tuple[float | None, str | None]:
    """Faz uma chamada ao Yahoo para uma unica data de referencia trimestral."""
    # Uma janela curta cobre fins de semana/feriados. `end` no yfinance e exclusivo.
    inicio = referencia - timedelta(days=7)
    fim_exclusivo = referencia + timedelta(days=1)
    historico = yf.Ticker(yahoo_ticker).history(
        start=inicio.isoformat(),
        end=fim_exclusivo.isoformat(),
        auto_adjust=False,
        actions=False,
    )
    if historico.empty or "Close" not in historico.columns:
        return None, None

    fechamentos = historico["Close"].dropna()
    fechamentos = fechamentos[fechamentos.index.date <= referencia]
    if fechamentos.empty:
        return None, None

    indice = fechamentos.index[-1]
    return round(float(fechamentos.iloc[-1]), 6), indice.date().isoformat()


def buscar_acoes_yfinance(yf, yahoo_ticker: str) -> list[tuple[date, int]]:
    """Retorna a serie historica de acoes do Yahoo, normalizada por data."""
    serie = yf.Ticker(yahoo_ticker).get_shares_full(start=f"{ANO_INICIAL}-01-01")
    if serie is None:
        return []
    if hasattr(serie, "columns"):
        coluna = "Shares" if "Shares" in serie.columns else serie.columns[0]
        serie = serie[coluna]
    resultado = []
    for indice, valor in serie.dropna().items():
        data = _data_indice(indice)
        quantidade = _quantidade_valida(valor)
        if data and quantidade:
            resultado.append((data, quantidade))
    return sorted(resultado, key=lambda item: item[0])


def _acoes_yahoo_na_data(serie: list[tuple[date, int]], referencia: date) -> tuple[int | None, date | None]:
    candidatos = [(data, quantidade) for data, quantidade in serie if data <= referencia]
    if not candidatos:
        return None, None
    data, quantidade = candidatos[-1]
    return quantidade, data


def validar_quantidade_acoes(yahoo: int | None, cvm: int | None) -> dict[str, object]:
    """Resolve a fonte de acoes sem ocultar divergencias materiais."""
    yahoo = _quantidade_valida(yahoo)
    cvm = _quantidade_valida(cvm)
    if yahoo and cvm:
        diferenca = abs(yahoo - cvm) / cvm
        if diferenca > LIMITE_DIVERGENCIA_ACOES:
            return {
                "quantidade": None,
                "fonte": None,
                "diferenca_pct": diferenca * 100.0,
                "status": "shares_discrepancy",
                "justificativa": "Yahoo e CVM divergem acima de 5%; market cap bloqueado para revisao.",
            }
        return {
            "quantidade": yahoo,
            "fonte": "Yahoo Finance",
            "diferenca_pct": diferenca * 100.0,
            "status": "validated",
            "justificativa": "Yahoo utilizado; diferenca contra CVM dentro do limite de 5%.",
        }
    if yahoo:
        return {"quantidade": yahoo, "fonte": "Yahoo Finance", "diferenca_pct": None, "status": "yahoo_only", "justificativa": "Yahoo utilizado; CVM ausente para a data."}
    if cvm:
        return {"quantidade": cvm, "fonte": "CVM", "diferenca_pct": None, "status": "cvm_fallback", "justificativa": "CVM utilizada como fallback porque Yahoo nao retornou quantidade valida."}
    return {"quantidade": None, "fonte": None, "diferenca_pct": None, "status": "missing", "justificativa": "Nenhuma fonte retornou quantidade valida."}


def adicionar_precos_yfinance(resultado: dict) -> None:
    """Preenche acoes/preco historicos, validando Yahoo contra CVM por trimestre.

    O Yahoo usa o sufixo .SA para a B3. `auto_adjust=False` preserva o Close
    historico nao ajustado, adequado para combinar preco e quantidade de acoes
    observados na mesma data historica.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "A dependencia 'yfinance' nao esta instalada. Execute: pip install yfinance"
        ) from exc

    for ticker, empresa in resultado["empresas"].items():
        yahoo_tickers = company_by_ticker(ticker).yahoo_tickers
        shares_series: list[tuple[date, int]] = []
        ticker_shares = None
        for yahoo_ticker in yahoo_tickers:
            try:
                shares_series = buscar_acoes_yfinance(yf, yahoo_ticker)
                if shares_series:
                    ticker_shares = yahoo_ticker
                    break
            except Exception as exc:
                print(f"Aviso: falha ao buscar acoes {yahoo_ticker}: {exc}", file=sys.stderr)
        for periodo in empresa["periodos"]:
            referencia = date.fromisoformat(periodo["data_referencia"])
            yahoo_shares, yahoo_date = _acoes_yahoo_na_data(shares_series, referencia)
            cvm_shares = _quantidade_valida(periodo.get("quantidade_acoes_cvm"))
            periodo["quantidade_acoes_yahoo"] = yahoo_shares
            periodo["data_acoes_yahoo"] = yahoo_date.isoformat() if yahoo_date else None
            periodo["quantidade_acoes_cvm"] = cvm_shares
            periodo["data_acoes_cvm"] = periodo["data_referencia"] if cvm_shares else None
            resolved = validar_quantidade_acoes(yahoo_shares, cvm_shares)
            periodo["quantidade_acoes_utilizada"] = resolved["quantidade"]
            periodo["quantidade_acoes_total"] = resolved["quantidade"]
            periodo["fonte_acoes_utilizada"] = resolved["fonte"]
            periodo["diferenca_acoes_pct"] = resolved["diferenca_pct"]
            periodo["status_validacao_acoes"] = resolved["status"]
            periodo["justificativa_acoes"] = resolved["justificativa"]
            preco = None
            data_preco = None
            for yahoo_ticker in yahoo_tickers:
                print(
                    f"Buscando {yahoo_ticker} para {referencia.isoformat()} no Yahoo Finance...",
                    file=sys.stderr,
                )
                try:
                    preco, data_preco = buscar_preco_yfinance(yf, yahoo_ticker, referencia)
                except Exception as exc:  # falha externa nao invalida os dados da CVM
                    print(
                        f"Aviso: falha ao buscar {yahoo_ticker} em {referencia.isoformat()}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                if preco is not None:
                    periodo["ticker_yahoo"] = yahoo_ticker
                    break
            periodo["preco_acao"] = preco
            periodo["data_preco"] = data_preco
            if periodo.get("quantidade_acoes_utilizada") and preco is not None and periodo.get("status_validacao_acoes") != "shares_discrepancy":
                periodo["market_cap"] = preco * periodo["quantidade_acoes_utilizada"]
            else:
                periodo["market_cap"] = None
            if ticker_shares:
                periodo["ticker_yahoo"] = ticker_shares


def executar(saida: str, ano_final: int | None = None) -> dict:
    hoje = date.today()
    fim = min(ano_final or hoje.year, hoje.year)
    todos: list[Registro] = []

    for ano in range(ANO_INICIAL, fim + 1):
        # ITR cobre os trimestres intermediarios. DFP cobre o fechamento anual.
        tipos = ["ITR"] + (["DFP"] if ano < hoje.year else [])
        for tipo in tipos:
            print(f"Baixando {tipo} {ano}...", file=sys.stderr)
            conteudo = baixar_zip(tipo, ano)
            if conteudo is None:
                print(f"Aviso: {tipo} {ano} ainda nao esta disponivel; ignorando.", file=sys.stderr)
                continue
            todos.extend(extrair_ano(tipo, ano, conteudo))

    resultado = consolidar(todos, hoje)
    adicionar_precos_yfinance(resultado)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrai o total trimestral de acoes dos ITRs/DFPs da CVM.")
    parser.add_argument(
        "--saida",
        default="acoes_totais_trimestrais_cvm.json",
        help="Arquivo JSON de saida (padrao: %(default)s).",
    )
    parser.add_argument("--sector", choices=("saude", "construcao_civil", "all"), default="saude")
    args = parser.parse_args()
    global EMPRESAS
    EMPRESAS = {c.ticker: c.cnpj for c in financial_companies(args.sector)}
    resultado = executar(args.saida)
    preenchidos = sum(
        p["quantidade_acoes_total"] is not None
        for e in resultado["empresas"].values()
        for p in e["periodos"]
    )
    print(f"Concluido: {preenchidos} observacoes gravadas em {args.saida}", file=sys.stderr)


if __name__ == "__main__":
    main()

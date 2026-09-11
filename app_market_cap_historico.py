#!/usr/bin/env python3
"""Extrai da CVM o total de acoes e o preco historico por trimestre em JSON.

Fontes:
- Yahoo Finance, via yfinance: quantidade historica e preco de fechamento.
- CVM: validacao/fallback da quantidade em arquivos de composicao do capital.

Dependencia externa: yfinance (pip install yfinance).
"""

from __future__ import annotations

import argparse
from company_registry import SECTORS, ShareClass, company_by_ticker, financial_companies
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
MAX_PRICE_STALENESS_DAYS = 7

# O ticker nao faz parte dos CSVs de ITR/DFP. O CNPJ e a chave estavel usada
# para relacionar cada ticker solicitado a companhia nos arquivos da CVM.
EMPRESAS = {company.ticker: company.cnpj for company in financial_companies("saude")}

URL_ZIP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS/{tipo_lower}_cia_aberta_{ano}.zip"


@dataclass(frozen=True)
class Registro:
    ticker: str
    cnpj: str
    data_referencia: str
    quantidade_acoes_total: int
    quantidade_acoes_on: int
    quantidade_acoes_pn: int
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
                    quantidade_acoes_on=inteiro(linha.get("QT_ACAO_ORDIN_CAP_INTEGR")),
                    quantidade_acoes_pn=inteiro(linha.get("QT_ACAO_PREF_CAP_INTEGR")),
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
                    "quantidade_acoes_on_cvm": r.quantidade_acoes_on if r else None,
                    "quantidade_acoes_pn_cvm": r.quantidade_acoes_pn if r else None,
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
                    "preco_acao_ajustado": None,
                    "data_preco": None,
                    "market_cap": None,
                    "classes_acoes": [],
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
            "campo_preco": "Close revertido por eventos Stock Splits posteriores",
            "criterio_preco": "preco nominal ponto-no-tempo, compativel com a quantidade de acoes da data",
            "defasagem_maxima_preco_dias": MAX_PRICE_STALENESS_DAYS,
            "data_inicial": f"{ANO_INICIAL}-01-01",
            "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        },
        "empresas": empresas,
    }


def preco_market_cap_na_data(historico: pd.DataFrame, referencia: date) -> tuple[float | None, str | None]:
    """Reverte o ajuste retroativo de splits do Yahoo para obter preco ponto-no-tempo."""
    if historico.empty or "Close" not in historico.columns:
        return None, None

    fechamentos = historico["Close"].dropna()
    fechamentos = fechamentos[fechamentos.index.date <= referencia]
    if fechamentos.empty:
        return None, None

    indice = fechamentos.index[-1]
    if (referencia - indice.date()).days > MAX_PRICE_STALENESS_DAYS:
        return None, None
    preco = float(fechamentos.iloc[-1])
    if "Stock Splits" in historico.columns:
        eventos_futuros = historico.loc[historico.index > indice, "Stock Splits"].dropna()
        for fator in eventos_futuros[eventos_futuros != 0]:
            preco *= float(fator)
    return round(preco, 6), indice.date().isoformat()


def preco_ajustado_na_data(historico: pd.DataFrame, referencia: date) -> tuple[float | None, str | None]:
    """Retorna serie economicamente comparavel, sem reverter splits futuros."""
    if historico.empty:
        return None, None
    coluna = "Adj Close" if "Adj Close" in historico.columns else "Close"
    if coluna not in historico.columns:
        return None, None
    fechamentos = historico[coluna].dropna()
    fechamentos = fechamentos[fechamentos.index.date <= referencia]
    if fechamentos.empty:
        return None, None
    indice = fechamentos.index[-1]
    if (referencia - indice.date()).days > MAX_PRICE_STALENESS_DAYS:
        return None, None
    return round(float(fechamentos.iloc[-1]), 6), indice.date().isoformat()


def calcular_market_cap_classes(classes: list[dict[str, object]]) -> float | None:
    """Soma preco x quantidade somente quando todas as classes sao validas."""
    if not classes:
        return None
    total = 0.0
    for item in classes:
        preco = item.get("preco_acao")
        quantidade = _quantidade_valida(item.get("quantidade_acoes"))
        if preco is None or quantidade is None:
            return None
        peso = float(item.get("peso_economico", 1.0))
        if peso <= 0:
            return None
        total += float(preco) * quantidade * peso
    return total


def _quantidade_classe(periodo: dict, share_class: ShareClass) -> int | None:
    fields = {
        "QT_ACAO_ORDIN_CAP_INTEGR": "quantidade_acoes_on_cvm",
        "QT_ACAO_PREF_CAP_INTEGR": "quantidade_acoes_pn_cvm",
    }
    return _quantidade_valida(periodo.get(fields[share_class.cvm_quantity_field]))


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
        candidatos = ((cvm, 1), (cvm * 1_000, 1_000))
        cvm_normalizado, escala_cvm = min(candidatos, key=lambda item: abs(yahoo - item[0]) / item[0])
        diferenca = abs(yahoo - cvm_normalizado) / cvm_normalizado
        if diferenca > LIMITE_DIVERGENCIA_ACOES:
            return {
                "quantidade": None,
                "fonte": None,
                "diferenca_pct": diferenca * 100.0,
                "status": "shares_discrepancy",
                "escala_cvm": None,
                "justificativa": "Yahoo e CVM divergem acima de 5%, inclusive apos testar escala CVM de milhares; market cap bloqueado para revisao.",
            }
        return {
            "quantidade": yahoo,
            "fonte": "Yahoo Finance",
            "diferenca_pct": diferenca * 100.0,
            "status": "validated",
            "escala_cvm": escala_cvm,
            "justificativa": f"Yahoo utilizado; diferenca contra CVM dentro do limite de 5% (escala CVM x{escala_cvm}).",
        }
    if yahoo:
        return {"quantidade": yahoo, "fonte": "Yahoo Finance", "diferenca_pct": None, "status": "yahoo_only", "escala_cvm": None, "justificativa": "Yahoo utilizado; CVM ausente para a data."}
    if cvm:
        return {"quantidade": cvm, "fonte": "CVM", "diferenca_pct": None, "status": "cvm_fallback", "escala_cvm": None, "justificativa": "CVM utilizada sem ajuste de escala porque Yahoo nao retornou quantidade valida."}
    return {"quantidade": None, "fonte": None, "diferenca_pct": None, "status": "missing", "escala_cvm": None, "justificativa": "Nenhuma fonte retornou quantidade valida."}


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

    historicos_precos: dict[str, pd.DataFrame] = {}

    def preco_na_data(yahoo_ticker: str, referencia: date) -> tuple[float | None, str | None]:
        if yahoo_ticker not in historicos_precos:
            historicos_precos[yahoo_ticker] = yf.Ticker(yahoo_ticker).history(
                start=f"{ANO_INICIAL}-01-01",
                end=(date.today() + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=True,
            )
        return preco_market_cap_na_data(historicos_precos[yahoo_ticker], referencia)

    for ticker, empresa in resultado["empresas"].items():
        company = company_by_ticker(ticker)
        yahoo_tickers = company.yahoo_tickers
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
            if company.share_classes:
                classes = []
                for share_class in company.share_classes:
                    try:
                        preco_classe, data_classe = preco_na_data(share_class.yahoo_ticker, referencia)
                    except Exception as exc:
                        print(f"Aviso: falha ao buscar classe {share_class.yahoo_ticker} em {referencia}: {exc}", file=sys.stderr)
                        preco_classe, data_classe = None, None
                    quantidade_reportada = _quantidade_classe(periodo, share_class)
                    classes.append({
                        "classe": share_class.class_label,
                        "ticker": share_class.ticker,
                        "ticker_yahoo": share_class.yahoo_ticker,
                        "campo_quantidade_cvm": share_class.cvm_quantity_field,
                        "quantidade_acoes_cvm_reportada": quantidade_reportada,
                        "quantidade_acoes": quantidade_reportada * share_class.cvm_quantity_scale if quantidade_reportada else None,
                        "peso_economico": share_class.economic_weight,
                        "quantidade_acoes_equivalentes": quantidade_reportada * share_class.cvm_quantity_scale * share_class.economic_weight if quantidade_reportada else None,
                        "escala_cvm": share_class.cvm_quantity_scale,
                        "fonte_acoes": "CVM",
                        "preco_acao": preco_classe,
                        "data_preco": data_classe,
                    })
                periodo["classes_acoes"] = classes
                periodo["quantidade_acoes_yahoo"] = yahoo_shares
                periodo["data_acoes_yahoo"] = yahoo_date.isoformat() if yahoo_date else None
                periodo["quantidade_acoes_utilizada"] = sum(float(item["quantidade_acoes_equivalentes"]) for item in classes) if all(item["quantidade_acoes_equivalentes"] for item in classes) else None
                periodo["quantidade_acoes_total"] = periodo["quantidade_acoes_utilizada"]
                periodo["fonte_acoes_utilizada"] = "CVM por classe" if periodo["quantidade_acoes_utilizada"] else None
                periodo["diferenca_acoes_pct"] = None
                periodo["status_validacao_acoes"] = "validated_class_sum" if periodo["quantidade_acoes_utilizada"] and all(item["preco_acao"] is not None for item in classes) else "missing_share_class_data"
                periodo["escala_cvm"] = sorted({item["escala_cvm"] for item in classes})
                periodo["justificativa_acoes"] = "Market cap calculado pela soma de preco x quantidade x peso economico de cada classe." if periodo["status_validacao_acoes"] == "validated_class_sum" else "Market cap bloqueado: preco ou quantidade ausente para ao menos uma classe."
                principal = next((item for item in classes if item["ticker"] == company.ticker), classes[0])
                periodo["preco_acao"] = principal["preco_acao"]
                periodo["preco_acao_ajustado"] = preco_ajustado_na_data(historicos_precos[principal["ticker_yahoo"]], referencia)[0]
                periodo["data_preco"] = principal["data_preco"]
                periodo["ticker_yahoo"] = principal["ticker_yahoo"]
                periodo["market_cap"] = calcular_market_cap_classes(classes) if periodo["status_validacao_acoes"] == "validated_class_sum" else None
                continue
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
            periodo["escala_cvm"] = resolved["escala_cvm"]
            periodo["justificativa_acoes"] = resolved["justificativa"]
            preco = None
            data_preco = None
            for yahoo_ticker in yahoo_tickers:
                print(
                    f"Buscando {yahoo_ticker} para {referencia.isoformat()} no Yahoo Finance...",
                    file=sys.stderr,
                )
                try:
                    preco, data_preco = preco_na_data(yahoo_ticker, referencia)
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
            historico_usado = historicos_precos.get(periodo.get("ticker_yahoo") or "")
            periodo["preco_acao_ajustado"] = preco_ajustado_na_data(historico_usado, referencia)[0] if historico_usado is not None else None
            periodo["data_preco"] = data_preco
            if periodo.get("quantidade_acoes_utilizada") and preco is not None and periodo.get("status_validacao_acoes") != "shares_discrepancy":
                periodo["market_cap"] = preco * periodo["quantidade_acoes_utilizada"]
            else:
                periodo["market_cap"] = None
            if ticker_shares:
                periodo["ticker_yahoo_acoes"] = ticker_shares


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
    parser.add_argument("--sector", choices=tuple(sorted(SECTORS)), default="saude")
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

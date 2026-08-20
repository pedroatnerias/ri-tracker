#!/usr/bin/env python3
"""Extrai da CVM o total de acoes e o preco historico por trimestre em JSON.

Fontes:
- CVM: arquivos de "composicao do capital" dos ITRs e DFPs.
- Yahoo Finance, via yfinance: preco de fechamento da acao.

Dependencia externa: yfinance (pip install yfinance).
"""

from __future__ import annotations

import argparse
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


ANO_INICIAL = 2022

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
                    "fonte_documento": r.documento if r else None,
                    "preco_acao": None,
                    "data_preco": None,
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
            "fonte": "CVM - ITR/DFP - composicao do capital",
            "campo_cvm": "QT_ACAO_TOTAL_CAP_INTEGR",
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


def adicionar_precos_yfinance(resultado: dict) -> None:
    """Preenche preco_acao/data_preco fazendo uma chamada por ticker e trimestre.

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
        yahoo_ticker = f"{ticker}.SA"
        for periodo in empresa["periodos"]:
            # So existe uma data-base identificada quando a CVM trouxe o total de acoes.
            if periodo["quantidade_acoes_total"] is None:
                continue
            referencia = date.fromisoformat(periodo["data_referencia"])
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
            periodo["preco_acao"] = preco
            periodo["data_preco"] = data_preco


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
    args = parser.parse_args()
    resultado = executar(args.saida)
    preenchidos = sum(
        p["quantidade_acoes_total"] is not None
        for e in resultado["empresas"].values()
        for p in e["periodos"]
    )
    print(f"Concluido: {preenchidos} observacoes gravadas em {args.saida}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Análise vertical (BP) e horizontal (BP/DRE) para JSONs de ITRs da CVM.

Sem dependências externas. O módulo aceita registros planos no estilo CVM ou
JSONs agrupados por período e exporta um único JSON com BP e DRE analisados.

Uso pela linha de comando:
    python analise_vertical_horizontal_cvm.py bp.json dre.json resultado.json

Uso como módulo:
    from analise_vertical_horizontal_cvm import analisar_arquivos
    analisar_arquivos("bp.json", "dre.json", "resultado.json")
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


# Aliases permitem integrar o módulo a JSONs já tratados, além dos nomes CVM.
ALIASES = {
    "codigo": ("CD_CONTA", "cd_conta", "codigo", "codigo_conta", "conta"),
    "descricao": ("DS_CONTA", "ds_conta", "descricao", "descricao_conta"),
    "valor": ("VL_CONTA", "vl_conta", "valor", "value"),
    "periodo": (
        "DT_FIM_EXERC",
        "dt_fim_exerc",
        "DT_REFER",
        "dt_refer",
        "periodo",
        "data",
        "date",
    ),
    "inicio": ("DT_INI_EXERC", "dt_ini_exerc", "inicio_periodo", "data_inicio"),
}

CONTAINER_KEYS = ("contas", "linhas", "items", "registros", "records", "estrutura")
PERIOD_CONTAINER_KEYS = ("periodos", "periods", "demonstracoes", "statements")


def _primeiro(dado: dict[str, Any], nomes: Iterable[str], padrao: Any = None) -> Any:
    for nome in nomes:
        if nome in dado and dado[nome] is not None:
            return dado[nome]
    return padrao


def _texto_normalizado(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).strip().lower()


def _numero(valor: Any) -> float | None:
    """Converte números JSON e strings pt-BR/en-US sem aceitar NaN/inf."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        numero = float(valor)
        return numero if math.isfinite(numero) else None

    texto = str(valor).strip().replace("\u00a0", "").replace(" ", "")
    if not texto or texto.lower() in {"null", "none", "nan", "-"}:
        return None
    negativo = texto.startswith("(") and texto.endswith(")")
    texto = texto.strip("()")

    # Se ambos separadores existem, o último é tratado como decimal.
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        numero = float(Decimal(texto))
    except (InvalidOperation, ValueError):
        return None
    if negativo:
        numero = -numero
    return numero if math.isfinite(numero) else None


def _ordenar_periodo(valor: str) -> tuple[int, Any]:
    texto = str(valor)
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m", "%Y"):
        try:
            return (0, datetime.strptime(texto, formato))
        except ValueError:
            pass
    return (1, texto)


def _extrair_registros(objeto: Any) -> list[dict[str, Any]]:
    """Normaliza JSON plano ou agrupado em registros com período herdado."""
    saida: list[dict[str, Any]] = []

    def visitar(no: Any, periodo_herdado: Any = None, inicio_herdado: Any = None) -> None:
        if isinstance(no, list):
            for item in no:
                visitar(item, periodo_herdado, inicio_herdado)
            return
        if not isinstance(no, dict):
            return

        periodo = _primeiro(no, ALIASES["periodo"], periodo_herdado)
        inicio = _primeiro(no, ALIASES["inicio"], inicio_herdado)
        codigo = _primeiro(no, ALIASES["codigo"])
        descricao = _primeiro(no, ALIASES["descricao"])
        tem_valor = any(k in no for k in ALIASES["valor"])

        if (codigo is not None or descricao is not None) and tem_valor:
            registro = dict(no)
            registro["__periodo"] = periodo
            registro["__inicio"] = inicio
            saida.append(registro)
            return

        for chave in PERIOD_CONTAINER_KEYS + CONTAINER_KEYS:
            filho = no.get(chave)
            if isinstance(filho, (list, dict)):
                visitar(filho, periodo, inicio)

    visitar(objeto)
    if not saida:
        raise ValueError(
            "Nenhuma conta foi encontrada no JSON. Cada conta deve conter código/descrição "
            "e valor; em registros planos, inclua também o período."
        )
    return saida


def _chave_conta(registro: dict[str, Any]) -> str:
    codigo = _primeiro(registro, ALIASES["codigo"])
    if codigo is not None and str(codigo).strip():
        return f"codigo:{str(codigo).strip()}"
    descricao = _texto_normalizado(_primeiro(registro, ALIASES["descricao"]))
    return f"descricao:{descricao}"


def _codigo(registro: dict[str, Any]) -> str | None:
    valor = _primeiro(registro, ALIASES["codigo"])
    return str(valor).strip() if valor is not None else None


def _descricao(registro: dict[str, Any]) -> str | None:
    valor = _primeiro(registro, ALIASES["descricao"])
    return str(valor).strip() if valor is not None else None


def _valor(registro: dict[str, Any]) -> float | None:
    return _numero(_primeiro(registro, ALIASES["valor"]))


def _periodo(registro: dict[str, Any]) -> str:
    valor = registro.get("__periodo")
    if valor is None:
        raise ValueError("Conta sem período/data. Não é possível calcular análise horizontal.")
    return str(valor)


def _achar_total_bp(registros: list[dict[str, Any]], lado: str) -> float | None:
    """Busca Ativo Total (código 1) ou Passivo Total (código 2)."""
    codigo_alvo = "1" if lado == "ativo" else "2"
    descricoes = {"ativo total"} if lado == "ativo" else {"passivo total", "passivo e patrimonio liquido"}

    for r in registros:
        if _codigo(r) == codigo_alvo and _valor(r) is not None:
            return _valor(r)
    for r in registros:
        desc = _texto_normalizado(_descricao(r))
        if desc in descricoes and _valor(r) is not None:
            return _valor(r)
    return None


def _lado_bp(registro: dict[str, Any]) -> str | None:
    codigo = _codigo(registro) or ""
    primeiro_bloco = re.split(r"[.\-\s]", codigo, maxsplit=1)[0]
    if primeiro_bloco == "1":
        return "ativo"
    if primeiro_bloco == "2":
        return "passivo"
    desc = _texto_normalizado(_descricao(registro))
    if desc.startswith("ativo"):
        return "ativo"
    if desc.startswith("passivo") or "patrimonio liquido" in desc:
        return "passivo"
    return None


def _variacao_horizontal(atual: float | None, anterior: float | None) -> float | None:
    # Não existe percentual matematicamente definido com base anterior igual a zero.
    if atual is None or anterior is None or anterior == 0:
        return None
    return ((atual / anterior) - 1.0) * 100.0


def _arredondar(valor: float | None, casas: int) -> float | None:
    return None if valor is None else round(valor, casas)


def analisar_demonstracao(
    dados: Any,
    tipo: str,
    *,
    casas_percentuais: int = 4,
) -> dict[str, Any]:
    """Analisa uma demonstração já carregada de JSON.

    `tipo` deve ser ``bp`` ou ``dre``. A análise horizontal compara cada conta
    com a mesma conta no período imediatamente anterior disponível.
    """
    tipo = tipo.lower()
    if tipo not in {"bp", "dre"}:
        raise ValueError("tipo deve ser 'bp' ou 'dre'.")

    registros = _extrair_registros(dados)
    por_periodo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for registro in registros:
        por_periodo[_periodo(registro)].append(registro)
    periodos = sorted(por_periodo, key=_ordenar_periodo)

    # Mapa da conta no período anterior. O código CVM é a chave preferencial.
    anteriores: dict[str, float | None] = {}
    periodos_saida: list[dict[str, Any]] = []

    for indice, periodo in enumerate(periodos):
        contas_periodo = por_periodo[periodo]
        totais = {}
        if tipo == "bp":
            totais = {
                "ativo": _achar_total_bp(contas_periodo, "ativo"),
                "passivo": _achar_total_bp(contas_periodo, "passivo"),
            }

        contas_saida = []
        for registro in contas_periodo:
            chave = _chave_conta(registro)
            atual = _valor(registro)
            anterior = anteriores.get(chave)
            ah = _variacao_horizontal(atual, anterior) if indice > 0 else None

            conta = {
                "codigo": _codigo(registro),
                "descricao": _descricao(registro),
                "valor": atual,
                "analise_horizontal_pct": _arredondar(ah, casas_percentuais),
            }

            if tipo == "bp":
                lado = _lado_bp(registro)
                denominador = totais.get(lado) if lado else None
                av = None if atual is None or denominador in (None, 0) else atual / denominador * 100.0
                conta["analise_vertical_pct"] = _arredondar(av, casas_percentuais)

            contas_saida.append(conta)

        # Atualiza após calcular todas as contas para impedir comparação intra-período.
        for registro in contas_periodo:
            anteriores[_chave_conta(registro)] = _valor(registro)

        item_periodo: dict[str, Any] = {"periodo": periodo, "contas": contas_saida}
        inicios = {str(r.get("__inicio")) for r in contas_periodo if r.get("__inicio") is not None}
        if len(inicios) == 1:
            item_periodo["inicio_periodo"] = next(iter(inicios))
        periodos_saida.append(item_periodo)

    return {
        "tipo": "balanco_patrimonial" if tipo == "bp" else "dre",
        "periodos": periodos_saida,
    }


def analisar_dados(bp: Any, dre: Any, *, casas_percentuais: int = 4) -> dict[str, Any]:
    """Retorna o objeto final com as duas demonstrações analisadas."""
    return {
        "balanco_patrimonial": analisar_demonstracao(
            bp, "bp", casas_percentuais=casas_percentuais
        ),
        "dre": analisar_demonstracao(dre, "dre", casas_percentuais=casas_percentuais),
        "metodologia": {
            "analise_vertical_bp": "valor_conta / total_do_lado_do_balanco * 100",
            "analise_horizontal": "(valor_atual / valor_periodo_anterior - 1) * 100",
            "base_zero_ou_ausente": None,
        },
    }


def _ler_json(caminho: str | Path) -> Any:
    with Path(caminho).open("r", encoding="utf-8-sig") as arquivo:
        return json.load(arquivo)


def _salvar_json(dados: Any, caminho: str | Path) -> None:
    # A pasta não é criada deliberadamente: o integrador controla o destino.
    with Path(caminho).open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2, allow_nan=False)
        arquivo.write("\n")


def analisar_arquivos(
    caminho_bp: str | Path,
    caminho_dre: str | Path,
    caminho_saida: str | Path,
    *,
    casas_percentuais: int = 4,
) -> dict[str, Any]:
    """Lê BP/DRE, calcula as análises, grava JSON e também retorna o resultado."""
    resultado = analisar_dados(
        _ler_json(caminho_bp),
        _ler_json(caminho_dre),
        casas_percentuais=casas_percentuais,
    )
    _salvar_json(resultado, caminho_saida)
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description="Análise vertical/horizontal de BP e DRE em JSON.")
    parser.add_argument("bp", help="Caminho do JSON do balanço patrimonial")
    parser.add_argument("dre", help="Caminho do JSON da DRE")
    parser.add_argument("saida", help="Caminho do JSON de saída (a pasta deve existir)")
    parser.add_argument(
        "--casas-percentuais",
        type=int,
        default=4,
        help="Casas decimais dos percentuais (padrão: 4)",
    )
    args = parser.parse_args()
    analisar_arquivos(args.bp, args.dre, args.saida, casas_percentuais=args.casas_percentuais)


if __name__ == "__main__":
    main()

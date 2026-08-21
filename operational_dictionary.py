"""Dicionario central de metricas operacionais do Acompanhador de Mercado.

As regras aqui classificam rotulos, escopos, proxies e falsos positivos.
Elas nao alteram demonstrativos financeiros nem substituem dados CVM.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TARGET_METRICS: tuple[str, ...] = (
    "Ticket Médio",
    "N. Atendimentos",
    "N. Unidades",
    "N. Pacientes",
    "Receita Bruta",
    "Glosa/PCLD",
)

CONFIDENCE_HIGH = 85
CONFIDENCE_MEDIUM = 70

GENERIC_OPERATIONAL_DICTIONARY: dict[str, dict[str, Any]] = {
    "Ticket Médio": {
        "aliases": ("ticket medio", "average ticket", "receita bruta por exame", "ticket por paciente-dia"),
        "expected_units": ("R$", "R$ por atendimento", "R$ por exame", "R$ por paciente-dia"),
        "forbidden_contexts": ("variação", "variacao", "yoy", "qoq", "%"),
    },
    "N. Atendimentos": {
        "aliases": ("atendimentos", "numero de atendimentos", "volume de atendimentos", "consultas"),
        "expected_units": ("atendimentos", "mil atendimentos"),
    },
    "N. Unidades": {
        "aliases": ("unidades", "unidades de atendimento", "unidades operacionais", "unidades proprias"),
        "expected_units": ("unidades",),
        "forbidden_contexts": ("aluguel", "locacao", "r$", "cidade", "municipio", "equipamentos", "salas"),
    },
    "N. Pacientes": {
        "aliases": ("pacientes", "numero de pacientes", "pacientes oncol", "pacientes unicos"),
        "expected_units": ("pacientes",),
        "forbidden_contexts": ("pacientes-dia", "paciente-dia"),
    },
    "Receita Bruta": {
        "aliases": ("receita bruta", "gross revenue"),
        "expected_units": ("R$ milhões", "R$ milhares", "R$"),
        "forbidden_contexts": ("receita liquida", "net revenue"),
    },
    "Glosa/PCLD": {
        "aliases": ("glosas", "pcld", "perdas estimadas", "creditos de liquidacao duvidosa", "glosa"),
        "expected_units": ("R$ milhões", "R$ milhares", "R$"),
    },
}

COMPANY_OPERATIONAL_DICTIONARY: dict[str, dict[str, dict[str, Any]]] = {
    "AALR3": {
        "N. Unidades": {"preferred_labels": ("unidades",), "allowed_breakdowns": ("mega", "padrao", "postos", "b2b")},
        "Glosa/PCLD": {"allowed_proxies": ("perdas", "glosas", "contas a receber", "365 dias")},
    },
    "DASA3": {
        "Ticket Médio": {"preferred_labels": ("receita bruta por exame", "ticket por paciente-dia")},
    },
    "FLRY3": {
        "Ticket Médio": {"preferred_labels": ("receita bruta por exame",)},
        "N. Atendimentos": {"preferred_labels": ("atendimentos",)},
        "Glosa/PCLD": {"preferred_labels": ("glosas e abatimentos",)},
    },
    "HAPV3": {
        "N. Unidades": {"preferred_labels": ("rede propria", "hospitais", "pronto atendimento", "clinicas")},
        "Glosa/PCLD": {"forbidden_contexts": ("reversao", "reversão")},
    },
    "MATD3": {
        "N. Pacientes": {"allowed_proxies": ("pacientes-dia",), "preferred_labels": ("pacientes oncologicos",)},
        "Glosa/PCLD": {"preferred_labels": ("glosas",)},
    },
    "ONCO3": {
        "N. Atendimentos": {"allowed_proxies": ("procedimentos", "tratamentos")},
        "N. Pacientes": {"allowed_proxies": ("procedimentos", "tratamentos")},
    },
    "RDOR3": {
        "Receita Bruta": {
            "preferred_labels": ("hospitais, oncologia e outros",),
            "forbidden_contexts": ("sulamerica", "sul america", "seguros e previdencia", "consolidado"),
        },
        "Glosa/PCLD": {"forbidden_contexts": ("sulamerica", "sul america", "seguros e previdencia")},
        "N. Unidades": {"allowed_proxies": ("hospitais",)},
    },
}


def all_metric_names() -> tuple[str, ...]:
    return TARGET_METRICS


def metric_definition(ticker: str, metric: str) -> dict[str, Any]:
    definition = deepcopy(GENERIC_OPERATIONAL_DICTIONARY.get(metric, {}))
    company = COMPANY_OPERATIONAL_DICTIONARY.get(ticker.upper(), {}).get(metric, {})
    for key, value in company.items():
        if key in {"aliases", "preferred_labels", "allowed_proxies", "allowed_scopes", "forbidden_contexts"}:
            definition[key] = tuple(definition.get(key, ())) + tuple(value)
        else:
            definition[key] = value
    return definition


def metric_aliases(ticker: str, metric: str) -> tuple[str, ...]:
    definition = metric_definition(ticker, metric)
    aliases = tuple(definition.get("aliases", ())) + tuple(definition.get("preferred_labels", ()))
    seen: list[str] = []
    for alias in aliases:
        if alias not in seen:
            seen.append(alias)
    return tuple(seen)

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
    "N. Médicos Relevantes",
    "Concentração Clientes",
    "N. Pacientes",
    "Vidas/Beneficiários",
    "Exames",
    "Procedimentos",
    "Leitos",
    "Hospitais/Clínicas",
    "Ocupação",
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
    "N. Médicos Relevantes": {
        "aliases": ("medicos", "medicos parceiros", "corpo clinico", "profissionais medicos"),
        "expected_units": ("médicos", "medicos"),
        "forbidden_contexts": ("medicos s.a", "médicos s.a", "razao social", "razão social"),
    },
    "Concentração Clientes": {
        "aliases": ("concentracao de clientes", "maiores clientes", "top clientes", "cliente relevante"),
        "expected_units": ("%",),
    },
    "N. Pacientes": {
        "aliases": ("pacientes", "numero de pacientes", "pacientes oncol", "pacientes unicos"),
        "expected_units": ("pacientes",),
        "forbidden_contexts": ("pacientes-dia", "paciente-dia"),
    },
    "Vidas/Beneficiários": {
        "aliases": ("vidas", "beneficiarios", "beneficiários", "vidas saude", "vidas odonto"),
        "expected_units": ("vidas", "beneficiários", "beneficiarios"),
    },
    "Exames": {
        "aliases": ("exames", "volume de exames", "exames realizados"),
        "expected_units": ("exames",),
    },
    "Procedimentos": {
        "aliases": ("procedimentos", "cirurgias", "avisos cirurgicos", "tratamentos", "infusoes"),
        "expected_units": ("procedimentos", "cirurgias", "tratamentos"),
    },
    "Leitos": {
        "aliases": ("leitos", "leitos operacionais", "leitos totais"),
        "expected_units": ("leitos",),
    },
    "Hospitais/Clínicas": {
        "aliases": ("hospitais", "clinicas", "clínicas", "hospitais e clinicas", "unidades hospitalares"),
        "expected_units": ("hospitais", "clínicas", "clinicas", "unidades"),
    },
    "Ocupação": {
        "aliases": ("ocupacao", "ocupação", "taxa de ocupacao", "occupancy rate"),
        "expected_units": ("%",),
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
        "N. Médicos Relevantes": {"preferred_labels": ("medicos parceiros",)},
        "Glosa/PCLD": {"allowed_proxies": ("perdas", "glosas", "contas a receber", "365 dias")},
    },
    "DASA3": {
        "Exames": {"allowed_scopes": ("Diagnósticos Nacional",)},
        "Ticket Médio": {"preferred_labels": ("receita bruta por exame", "ticket por paciente-dia")},
        "Leitos": {"allowed_scopes": ("Hospitais/Onco NE", "Américas", "Hospital da Bahia", "Clínicas AMO")},
        "Ocupação": {"allowed_scopes": ("Hospitais/Onco NE", "Américas", "Hospital da Bahia", "Clínicas AMO")},
    },
    "FLRY3": {
        "Ticket Médio": {"preferred_labels": ("receita bruta por exame",)},
        "Exames": {"preferred_labels": ("exames",)},
        "N. Atendimentos": {"preferred_labels": ("atendimentos",)},
        "Glosa/PCLD": {"preferred_labels": ("glosas e abatimentos",)},
    },
    "HAPV3": {
        "Vidas/Beneficiários": {"preferred_labels": ("vidas saude", "vidas odonto", "beneficiarios")},
        "N. Unidades": {"preferred_labels": ("rede propria", "hospitais", "pronto atendimento", "clinicas")},
        "Glosa/PCLD": {"forbidden_contexts": ("reversao", "reversão")},
    },
    "MATD3": {
        "Leitos": {"preferred_labels": ("leitos operacionais",)},
        "N. Pacientes": {"allowed_proxies": ("pacientes-dia",), "preferred_labels": ("pacientes oncologicos",)},
        "Procedimentos": {"preferred_labels": ("avisos cirurgicos",)},
        "Glosa/PCLD": {"preferred_labels": ("glosas",)},
    },
    "ONCO3": {
        "Procedimentos": {"preferred_labels": ("procedimentos", "tratamentos")},
        "N. Atendimentos": {"allowed_proxies": ("procedimentos", "tratamentos")},
        "N. Pacientes": {"allowed_proxies": ("procedimentos", "tratamentos")},
        "Hospitais/Clínicas": {"allowed_proxies": ("unidades", "clinicas", "clínicas")},
    },
    "RDOR3": {
        "Receita Bruta": {
            "preferred_labels": ("hospitais, oncologia e outros",),
            "forbidden_contexts": ("sulamerica", "sul america", "seguros e previdencia", "consolidado"),
        },
        "Glosa/PCLD": {"forbidden_contexts": ("sulamerica", "sul america", "seguros e previdencia")},
        "Vidas/Beneficiários": {"allowed_scopes": ("SulAmérica", "Sul America")},
        "N. Unidades": {"allowed_proxies": ("hospitais",)},
        "Hospitais/Clínicas": {"allowed_proxies": ("hospitais",)},
        "Procedimentos": {"allowed_proxies": ("cirurgias", "infusoes")},
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


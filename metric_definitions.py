"""Definicoes metodologicas centrais do Acompanhador de Mercado.

Este modulo concentra regras de comparabilidade para evitar excecoes
espalhadas pelos aplicativos. Dados CVM continuam sendo a camada oficial; as
configuracoes abaixo afetam apenas indicadores derivados e rotulos
metodologicos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from company_registry import financial_companies


METHODOLOGY_VERSION = "2.0"

QualityStatus = Literal[
    "validated",
    "methodology_difference",
    "estimated",
    "incomplete",
    "not_comparable",
    "requires_review",
    "error",
]


@dataclass(frozen=True)
class RevenueRule:
    accounting_code: str = "3.01"
    operating_metric: str | None = None
    denominator_label: str = "Receita contabil CVM 3.01"
    ifrs17: bool = False


@dataclass(frozen=True)
class NetDebtRule:
    cash_codes: tuple[str, ...] = ("1.01.01",)
    financial_investment_codes: tuple[str, ...] = ("1.01.02",)
    short_term_debt_codes: tuple[str, ...] = ("2.01.04",)
    long_term_debt_codes: tuple[str, ...] = ("2.02.01",)
    deduct_financial_investments: bool = True
    include_leases: bool = False
    description: str = (
        "Divida financeira bruta menos caixa e equivalentes e aplicacoes "
        "financeiras identificadas como dedutiveis pela configuracao padrao."
    )


@dataclass(frozen=True)
class CompanyMetricRule:
    ticker: str
    financial_scope: str = "consolidado"
    revenue: RevenueRule = field(default_factory=RevenueRule)
    net_debt: NetDebtRule = field(default_factory=NetDebtRule)


DEFAULT_NET_DEBT_RULE = NetDebtRule()

COMPANY_METRIC_RULES: dict[str, CompanyMetricRule] = {
    ticker: CompanyMetricRule(ticker=ticker)
    for ticker in (company.ticker for company in financial_companies("all") if company.ticker not in {"RDOR3", "HAPV3"})
}

COMPANY_METRIC_RULES["RDOR3"] = CompanyMetricRule(
    ticker="RDOR3",
    financial_scope="individual",
)

COMPANY_METRIC_RULES["HAPV3"] = CompanyMetricRule(
    ticker="HAPV3",
    revenue=RevenueRule(
        accounting_code="3.01",
        operating_metric="Receita Bruta",
        denominator_label=(
            "Receita operacional/gerencial divulgada pela companhia quando "
            "disponivel; caso ausente, margens gerenciais ficam incompletas"
        ),
        ifrs17=True,
    ),
)


EBITDA_CONTABIL_FORMULA = "EBIT CVM 3.05 + Depreciacao e amortizacao da DFC"
EBITDA_AJUSTADO_SOURCE_RULE = (
    "Somente valor explicitamente divulgado em release, apresentacao, "
    "planilha de fundamentos ou outra fonte oficial de RI."
)
EBITDA_LTM_FORMULA = "Soma dos quatro ultimos trimestres individuais comparaveis"
EV_FORMULA = "Market Cap historico + Divida liquida padronizada"
EV_EBITDA_LTM_FORMULA = "(Market Cap + Divida liquida padronizada) / EBITDA contabil LTM"


MATERIALITY_THRESHOLDS = {
    "match_pct": 1.0,
    "review_pct": 5.0,
}


# Contrato operacional de Varejo. Os aliases identificam apenas divulgações
# explícitas; GMV, sell-out e vendas de terceiros são mantidos fora das
# receitas de canal para evitar equivalências silenciosas.
RETAIL_OPERATIONAL_DICTIONARY: dict[str, dict[str, object]] = {
    "stores_count": {
        "display_name": "Número de lojas",
        "definition": "Quantidade de lojas no fechamento do período, sem somar aberturas que possam se sobrepor ao estoque final.",
        "unit": "lojas",
        "nature": "stock",
        "aliases": ("numero de lojas", "número de lojas", "total de lojas", "lojas totais", "store count", "number of stores"),
        "forbidden_contexts": ("aberturas", "openings", "lojas abertas", "fechamentos", "closures"),
    },
    "sales_area_sqm": {
        "display_name": "Área total de vendas",
        "definition": "Área comercial divulgada no fechamento ou média do período, normalizada para m².",
        "unit": "m²",
        "nature": "stock",
        "aliases": ("area total de vendas", "área total de vendas", "area de vendas", "área de vendas", "selling area", "sales area"),
        "forbidden_contexts": ("area media por loja", "área média por loja", "average area per store"),
    },
    "physical_revenue_brl": {
        "display_name": "Receita física",
        "definition": "Receita explicitamente atribuída ao canal de lojas físicas, no escopo divulgado.",
        "unit": "R$",
        "nature": "flow",
        "aliases": ("receita fisica", "receita física", "receita lojas fisicas", "receita lojas físicas", "receita canal fisico", "physical store revenue", "brick and mortar revenue"),
        "forbidden_contexts": ("gmv", "sell-out", "sell out", "vendas em lojas", "same store sales", "sss"),
    },
    "digital_revenue_brl": {
        "display_name": "Receita digital",
        "definition": "Receita explicitamente atribuída ao canal digital; GMV e sell-out não são tratados como receita.",
        "unit": "R$",
        "nature": "flow",
        "aliases": ("receita digital", "receita e-commerce", "receita ecommerce", "receita online", "digital revenue", "e-commerce revenue", "online revenue"),
        "forbidden_contexts": ("gmv", "sell-out", "sell out", "vendas digitais", "participacao digital", "participação digital"),
    },
    "comparable_total_revenue_brl": {
        "display_name": "Receita total comparável",
        "definition": "Base de receita explicitamente compatível com as receitas física e digital.",
        "unit": "R$",
        "nature": "flow",
        "aliases": ("receita total dos canais", "receita total varejo", "receita total comparavel", "receita total comparável", "total channel revenue", "retail revenue"),
        "forbidden_contexts": ("gmv", "sell-out", "servicos financeiros", "serviços financeiros", "atacado", "wholesale", "intercompany"),
        "dependency_only": True,
    },
    "digital_revenue_share": {
        "display_name": "Receita digital / receita total",
        "definition": "Receita digital dividida pela receita total comparável, somente com escopo e período reconciliados.",
        "unit": "%",
        "nature": "ratio",
        "derived": True,
    },
    "physical_revenue_per_sqm": {
        "display_name": "Receita física / área total de vendas",
        "definition": "Receita física do período dividida pela área média; na ausência desta, usa área de fechamento com sinalização explícita.",
        "unit": "R$/m²",
        "nature": "ratio",
        "derived": True,
    },
}

RETAIL_METRIC_IDS = tuple(RETAIL_OPERATIONAL_DICTIONARY)


def company_rule(ticker: str) -> CompanyMetricRule:
    return COMPANY_METRIC_RULES.get(ticker.upper(), CompanyMetricRule(ticker=ticker.upper()))


def net_debt_options(ticker: str) -> dict[str, object]:
    rule = company_rule(ticker).net_debt
    return {
        "codes": {
            "cash": list(rule.cash_codes),
            "financial_investments": list(rule.financial_investment_codes),
            "short_term_debt": list(rule.short_term_debt_codes),
            "long_term_debt": list(rule.long_term_debt_codes),
        },
        "deduct_financial_investments": rule.deduct_financial_investments,
        "include_leases": rule.include_leases,
    }

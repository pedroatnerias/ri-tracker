"""Definicoes metodologicas centrais do Acompanhador de Mercado.

Este modulo concentra regras de comparabilidade para evitar excecoes
espalhadas pelos aplicativos. Dados CVM continuam sendo a camada oficial; as
configuracoes abaixo afetam apenas indicadores derivados e rotulos
metodologicos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


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
    for ticker in ("AALR3", "DASA3", "FLRY3", "MATD3", "ONCO3")
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

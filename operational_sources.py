"""Cadastro canônico e estritamente setorial das fontes operacionais de RI."""

from __future__ import annotations

from typing import Any

from company_registry import companies_for_sector, validate_sector

ACCEPTED_DOCUMENT_TYPES = (
    "PREVIA_OPERACIONAL", "RELEASE_RESULTADOS", "APRESENTACAO_RESULTADOS",
    "PLANILHA_RESULTADOS", "DEMONSTRACOES_FINANCEIRAS", "TRANSCRICAO_WEBCAST",
)

_HEALTH_URLS = {
    "RDOR3": "https://ri.rededorsaoluiz.com.br/informacoes-financeiras/central-de-resultados/",
    "MATD3": "https://ri.materdei.com.br/informacoes-aos-acionistas/central-de-resultados/",
    "FLRY3": "https://ri.fleury.com.br/informacoes-financeiras-e-apresentacoes/central-de-resultados/",
    "AALR3": "https://ri.allianca.com/informacoes-financeiras/central-de-resultados/",
    "DASA3": "https://www.dasa3.com.br/informacoes-financeiras/resultado-trimestral/",
    "ONCO3": "https://ri.grupooncoclinicas.com/informacoes-financeiras/central-de-resultados/",
    "HAPV3": "https://ri.hapvida.com.br/informacoes-financeiras/central-de-resultados/",
}

# URLs ficam centralizadas aqui; falhas de descoberta são explícitas e jamais usam outro setor.
_CONSTRUCTION_URLS = {
    "AVLL3": "https://ri.alphaville.com.br/", "CALI3": "https://ri.cal.com.br/",
    "CURY3": "https://ri.cury.net/", "CYRE3": "https://ri.cyrela.com.br/",
    "DIRR3": "https://ri.direcional.com.br/", "EVEN3": "https://ri.even.com.br/",
    "EZTC3": "https://ri.eztec.com.br/", "FIEI3": "https://ri.ficaempreendimentos.com.br/",
    "GFSA3": "https://ri.gafisa.com.br/", "HBOR3": "https://ri.helbor.com.br/",
    "INNC3": "https://ri.incorporadorainc.com.br/", "JFEN3": "https://ri.joaofortes.com.br/",
    "JHSF3": "https://ri.jhsf.com.br/", "LAVV3": "https://ri.lavvi.com.br/",
    "MDNE3": "https://ri.mouradubeux.com.br/", "MELK3": "https://ri.melnick.com.br/",
    "MRVE3": "https://ri.mrv.com.br/", "MTRE3": "https://ri.mitrerealty.com.br/",
    "PDGR3": "https://ri.pdg.com.br/", "PLPL3": "https://ri.planoeplano.com.br/",
    "RDNI3": "https://ri.rni.com.br/", "RSID3": "https://ri.rossiresidencial.com.br/",
    "TCSA3": "https://ri.tecnisa.com.br/", "TEND3": "https://ri.tenda.com/",
    "TRIS3": "https://ri.trisul-sa.com.br/", "VIVR3": "https://ri.viver.com.br/",
}


def _build_sector_sources(sector: str, urls: dict[str, str]) -> dict[str, dict[str, Any]]:
    companies = {company.ticker: company for company in companies_for_sector(sector) if company.operational_enabled}
    return {
        ticker: {
            "ticker": ticker, "legacy_tickers": list(company.legacy_tickers),
            "empresa": company.expected_name, "aliases": list(company.aliases),
            "url": urls[ticker], "official_domain": urls[ticker].split("/", 3)[2],
            "discovery_method": "official_results_page",
            "accepted_document_types": list(ACCEPTED_DOCUMENT_TYPES),
        }
        for ticker, company in companies.items() if ticker in urls
    }


OPERATIONAL_RI_SOURCES = {
    "saude": _build_sector_sources("saude", _HEALTH_URLS),
    "construcao_civil": _build_sector_sources("construcao_civil", _CONSTRUCTION_URLS),
}


def operational_sources_for_sector(sector: str) -> dict[str, dict[str, Any]]:
    sector = validate_sector(sector)
    sources = OPERATIONAL_RI_SOURCES.get(sector)
    if not sources:
        raise ValueError(f"Nenhuma configuração de RI encontrada para o setor {sector}.")
    return sources

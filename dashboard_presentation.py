"""Contratos puros da camada de apresentação do dashboard.

Este módulo não importa Flask nem fontes de dados. Ele transforma manifestos e
metadados já carregados em estruturas consumíveis pela apresentação.
"""

from __future__ import annotations


COMPARISON_METRICS = (
    ("cagr_receita", "CAGR Receita", "percent"),
    ("cagr_lucros", "CAGR Lucros", "percent"),
    ("ciclo_financeiro", "Ciclo Financeiro", "days"),
    ("margem_bruta", "Margem Bruta", "percent"),
    ("margem_operacional", "Margem Operacional", "percent"),
    ("margem_ebitda", "Margem EBITDA", "percent"),
    ("margem_liquida", "Margem Líquida", "percent"),
    ("ev_ebitda", "EV/EBITDA", "multiple"),
    ("delta_preco_30d", "Delta Preço da Ação 30 dias", "signed_percent"),
    ("delta_preco_90d", "Delta Preço da Ação 90 dias", "signed_percent"),
    ("delta_preco_360d", "Delta Preço da Ação 360 dias", "signed_percent"),
    ("n_unidades", "N. Unidades", "integer"),
)


def build_chart_assets_payload(manifest: dict, version: str, *, sector: str, manifest_v2: bool, url_for_path) -> dict:
    """Converte um manifesto em payload de assets sem depender do Flask."""
    def with_url(path: str) -> dict:
        asset_path = f"charts/{sector}/{path.removeprefix('charts/')}" if manifest_v2 and path.startswith("charts/") else path
        url = url_for_path(asset_path)
        return {"path": path, "url": f"{url}?v={version}" if url and version else url}

    individual = {
        ticker: {key: with_url(path) for key, path in charts.items() if isinstance(path, str)}
        for ticker, charts in (manifest.get("individual") or {}).items()
        if isinstance(charts, dict)
    }
    comparison = {
        key: with_url(path)
        for key, path in (manifest.get("comparison") or {}).items()
        if isinstance(path, str)
    }
    return {"version": version, "individual": individual, "comparison": comparison}

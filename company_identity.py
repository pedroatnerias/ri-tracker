"""Selecao auditavel de companhias nos arquivos estruturados da CVM."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from company_registry import Company


class CompanyNotFoundError(RuntimeError):
    """Identidade esperada ausente no demonstrativo consultado."""


def normalize_cd_cvm(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )


def normalize_cnpj(series: pd.Series) -> pd.Series:
    return series.astype("string").str.replace(r"\D", "", regex=True).str.zfill(14)


def normalized_name(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def statement_scope_label(company: Company) -> str:
    return "consolidada" if company.statement_scope == "con" else "individual"


def select_company_rows(base: pd.DataFrame, company: Company, statement: str) -> pd.DataFrame:
    required = {"CD_CVM", "CNPJ_CIA"}
    missing = required - set(base.columns)
    if missing:
        raise RuntimeError(f"{statement}: colunas de identidade ausentes: {sorted(missing)}")

    work = base.copy()
    work["CD_CVM_NORMALIZADO"] = normalize_cd_cvm(work["CD_CVM"])
    work["CNPJ_NORMALIZADO"] = normalize_cnpj(work["CNPJ_CIA"])
    expected_code = str(company.cd_cvm).zfill(6)
    expected_cnpj = re.sub(r"\D", "", company.cnpj).zfill(14)
    by_code = work["CD_CVM_NORMALIZADO"].eq(expected_code)
    by_cnpj = work["CNPJ_NORMALIZADO"].eq(expected_cnpj)

    code_rows = work.loc[by_code]
    cnpj_rows = work.loc[by_cnpj]
    if not code_rows.empty and not cnpj_rows.empty:
        code_cnpjs = set(code_rows["CNPJ_NORMALIZADO"].dropna())
        cnpj_codes = set(cnpj_rows["CD_CVM_NORMALIZADO"].dropna())
        if (code_cnpjs - {expected_cnpj}) or (cnpj_codes - {expected_code}):
            raise RuntimeError(
                f"{company.ticker}: conflito de identidade na {statement}. "
                f"CD_CVM {expected_code} aponta para CNPJ(s) {sorted(code_cnpjs)}; "
                f"CNPJ {company.cnpj} aponta para CD_CVM(s) {sorted(cnpj_codes)}."
            )

    selected = work.loc[by_code | by_cnpj].copy()
    if selected.empty:
        aliases = [company.expected_name, *company.aliases]
        nearby: list[dict[str, object]] = []
        if "DENOM_CIA" in work.columns:
            target_tokens = {token for name in aliases for token in normalized_name(name).split() if len(token) >= 5}
            candidates = work[["CD_CVM", "CNPJ_CIA", "DENOM_CIA"]].drop_duplicates()
            candidates = candidates[candidates["DENOM_CIA"].map(lambda value: bool(target_tokens & set(normalized_name(value).split())))]
            nearby = candidates.head(10).to_dict("records")
        raise CompanyNotFoundError(
            f"{company.ticker} não localizada na {statement} {statement_scope_label(company)}. "
            f"CD_CVM esperado: {expected_code}; CNPJ esperado: {company.cnpj}; "
            f"setor: {company.sector}; escopo contábil: {company.statement_scope}; "
            f"aliases: {aliases}; exemplos próximos: {nearby}"
        )

    identities = selected[["CD_CVM_NORMALIZADO", "CNPJ_NORMALIZADO"]].drop_duplicates()
    if len(identities) > 1:
        raise RuntimeError(
            f"{company.ticker}: múltiplas identidades misturadas na {statement}: "
            f"{identities.to_dict('records')}"
        )
    selected["IDENTITY_MATCH"] = "cd_cvm" if bool(by_code.any()) else "cnpj_fallback"
    return selected

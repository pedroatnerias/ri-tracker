"""Cadastro central, imutavel e tipado das companhias do RI Tracker."""

from __future__ import annotations

from dataclasses import dataclass


SECTORS = frozenset({"saude", "construcao_civil", "all"})
SECTOR_LABELS = {"saude": "Saúde", "construcao_civil": "Construção civil", "all": "Todos"}


@dataclass(frozen=True, slots=True)
class Company:
    ticker: str
    sector: str
    cd_cvm: str
    cnpj: str
    expected_name: str
    aliases: tuple[str, ...]
    statement_scope: str
    financial_enabled: bool = True
    operational_enabled: bool = False
    yahoo_ticker: str | None = None
    configuration_status: str = "validated"
    configuration_note: str | None = None

    @property
    def scope_label(self) -> str:
        return "Consolidado" if self.statement_scope == "con" else "Individual"


def _c(ticker: str, sector: str, cd: str, cnpj: str, name: str, aliases: tuple[str, ...] = (),
       scope: str = "con", operational: bool = False, yahoo: str | None = None,
       status: str = "validated", note: str | None = None) -> Company:
    return Company(ticker, sector, cd.zfill(6), cnpj, name, aliases or (name,), scope, True,
                   operational, yahoo if yahoo is not None else f"{ticker}.SA", status, note)


_COMPANIES = (
    _c("AALR3", "saude", "24023", "42.771.949/0001-35", "CENTRO DE IMAGEM DIAGNOSTICOS S.A.", ("CENTRO DE IMAGEM DIAGNOSTICOS S.A.", "ALLIANCA SAUDE E PARTICIPACOES S.A.", "ALLIAR"), operational=True),
    _c("DASA3", "saude", "19623", "61.486.650/0001-83", "DIAGNOSTICOS DA AMERICA S.A.", operational=True),
    _c("FLRY3", "saude", "21881", "60.840.055/0001-31", "FLEURY S.A.", operational=True),
    _c("HAPV3", "saude", "24392", "05.197.443/0001-38", "HAPVIDA PARTICIPACOES E INVESTIMENTOS S.A.", operational=True),
    _c("MATD3", "saude", "25690", "16.676.520/0001-59", "HOSPITAL MATER DEI S.A.", operational=True),
    _c("ONCO3", "saude", "26123", "12.104.241/0004-02", "ONCOCLINICAS DO BRASIL SERVICOS MEDICOS S.A.", operational=True),
    _c("RDOR3", "saude", "24821", "06.047.087/0001-39", "REDE D'OR SAO LUIZ S.A.", ("REDE D'OR SAO LUIZ S.A.", "REDE DOR SAO LUIZ S.A.", "REDE DOR S.A."), scope="ind", operational=True),
    _c("AVLL3", "construcao_civil", "25275", "16.811.931/0001-00", "ALPHAVILLE S.A."),
    _c("CALI3", "construcao_civil", "4723", "61.022.042/0001-18", "CONSTRUTORA ADOLPHO LINDENBERG S.A.", ("CONSTRUTORA ADOLPHO LINDENBERG S.A.", "CAL S/A")),
    _c("CURY3", "construcao_civil", "25100", "08.797.760/0001-83", "CURY CONSTRUTORA E INCORPORADORA S.A."),
    _c("CYRE3", "construcao_civil", "14460", "73.178.600/0001-18", "CYRELA BRAZIL REALTY S.A. EMPREENDIMENTOS E PARTICIPACOES"),
    _c("DIRR3", "construcao_civil", "21350", "16.614.075/0001-00", "DIRECIONAL ENGENHARIA S.A."),
    _c("EVEN3", "construcao_civil", "20524", "43.470.988/0001-65", "EVEN CONSTRUTORA E INCORPORADORA S.A."),
    _c("EZTC3", "construcao_civil", "20770", "08.312.229/0001-73", "EZ TEC EMPREENDIMENTOS E PARTICIPACOES S.A."),
    _c("FIEI3", "construcao_civil", "20630", "07.820.907/0001-46", "FICA EMPREENDIMENTOS IMOBILIARIOS S.A.", ("FICA EMPREENDIMENTOS IMOBILIARIOS S.A.", "CR2 EMPREENDIMENTOS IMOBILIARIOS S.A.")),
    _c("GFSA3", "construcao_civil", "16101", "01.545.826/0001-07", "GAFISA S.A."),
    _c("HBOR3", "construcao_civil", "20877", "49.263.189/0001-02", "HELBOR EMPREENDIMENTOS S.A."),
    _c("INNT3", "construcao_civil", "24279", "09.611.768/0001-76", "INTER CONSTRUTORA E INCORPORADORA S.A.", ("INTER CONSTRUTORA E INCORPORADORA S.A.", "INC EMPREENDIMENTOS IMOBILIARIOS S.A.", "INNC3")),
    _c("JFEN3", "construcao_civil", "7811", "33.035.536/0001-00", "JOAO FORTES ENGENHARIA S.A.", ("JOAO FORTES ENGENHARIA S.A.", "JOAO FORTES ENGENHARIA S.A. - EM RECUPERACAO JUDICIAL")),
    _c("JHSF3", "construcao_civil", "20605", "08.294.224/0001-65", "JHSF PARTICIPACOES S.A."),
    _c("LAVV3", "construcao_civil", "25062", "26.462.693/0001-28", "LAVVI EMPREENDIMENTOS IMOBILIARIOS S.A."),
    _c("MDNE3", "construcao_civil", "21067", "12.049.631/0001-84", "MOURA DUBEUX ENGENHARIA S.A."),
    _c("MELK3", "construcao_civil", "25119", "12.181.987/0001-77", "MELNICK DESENVOLVIMENTO IMOBILIARIO S.A."),
    _c("MRVE3", "construcao_civil", "20915", "08.343.492/0001-20", "MRV ENGENHARIA E PARTICIPACOES S.A."),
    _c("MTRE3", "construcao_civil", "24902", "07.882.930/0001-65", "MITRE REALTY EMPREENDIMENTOS E PARTICIPACOES S.A."),
    _c("PDGR3", "construcao_civil", "20478", "02.950.811/0001-89", "PDG REALTY S.A. EMPREENDIMENTOS E PARTICIPACOES"),
    _c("PLPL3", "construcao_civil", "25070", "24.230.275/0001-80", "PLANO & PLANO DESENVOLVIMENTO IMOBILIARIO S.A."),
    _c("RDNI3", "construcao_civil", "20451", "67.010.660/0001-24", "RNI NEGOCIOS IMOBILIARIOS S.A.", ("RNI NEGOCIOS IMOBILIARIOS S.A.", "RODOBENS NEGOCIOS IMOBILIARIOS S.A.")),
    _c("RSID3", "construcao_civil", "16306", "61.065.751/0001-80", "ROSSI RESIDENCIAL S.A.", ("ROSSI RESIDENCIAL S.A.", "ROSSI RESIDENCIAL S.A. - EM RECUPERACAO JUDICIAL")),
    _c("TCSA3", "construcao_civil", "20435", "08.065.557/0001-12", "TECNISA S.A."),
    _c("TEND3", "construcao_civil", "21148", "71.476.527/0001-35", "CONSTRUTORA TENDA S.A."),
    _c("TRIS3", "construcao_civil", "21130", "08.811.643/0001-27", "TRISUL S.A."),
    _c("VIVR3", "construcao_civil", "20702", "67.571.414/0001-41", "VIVER INCORPORADORA E CONSTRUTORA S.A."),
)

_BY_TICKER = {company.ticker: company for company in _COMPANIES}
if len(_BY_TICKER) != len(_COMPANIES):
    raise RuntimeError("Ticker duplicado no cadastro central")


def validate_sector(sector: str) -> str:
    normalized = (sector or "saude").strip().lower()
    if normalized not in SECTORS:
        raise ValueError(f"Setor invalido: {sector}")
    return normalized


def all_companies() -> tuple[Company, ...]:
    return _COMPANIES


def companies_for_sector(sector: str) -> tuple[Company, ...]:
    sector = validate_sector(sector)
    return _COMPANIES if sector == "all" else tuple(c for c in _COMPANIES if c.sector == sector)


def financial_companies(sector: str = "saude") -> tuple[Company, ...]:
    return tuple(c for c in companies_for_sector(sector) if c.financial_enabled)


def operational_companies(sector: str = "saude") -> tuple[Company, ...]:
    return tuple(c for c in companies_for_sector(sector) if c.operational_enabled)


def tickers_for_sector(sector: str = "saude") -> tuple[str, ...]:
    return tuple(c.ticker for c in companies_for_sector(sector))


def company_by_ticker(ticker: str) -> Company:
    try:
        return _BY_TICKER[ticker.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"Ticker desconhecido: {ticker}") from exc

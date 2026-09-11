"""Cadastro central, imutavel e tipado das companhias do RI Tracker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectorConfig:
    label: str
    financial_enabled: bool
    operational_enabled: bool


@dataclass(frozen=True, slots=True)
class ShareClass:
    ticker: str
    cvm_quantity_field: str
    cvm_quantity_scale: int = 1
    economic_weight: float = 1.0
    class_label: str | None = None

    @property
    def yahoo_ticker(self) -> str:
        return self.ticker if self.ticker.endswith(".SA") else f"{self.ticker}.SA"


@dataclass(frozen=True, slots=True)
class StatementScaleOverride:
    document: str
    start_date: str
    end_date: str
    declared_scale: str
    multiplier: int
    reason: str


SECTOR_CONFIG = {
    "saude": SectorConfig("Saúde", True, True),
    "construcao_civil": SectorConfig("Construção civil", True, True),
    "varejo": SectorConfig("Varejo", True, False),
}
REAL_SECTORS = tuple(SECTOR_CONFIG)
SECTORS = frozenset((*REAL_SECTORS, "all"))
SECTOR_LABELS = {**{sector: config.label for sector, config in SECTOR_CONFIG.items()}, "all": "Todos"}


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
    legacy_tickers: tuple[str, ...] = ()
    share_classes: tuple[ShareClass, ...] = ()
    statement_scale_overrides: tuple[StatementScaleOverride, ...] = ()

    @property
    def scope_label(self) -> str:
        return "Consolidado" if self.statement_scope == "con" else "Individual"

    @property
    def yahoo_tickers(self) -> tuple[str, ...]:
        tickers = tuple(
            ticker if ticker.endswith(".SA") else f"{ticker}.SA"
            for ticker in (self.ticker, *self.legacy_tickers)
        )
        configured = () if self.yahoo_ticker is None else (self.yahoo_ticker,)
        return tuple(dict.fromkeys((*configured, *tickers)))


def _c(ticker: str, sector: str, cd: str, cnpj: str, name: str, aliases: tuple[str, ...] = (),
       scope: str = "con", operational: bool | None = None, yahoo: str | None = None,
       status: str = "validated", note: str | None = None,
       legacy_tickers: tuple[str, ...] = (), share_classes: tuple[ShareClass, ...] = (),
       statement_scale_overrides: tuple[StatementScaleOverride, ...] = ()) -> Company:
    operational_enabled = SECTOR_CONFIG[sector].operational_enabled if operational is None else operational
    return Company(ticker, sector, cd.zfill(6), cnpj, name, aliases or (name,), scope, True,
                   operational_enabled, yahoo if yahoo is not None else f"{ticker}.SA", status, note, legacy_tickers,
                   share_classes, statement_scale_overrides)


_COMPANIES = (
    _c("AALR3", "saude", "24023", "42.771.949/0001-35", "CENTRO DE IMAGEM DIAGNOSTICOS S.A.", ("CENTRO DE IMAGEM DIAGNOSTICOS S.A.", "ALLIANCA SAUDE E PARTICIPACOES S.A.", "ALLIAR"), operational=True),
    _c("DASA3", "saude", "19623", "61.486.650/0001-83", "DIAGNOSTICOS DA AMERICA S.A.", operational=True),
    _c("FLRY3", "saude", "21881", "60.840.055/0001-31", "FLEURY S.A.", operational=True),
    _c("HAPV3", "saude", "24392", "05.197.443/0001-38", "HAPVIDA PARTICIPACOES E INVESTIMENTOS S.A.", operational=True),
    _c("MATD3", "saude", "25690", "16.676.520/0001-59", "HOSPITAL MATER DEI S.A.", operational=True),
    _c("ONCO3", "saude", "26123", "12.104.241/0004-02", "ONCOCLINICAS DO BRASIL SERVICOS MEDICOS S.A.", operational=True),
    _c("RDOR3", "saude", "24821", "06.047.087/0001-39", "REDE D'OR SAO LUIZ S.A.", ("REDE D'OR SAO LUIZ S.A.", "REDE DOR SAO LUIZ S.A.", "REDE DOR S.A."), scope="ind", operational=True),
    _c("AVLL3", "construcao_civil", "25275", "16.811.931/0001-00", "ALPHAVILLE S.A.", operational=True),
    _c("CALI3", "construcao_civil", "4723", "61.022.042/0001-18", "CONSTRUTORA ADOLPHO LINDENBERG S.A.", ("CONSTRUTORA ADOLPHO LINDENBERG S.A.", "CAL S/A"), operational=True),
    _c("CURY3", "construcao_civil", "25100", "08.797.760/0001-83", "CURY CONSTRUTORA E INCORPORADORA S.A.", operational=True),
    _c("CYRE3", "construcao_civil", "14460", "73.178.600/0001-18", "CYRELA BRAZIL REALTY S.A. EMPREENDIMENTOS E PARTICIPACOES", operational=True),
    _c("DIRR3", "construcao_civil", "21350", "16.614.075/0001-00", "DIRECIONAL ENGENHARIA S.A.", operational=True),
    _c("EVEN3", "construcao_civil", "20524", "43.470.988/0001-65", "EVEN CONSTRUTORA E INCORPORADORA S.A.", operational=True),
    _c("EZTC3", "construcao_civil", "20770", "08.312.229/0001-73", "EZ TEC EMPREENDIMENTOS E PARTICIPACOES S.A.", operational=True),
    _c("FIEI3", "construcao_civil", "20630", "07.820.907/0001-46", "FICA EMPREENDIMENTOS IMOBILIARIOS S.A.", ("FICA EMPREENDIMENTOS IMOBILIARIOS S.A.", "CR2 EMPREENDIMENTOS IMOBILIARIOS S.A."), operational=True),
    _c("GFSA3", "construcao_civil", "16101", "01.545.826/0001-07", "GAFISA S.A.", operational=True),
    _c("HBOR3", "construcao_civil", "20877", "49.263.189/0001-02", "HELBOR EMPREENDIMENTOS S.A.", operational=True),
    _c("INNC3", "construcao_civil", "24279", "09.611.768/0001-76", "INC EMPREENDIMENTOS IMOBILIARIOS S.A.", ("INTER CONSTRUTORA E INCORPORADORA S.A.", "INC EMPREENDIMENTOS IMOBILIARIOS S.A."), operational=True, legacy_tickers=("INNT3",)),
    _c("JFEN3", "construcao_civil", "7811", "33.035.536/0001-00", "JOAO FORTES ENGENHARIA S.A.", ("JOAO FORTES ENGENHARIA S.A.", "JOAO FORTES ENGENHARIA S.A. - EM RECUPERACAO JUDICIAL"), operational=True),
    _c("JHSF3", "construcao_civil", "20605", "08.294.224/0001-65", "JHSF PARTICIPACOES S.A.", operational=True),
    _c("LAVV3", "construcao_civil", "25062", "26.462.693/0001-28", "LAVVI EMPREENDIMENTOS IMOBILIARIOS S.A.", operational=True),
    _c("MDNE3", "construcao_civil", "21067", "12.049.631/0001-84", "MOURA DUBEUX ENGENHARIA S.A.", operational=True),
    _c("MELK3", "construcao_civil", "25119", "12.181.987/0001-77", "MELNICK DESENVOLVIMENTO IMOBILIARIO S.A.", operational=True),
    _c("MRVE3", "construcao_civil", "20915", "08.343.492/0001-20", "MRV ENGENHARIA E PARTICIPACOES S.A.", operational=True),
    _c("MTRE3", "construcao_civil", "24902", "07.882.930/0001-65", "MITRE REALTY EMPREENDIMENTOS E PARTICIPACOES S.A.", operational=True),
    _c("PDGR3", "construcao_civil", "20478", "02.950.811/0001-89", "PDG REALTY S.A. EMPREENDIMENTOS E PARTICIPACOES", operational=True),
    _c("PLPL3", "construcao_civil", "25070", "24.230.275/0001-80", "PLANO & PLANO DESENVOLVIMENTO IMOBILIARIO S.A.", operational=True),
    _c("RDNI3", "construcao_civil", "20451", "67.010.660/0001-24", "RNI NEGOCIOS IMOBILIARIOS S.A.", ("RNI NEGOCIOS IMOBILIARIOS S.A.", "RODOBENS NEGOCIOS IMOBILIARIOS S.A."), operational=True),
    _c("RSID3", "construcao_civil", "16306", "61.065.751/0001-80", "ROSSI RESIDENCIAL S.A.", ("ROSSI RESIDENCIAL S.A.", "ROSSI RESIDENCIAL S.A. - EM RECUPERACAO JUDICIAL"), operational=True),
    _c("TCSA3", "construcao_civil", "20435", "08.065.557/0001-12", "TECNISA S.A.", operational=True),
    _c("TEND3", "construcao_civil", "21148", "71.476.527/0001-35", "CONSTRUTORA TENDA S.A.", operational=True),
    _c("TRIS3", "construcao_civil", "21130", "08.811.643/0001-27", "TRISUL S.A.", operational=True),
    _c("VIVR3", "construcao_civil", "20702", "67.571.414/0001-41", "VIVER INCORPORADORA E CONSTRUTORA S.A.", operational=True),
    _c("ALLD3", "varejo", "25330", "20.247.322/0001-47", "ALLIED TECNOLOGIA S.A."),
    _c("AMAR3", "varejo", "22055", "61.189.288/0001-89", "MARISA LOJAS S.A."),
    _c("AMER3", "varejo", "20990", "00.776.574/0001-56", "AMERICANAS S.A. - EM RECUPERACAO JUDICIAL", ("AMERICANAS S.A.", "AMERICANAS S.A. - EM RECUPERACAO JUDICIAL")),
    _c("BHIA3", "varejo", "6505", "33.041.260/0652-90", "GRUPO CASAS BAHIA S.A.", ("GRUPO CASAS BAHIA S.A.", "VIA S.A.", "VIA VAREJO S.A.")),
    _c("CEAB3", "varejo", "24848", "45.242.914/0001-05", "C&A MODAS S.A."),
    _c("CGRA3", "varejo", "4537", "92.012.467/0001-70", "GRAZZIOTIN S.A.", share_classes=(ShareClass("CGRA3", "QT_ACAO_ORDIN_CAP_INTEGR"), ShareClass("CGRA4", "QT_ACAO_PREF_CAP_INTEGR"))),
    _c("LJQQ3", "varejo", "25038", "96.418.264/0218-02", "LOJAS QUERO-QUERO S.A."),
    _c("LREN3", "varejo", "8133", "92.754.738/0001-62", "LOJAS RENNER S.A."),
    _c("MGLU3", "varejo", "22470", "47.960.950/0001-21", "MAGAZINE LUIZA S.A."),
    _c("RIAA3", "varejo", "4669", "08.402.943/0001-52", "GUARARAPES CONFECCOES S.A.", ("GUARARAPES CONFECCOES S.A.", "RIACHUELO S.A."), legacy_tickers=("GUAR3",)),
    _c("SBFG3", "varejo", "24694", "13.217.485/0001-11", "GRUPO SBF S.A."),
    _c("TFCO4", "varejo", "25208", "59.418.806/0001-47", "TRACK & FIELD CO S.A.", share_classes=(ShareClass("TFCO4", "QT_ACAO_ORDIN_CAP_INTEGR", economic_weight=0.1, class_label="ON"), ShareClass("TFCO4", "QT_ACAO_PREF_CAP_INTEGR", class_label="PN"))),
    _c("TOKY3", "varejo", "25461", "31.553.627/0001-01", "GRUPO TOKY S.A. - EM RECUPERACAO JUDICIAL", ("GRUPO TOKY S.A.", "GRUPO TOKY S.A. - EM RECUPERACAO JUDICIAL", "MOBLY S.A."), status="validated_with_scale_override", note="ITRs de 2025 ate 2T26 declaram UNIDADE, mas os valores monetarios permanecem em milhares; multiplicador auditavel x1000 aplicado apenas ao intervalo validado.", statement_scale_overrides=(StatementScaleOverride("ITR", "2025-01-01", "2026-06-30", "UNIDADE", 1_000, "Continuidade com DFPs e releases oficiais confirma valores em milhares apesar do rotulo UNIDADE."),)),
    _c("VSTE3", "varejo", "21440", "49.669.856/0001-43", "VESTE S.A. ESTILO", ("VESTE S.A. ESTILO", "RESTOQUE COMERCIO E CONFECCOES DE ROUPAS S.A."), legacy_tickers=("LLIS3",)),
    _c("WEST3", "varejo", "25518", "14.776.142/0001-50", "WESTWING COMERCIO VAREJISTA S.A.", scope="ind"),
    _c("WHRL3", "varejo", "14346", "59.105.999/0001-86", "WHIRLPOOL S.A.", share_classes=(ShareClass("WHRL3", "QT_ACAO_ORDIN_CAP_INTEGR", 1_000), ShareClass("WHRL4", "QT_ACAO_PREF_CAP_INTEGR", 1_000))),
)

_BY_TICKER = {company.ticker: company for company in _COMPANIES}
if len(_BY_TICKER) != len(_COMPANIES):
    raise RuntimeError("Ticker duplicado no cadastro central")
_BY_LEGACY_TICKER = {ticker: company for company in _COMPANIES for ticker in company.legacy_tickers}


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


def operational_sectors() -> tuple[str, ...]:
    return tuple(sector for sector, config in SECTOR_CONFIG.items() if config.operational_enabled)


def tickers_for_sector(sector: str = "saude") -> tuple[str, ...]:
    return tuple(c.ticker for c in companies_for_sector(sector))


def company_by_ticker(ticker: str) -> Company:
    normalized = ticker.strip().upper()
    try:
        return _BY_TICKER.get(normalized) or _BY_LEGACY_TICKER[normalized]
    except KeyError as exc:
        raise ValueError(f"Ticker desconhecido: {ticker}") from exc


def canonical_ticker(ticker: str) -> str:
    return company_by_ticker(ticker).ticker


def statement_value_factor(company: Company, document: object, reference_date: object, declared_scale: object, default_factor: float) -> float:
    document_text = str(document or "").upper()
    scale_text = str(declared_scale or "").upper()
    reference_text = str(reference_date or "")[:10]
    for override in company.statement_scale_overrides:
        if document_text == override.document and scale_text == override.declared_scale and override.start_date <= reference_text <= override.end_date:
            return float(override.multiplier)
    matching_overrides = [override for override in company.statement_scale_overrides if document_text == override.document and scale_text == override.declared_scale]
    if matching_overrides and reference_text > max(override.end_date for override in matching_overrides):
        raise ValueError(
            f"Escala {scale_text} de {company.ticker} em {reference_text} requer validacao; "
            "o ultimo periodo coberto pelo override expirou."
        )
    return float(default_factor)

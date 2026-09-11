from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest

from operational_periods import target_quarter, display_quarter
from construction_operational import extract_markdown_observations, parse_brazilian_financial_value, identify_metric
from construction_extraction_audit import merge_observations, coverage_matrix
from construction_benchmark import classify
import app_parser_operacional as parser


def fixture(value=100, period="2T26", basis="100%"):
    return extract_markdown_observations(f"# Previa R$ milhoes {basis}\n| Indicador | {period} |\n|---|---|\n| VGV lancado | {value} |", ticker="CURY3", source_document="CURY3.pdf")[0]


def test_previous_completed_quarter_and_strict_cli():
    assert target_quarter(today=date(2026, 1, 1)) == "2025T4"
    assert target_quarter(today=date(2026, 9, 9)) == "2026T2"
    assert display_quarter("2026T2") == "2T26"
    with pytest.raises(ValueError):
        target_quarter("2T26")


def test_zero_is_observed_not_missing():
    assert fixture(0)["validation_status"] == "valid"


def test_wrong_ownership_never_published():
    _, accepted, rejected, _ = merge_observations([], [fixture(basis="participacao da companhia")])
    assert not accepted
    assert rejected[0]["validation_status"] == "quarantined"


def test_partial_merge_preserves_history_and_other_metrics():
    old = fixture(90, "1T26")
    current = fixture(100)
    merged, accepted, rejected, preserved = merge_observations([old], [current])
    assert len(merged) == 2 and accepted == [current] and not rejected and preserved == 1


def test_conflicting_sources_preserve_previous_and_all_evidence():
    old = fixture(80)
    merged, accepted, rejected, preserved = merge_observations([old], [fixture(100), fixture(110)])
    assert merged == [old] and not accepted and len(rejected) == 2 and preserved == 1


def test_no_new_coverage_from_historical_snapshot():
    _, accepted, rejected, _ = merge_observations([fixture()], [])
    rows = coverage_matrix("CURY3", "2T26", accepted, rejected, [])
    assert all(row["status"] == "document_missing" for row in rows)
    retained = [{"ticker": "CURY3", "indicator_id": "launches_vgv", "period": "2T26", "value": 1}]
    retained_rows = coverage_matrix("CURY3", "2T26", [], [], [], preserved=retained)
    assert next(row for row in retained_rows if row["indicator_id"] == "launches_vgv")["status"] == "preserved"


def test_numeric_prose_rejected_and_parentheses_negative():
    with pytest.raises(ValueError):
        parse_brazilian_financial_value("consolidacao e 9", "R$ milhoes")
    assert parse_brazilian_financial_value("(1.250)", "R$ milhoes")["parsed_value"] == -1250


def test_money_receivables_not_number_of_units():
    text = "# Contas a receber R$ MM\n| Indicador | 2T26 |\n|---|---|\n| Unidades em construcao | 17.122 |"
    assert not extract_markdown_observations(text, ticker="CYRE3", source_document="CYRE3.pdf")


def test_headers_do_not_leak_to_next_table():
    text = "# R$ milhoes 100%\n| Indicador | 2T26 |\n|---|---|\n| VGV lancado | 100 |\n\n# Outra tabela\n| Indicador | Valor |\n|---|---|\n| VGV lancado | 999 |"
    rows = extract_markdown_observations(text, ticker="CURY3", source_document="CURY3.pdf")
    assert [row["value"] for row in rows] == [100]


def test_narrative_requires_explicit_single_period_and_value():
    text = "<!-- page 16 -->\nAo final do 2T26, a participacao da companhia no estoque de terrenos era de R$ 16,1 bilhoes."
    rows = extract_markdown_observations(text, ticker="CYRE3", source_document="CYRE3.pdf")
    assert len(rows) == 1 and rows[0]["value"] == pytest.approx(16100) and rows[0]["page"] == 16
    assert not extract_markdown_observations(text.replace("2T26", "periodo"), ticker="CYRE3", source_document="CYRE3.pdf")


def test_non_disclosure_rule_not_applied_to_future_period():
    profile = {"metrics": {"launches_vgv": {"publication": "not_disclosed", "publication_periods": ["1T26"]}}}
    with patch("construction_operational.profile_for", return_value=profile):
        assert fixture(period="2T26")["validation_status"] == "valid"
        assert fixture(period="1T26")["validation_status"] == "quarantined"


def test_benchmark_protected_status_only_checks_same_metric_period():
    expected = {"Indicador canônico": "landbank_vgv", "Período": "2T26", "Status": "não divulgado"}
    assert classify(expected, [fixture()]) == "protected_state"


def test_results_page_before_home_and_no_browser_if_target_found():
    doc = parser.DocumentoEncontrado(ticker="CURY3", empresa="Cury", periodo="2T26", ano=2026,
        tipo="RELEASE_RESULTADOS", titulo_original="Release 2T26", url_origem="https://ri.example/results", url_documento="https://ri.example/2T26.pdf")
    source = {"sector": "construcao_civil", "empresa": "Cury", "url": "https://ri.example",
              "results_pages": ["https://ri.example/results"], "target_period": "2T26"}
    calls = []
    def fetch(ticker, config, session, year, browser, diagnostic):
        calls.append((config["url"], browser))
        return [doc] if config["url"].endswith("results") else []
    with patch.object(parser, "_coletar_pagina_empresa", side_effect=fetch):
        assert parser.coletar_documentos_empresa("CURY3", source, None, 2026, True) == [doc]
    assert calls == [("https://ri.example/results", False), ("https://ri.example", False)]


def test_construction_discovery_follows_result_subpage_when_parent_is_empty():
    source = {"sector": "construcao_civil", "empresa": "Cury", "url": "https://ri.example",
              "results_pages": ["https://ri.example/results"]}
    session = type("Session", (), {})()
    response = type("Response", (), {"text": '<a href="/resultados/2026">Resultados 2026</a>',
                                      "raise_for_status": lambda self: None})()
    session.get = lambda url, timeout: response
    doc = parser.DocumentoEncontrado(ticker="CURY3", empresa="Cury", periodo="2T26", ano=2026,
        tipo="RELEASE_RESULTADOS", titulo_original="Release 2T26", url_origem="https://ri.example/results",
        url_documento="https://ri.example/2T26.pdf")
    def collect(ticker, config, sess, year, browser, diagnostic):
        return [doc] if config["url"].endswith("2026") else []
    with patch.object(parser, "_coletar_pagina_empresa", side_effect=collect):
        assert parser.coletar_documentos_empresa("CURY3", source, session, 2026, False) == [doc]

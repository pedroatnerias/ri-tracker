from dashboard import _operational_annual_series
from dashboard_presentation import COMPARISON_METRICS as PRESENTATION_METRICS
from dashboard_presentation import build_chart_assets_payload as presentation_chart_assets
from dashboard_services import COMPARISON_METRICS, build_chart_assets_payload, operational_annual_series
from dashboard_financial_services import as_number, nested_get


def test_comparison_metric_contract_is_owned_by_dashboard_services():
    assert len(COMPARISON_METRICS) == 12
    assert COMPARISON_METRICS[-1] == ("n_unidades", "N. Unidades", "integer")
    assert COMPARISON_METRICS is PRESENTATION_METRICS
    assert build_chart_assets_payload is presentation_chart_assets


def test_chart_assets_service_preserves_manifest_paths_and_versions():
    payload = presentation_chart_assets(
        {"individual": {"AALR3": {"annual": "charts/AALR3/annual.png"}}, "comparison": {}},
        "v1",
        sector="saude",
        manifest_v2=False,
        url_for_path=lambda path: "/assets/" + path,
    )
    assert payload["individual"]["AALR3"]["annual"] == {
        "path": "charts/AALR3/annual.png", "url": "/assets/charts/AALR3/annual.png?v=v1"
    }


def test_operational_annual_series_dashboard_adapter_matches_service():
    series = {"1T25": 1, "2T25": 2, "3T25": 3, "4T25": 4}
    expected = operational_annual_series(series, "launches_vgv", "construcao_civil")
    assert _operational_annual_series(series, "launches_vgv", "construcao_civil") == expected


def test_financial_number_contract_preserves_nan_and_boolean_handling():
    assert as_number(float("nan")) is None
    assert as_number(True) is None
    assert nested_get({"value": float("nan")}, "value") is None

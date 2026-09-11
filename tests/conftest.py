"""Classificação operacional dos testes do projeto.

As marcas são atribuídas pelo domínio do módulo para manter a suíte existente
inalterada e permitir execuções focadas por risco.
"""

import pytest


PUBLICATION = {
    "test_chart_assets.py",
    "test_comparison_payload.py",
    "test_cagr_period_labels.py",
    "test_sector_dashboard.py",
    "test_sector_publication.py",
}
FILESYSTEM = {
    "test_data_access.py",
    "test_document_catalog.py",
    "test_manual_workflows.py",
    "test_operational_resilience.py",
    "test_update_modes.py",
}
NETWORK = {"test_cvm_downloads.py", "test_parser_ri_discovery.py", "test_remote_data_source.py"}
INTEGRATION = {
    "test_construction_operational.py",
    "test_operational_sector_isolation.py",
    "test_sector_update.py",
}
STATEFUL = {"test_manual_operational.py", "test_tracking.py"}


def pytest_collection_modifyitems(items):
    for item in items:
        filename = item.fspath.basename
        if filename in NETWORK:
            item.add_marker(pytest.mark.network)
            item.add_marker(pytest.mark.slow)
        elif filename in PUBLICATION:
            item.add_marker(pytest.mark.publication)
        elif filename in FILESYSTEM:
            item.add_marker(pytest.mark.filesystem)
        elif filename in INTEGRATION:
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
        if filename in STATEFUL:
            item.add_marker(pytest.mark.stateful)

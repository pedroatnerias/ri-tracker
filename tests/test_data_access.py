import json

from data_access import atomic_write_json, atomic_write_text, read_json, read_json_if_exists
from dashboard import DashboardDataSource, load_optional_json, load_optional_statement
from data_publication import read_json as publication_read_json
from sector_paths import read_json_if_exists as sector_read_json_if_exists


def test_read_json_decodes_local_document(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert read_json(path) == {"ok": True}


def test_atomic_write_text_replaces_previous_content(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text("old", encoding="utf-8")
    assert atomic_write_text(path, "new\n") == path
    assert path.read_text(encoding="utf-8") == "new\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_json_uses_project_serialization_contract(tmp_path):
    path = tmp_path / "payload.json"
    atomic_write_json(path, {"accent": "ação", "values": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"accent": "ação", "values": [1, 2]}


def test_read_json_if_exists_preserves_optional_object_contract(tmp_path):
    assert read_json_if_exists(tmp_path / "missing.json") is None
    path = tmp_path / "payload.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert read_json_if_exists(path) is None


def test_legacy_read_wrappers_preserve_canonical_contract(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps({"value": 7}), encoding="utf-8")
    assert publication_read_json(path) == {"value": 7}
    assert sector_read_json_if_exists(path) == {"value": 7}


def test_dashboard_optional_json_uses_shared_fallback(tmp_path):
    assert load_optional_json(tmp_path / "missing.json") is None


def test_dashboard_optional_statement_keeps_empty_mapping_contract(tmp_path):
    assert load_optional_statement(None) == {}
    assert load_optional_statement(tmp_path / "missing.json") == {}


def test_dashboard_source_memoizes_local_json_reads(tmp_path, monkeypatch):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps({"value": 1}), encoding="utf-8")
    calls = []
    original = __import__("dashboard").load_json

    def counted(candidate):
        calls.append(candidate)
        return original(candidate)

    monkeypatch.setattr("dashboard.load_json", counted)
    source = DashboardDataSource(tmp_path, mode="local")
    assert source.load_local_optional(path, "payload") == {"value": 1}
    assert source.load_local_optional(path, "payload") == {"value": 1}
    assert calls == [path]
    assert source.cache_stats() == {"local_entries": 1, "local_hits": 1, "local_misses": 1}

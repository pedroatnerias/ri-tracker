"""Offline benchmark against construction-company review matrices.

The benchmark reads only local review workbooks and local Markdown derivatives
of RI PDFs. It never downloads data or writes production JSONs.
"""
from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path
from typing import Any

from construction_operational import extract_markdown_observations
from data_access import atomic_write_json


def read_matrix(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = workbook["Evidências"]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    headers = [str(value or "").strip() for value in rows[2]]
    return [dict(zip(headers, row)) for row in rows[3:] if row and row[0]]


def read_pdf_as_markdown(path: Path) -> str:
    """Read a real review PDF without changing the review directory."""
    from app_parser_operacional import converter_pdf_para_markdown
    with tempfile.TemporaryDirectory(prefix="construction_benchmark_") as temporary:
        result = converter_pdf_para_markdown(path, diretorio_saida=Path(temporary), extrair_imagens=False, mostrar_progresso=False, construction_recovery=True)
        return Path(result["markdown"]).read_text(encoding="utf-8")


def normalize_expected(expected):
    from construction_operational import CONSTRUCTION_OPERATIONAL_DICTIONARY, normalize_text
    result = dict(expected)
    label = normalize_text(expected.get("Indicador can\u00f4nico", ""))
    metric = next((key for key, definition in CONSTRUCTION_OPERATIONAL_DICTIONARY.items()
                   if label in {normalize_text(key), normalize_text(definition["display_name"])}), None)
    result["metric_id"] = metric
    result["period"] = str(expected.get("Per\u00edodo") or "").strip().upper().replace("Q", "T")
    result["status"] = normalize_text(expected.get("Status", ""))
    result["expected_value"] = expected.get("Valor normalizado")
    if metric and metric.endswith("_vgv") and result["expected_value"] not in (None, ""):
        unit = normalize_text(expected.get("Unidade original", ""))
        if unit == "r$":
            result["expected_value"] = float(result["expected_value"]) / 1_000_000
    return result


def classify(expected: dict[str, Any], actual: list[dict[str, Any]]) -> str:
    expected = normalize_expected(expected)
    if not expected["metric_id"]:
        return "unmapped_expectation"
    candidates = [row for row in actual if row.get("indicator_id") == expected["metric_id"] and row.get("period") == expected["period"]]
    if expected["status"] in {"nao divulgado", "nao aplicavel", "ambiguo"}:
        return "protected_state" if not candidates else "false_positive"
    if not candidates:
        return "not_found"
    value = expected["expected_value"]
    if value in (None, ""):
        return "found_without_expected_value"
    from construction_operational import infer_ownership_basis
    basis = infer_ownership_basis(str(expected.get("Base de participa\u00e7\u00e3o") or ""))
    for row in candidates:
        if basis != "unknown" and row.get("ownership_basis") != basis:
            continue
        try:
            if abs(float(row["value"]) - float(value)) <= max(.000001, abs(float(value)) * .0001):
                return "match"
        except (TypeError, ValueError):
            pass
    return "mismatch"


def run(matrix_dir: Path, markdown_dir: Path, period: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"mode": "offline", "companies": {}, "source_policy": "official_ri_pdf_only"}
    for matrix in sorted(matrix_dir.rglob("matriz_ajuste_fino_construcao_civil_*.xlsx")):
        ticker = matrix.stem.removeprefix("matriz_ajuste_fino_construcao_civil_").removesuffix("_preenchida").upper()
        expected = read_matrix(matrix)
        if period:
            expected = [row for row in expected if normalize_expected(row)["period"] == period]
        expected = [row for row in expected if normalize_expected(row)["metric_id"] and normalize_expected(row)["metric_id"] not in {"roe", "credit_loss_allowance_to_receivables", "net_vso"}]
        actual: list[dict[str, Any]] = []
        seen_hashes = set()
        for markdown in markdown_dir.rglob("*.md"):
            from operational_document_handoff import resolve_markdown
            text = markdown.read_text(encoding="utf-8", errors="replace")
            resolution, metadata, reason = resolve_markdown(markdown, text)
            if resolution and resolution["ticker"] == ticker:
                digest = metadata.get("source_sha256")
                if digest and digest in seen_hashes:
                    continue
                if digest:
                    seen_hashes.add(digest)
                actual.extend(extract_markdown_observations(text, ticker=ticker, source_document=metadata.get("source_pdf", str(markdown)), source_url=metadata.get("url_documento", "")))
        for pdf in markdown_dir.rglob("*.pdf"):
            if not re.search(rf"(?i)(^|[^A-Z0-9]){re.escape(ticker)}([^A-Z0-9]|$)", pdf.name) and pdf.parent.name.upper() != ticker:
                continue
            import hashlib
            if hashlib.sha256(pdf.read_bytes()).hexdigest() in seen_hashes:
                continue
            text = read_pdf_as_markdown(pdf)
            if text:
                actual.extend(extract_markdown_observations(text, ticker=ticker, source_document=pdf.name))
        from construction_extraction_audit import merge_observations
        _, actual, rejected, _ = merge_observations([], actual)
        counts: dict[str, int] = {}
        comparisons = []
        for row in expected:
            result = classify(row, actual)
            comparisons.append({"expected": normalize_expected(row), "result": result})
            counts[result] = counts.get(result, 0) + 1
        report["companies"][ticker] = {
            "expected_observations": len(expected),
            "actual_observations": len(actual),
            "documents_processed": len({str(item.get("source_document") or "") for item in actual}),
            "classification": counts,
            "comparisons": comparisons,
            "rejected_observations": rejected,
            "quality_dimensions": {
                "value": counts.get("match", 0),
                "unit": sum(1 for item in actual if item.get("unit")),
                "scale": sum(1 for item in actual if item.get("scale")),
                "period": sum(1 for item in actual if item.get("period")),
                "ownership_basis": sum(1 for item in actual if item.get("ownership_basis")),
                "sign": sum(1 for item in actual if item.get("value") is not None and float(item.get("value")) != 0),
                "false_positive": counts.get("false_positive", 0),
                "absence_as_zero": 0,
            },
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--markdown-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--period", default=None)
    args = parser.parse_args()
    atomic_write_json(args.output, run(args.matrix_dir, args.markdown_dir, args.period))


if __name__ == "__main__":
    main()

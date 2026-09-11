"""Consolidate isolated construction discovery/extraction tracking."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--discovery", type=Path, required=True)
    cli.add_argument("--extraction", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    discovery = read(args.discovery)
    if not isinstance(discovery, list):
        raise SystemExit("discovery_result.json inválido")
    extraction = read(args.extraction) if args.extraction else None
    by_ticker = {}
    for row in discovery:
        diagnostics = row.get("diagnostics", [])
        causes = Counter(item.get("error", item.get("reason", "unknown")) for item in diagnostics)
        by_ticker[row["ticker"]] = {"discovery_status": row.get("status"), "documents": len(row.get("documents", [])), "errors": row.get("errors", []), "diagnostic_causes": dict(causes)}
    if isinstance(extraction, dict):
        report_rejections = dict(extraction.get("rejection_reasons") or {})
        for row in extraction.get("coverage", []):
            item = by_ticker.setdefault(row["ticker"], {})
            item.setdefault("coverage", Counter())
            item["coverage"][row["status"]] += 1
            for rejected in row.get("rejected", []):
                reason = str(rejected.get("rejection_reason") or rejected.get("validation_status") or "unknown")
                report_rejections[reason] = report_rejections.get(reason, 0) + 1
        for item in by_ticker.values():
            if isinstance(item.get("coverage"), Counter):
                item["coverage"] = dict(item["coverage"])
    else:
        report_rejections = {}
    report = {"schema_version": 1, "companies": len(by_ticker), "discovery_status": dict(Counter(item.get("discovery_status") for item in by_ticker.values())), "diagnostic_causes": dict(Counter(cause for item in by_ticker.values() for cause in item.get("diagnostic_causes", {}))), "rejection_reasons": report_rejections, "by_ticker": by_ticker}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"companies": report["companies"], "discovery_status": report["discovery_status"], "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

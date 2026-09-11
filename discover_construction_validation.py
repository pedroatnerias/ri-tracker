"""Collect target-quarter RI PDFs into an isolated validation directory."""
import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import ssl
import uuid

import app_parser_operacional as parser
from operational_sources import operational_sources_for_sector
from operational_periods import target_quarter, display_quarter
from data_access import atomic_write_json
from tracking import TrackingRun


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=Path("tmp/operational_validation/discovery"))
    cli.add_argument("--periodo-alvo", type=target_quarter, default=target_quarter())
    cli.add_argument("--system-ca", action="store_true", help="Use OS trusted public certificates for validation requests")
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    bundle = None
    if args.system_ca:
        bundle = args.output / "system_ca.pem"
        bundle.write_text("".join(ssl.DER_cert_to_PEM_cert(cert) for cert in ssl.create_default_context().get_ca_certs(binary_form=True)), encoding="ascii")
    sources = operational_sources_for_sector("construcao_civil")
    parser.TIMEOUT_REQUISICAO = 15
    def collect(item):
        ticker, source = item
        tracker = TrackingRun(sector="construcao_civil", pipeline="operational_discovery", extractor_version="construction_discovery_v1", run_id=f"{run_id}-{ticker}")
        session = parser.criar_sessao_http()
        if bundle:
            session.verify = str(bundle.resolve())
        source = {**source, "target_period": display_quarter(args.periodo_alvo)}
        source["diagnostics"] = []
        result = {"ticker": ticker, "target_period": args.periodo_alvo, "documents": [], "errors": []}
        try:
            documents = parser.coletar_documentos_empresa(ticker, source, session, int(args.periodo_alvo[:4]), False)
            for document in documents:
                document_id = tracker.document(source_url=document.url_documento, source_type="PDF", ticker=ticker, period=document.periodo)
                tracker.event(document_id, "accepted", period=document.periodo)
            for document in documents:
                if document.periodo != display_quarter(args.periodo_alvo):
                    continue
                try:
                    downloaded = parser.baixar_documento(document, session, False, args.output / "pdfs" / ticker)
                    if downloaded:
                        result["documents"].append(asdict(downloaded))
                        tracker.event(document_id, "downloaded", path=downloaded.arquivo_local, sha256=downloaded.sha256)
                except Exception as exc:
                    result["errors"].append({"url": document.url_documento, "status": "download_failed", "error": str(exc)})
                    tracker.event(document_id, "extraction_error", error_type="download_failed")
            if result["documents"]:
                result["status"] = "downloaded"
            elif result["errors"]:
                result["status"] = "download_failed"
            elif source.get("diagnostics"):
                result["status"] = "discovery_failed"
            else:
                result["status"] = "document_missing"
            if result["status"] in {"document_missing", "discovery_failed"}:
                reason = result["status"]
                tracker.event(tracker.document(source_url=source.get("url", ""), source_type="results_page", ticker=ticker), "unresolved", reason=reason)
            result["diagnostics"] = source.get("diagnostics", [])
        except Exception as exc:
            result["status"] = "discovery_failed"
            result["errors"].append({"error": str(exc)})
        finally:
            session.close()
        result["tracking"] = tracker.payload()
        atomic_write_json(args.output / f"{ticker}.json", result)
        return result
    with (args.output / "discovery.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(collect, sources.items()))
    atomic_write_json(args.output / "discovery_result.json", results)
    atomic_write_json(args.output / "tracking.json", {"run_id": run_id, "sector": "construcao_civil", "pipeline": "operational_discovery", "target_period": args.periodo_alvo, "companies": results})
    print({"companies": len(results), "companies_with_pdfs": sum(bool(row["documents"]) for row in results), "report": str(args.output / "discovery_result.json")})


if __name__ == "__main__":
    main()

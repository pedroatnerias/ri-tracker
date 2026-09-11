"""Isolated replay of official review PDFs; never writes production snapshots."""
from pathlib import Path
import argparse
import asyncio
import contextlib
import json

from app_parser_operacional import converter_pdf_para_markdown
from app_extrator_operacional import build_parser, run
from data_access import atomic_write_json
from operational_periods import target_quarter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Indicadores para Revisão"))
    parser.add_argument("--output", type=Path, default=Path("tmp/operational_validation"))
    parser.add_argument("--periodo-alvo", type=target_quarter, default=target_quarter())
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    with (args.output / "conversion.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        for pdf in sorted(args.source.rglob("*.pdf")):
            try:
                result = converter_pdf_para_markdown(pdf, diretorio_saida=args.output / "markdown" / pdf.parent.name,
                    extrair_imagens=False, mostrar_progresso=False, construction_recovery=True)
                records.append({"source": str(pdf), "ticker": pdf.parent.name, "status": "converted", **result})
            except Exception as exc:
                records.append({"source": str(pdf), "ticker": pdf.parent.name, "status": "conversion_failed", "error": str(exc)})
        extraction_args = build_parser().parse_args(["--sector", "construcao_civil", "--md-dir", str(args.output / "markdown"),
            "--output-dir", str(args.output / "snapshots"), "--periodo-alvo", args.periodo_alvo,
            "--result-json", str(args.output / "extraction_result.json")])
        exit_code = asyncio.run(run(extraction_args))
    atomic_write_json(args.output / "conversion_result.json", records)
    result = json.loads((args.output / "extraction_result.json").read_text(encoding="utf-8"))
    counts = {}
    for row in result["coverage"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"documents": len(records), "coverage": counts, "extractor_exit_code": exit_code,
                      "report": str(args.output / "extraction_result.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

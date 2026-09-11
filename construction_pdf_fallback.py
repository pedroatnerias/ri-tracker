"""Page-scoped text/table recovery; never infers financial values."""
import pymupdf
import re


def coordinate_tables(page):
    """Recover numeric rows under explicit horizontally aligned period headers."""
    lines = {}
    for word in page.get_text("words"):
        # Word baselines in one row can differ slightly due to font size.
        y = round(word[3] / 3) * 3
        lines.setdefault(y, []).append(word)
    output = []
    headers = []
    rows = []
    page_text = page.get_text("text").lower()
    monetary_scope = "contas a receber" in page_text or "recebíveis" in page_text or "recebiveis" in page_text
    for y, words in sorted(lines.items()):
        words.sort(key=lambda word: word[0])
        periods = [word for word in words if re.fullmatch(r"(?:[1-4][TQ]\d{2,4}|[69]M\d{2,4}|20\d{2})", word[4], re.I)]
        comparisons = [word for word in words if word[4].lower() in {"x", "/"}]
        periods = [word for word in periods if not any(abs(word[2] - other[0]) < 8 or abs(other[2] - word[0]) < 8 for other in comparisons)]
        if periods and periods[0][0] > page.rect.width * .75:
            periods = []
        if len(periods) >= 2:
            if rows:
                output.append(rows)
            headers = periods
            rows = [["Contas a receber R$" if monetary_scope else "Indicador", *[word[4] for word in headers]]]
            continue
        if not headers:
            continue
        numeric_start = headers[0][0] - 15
        label = " ".join(word[4] for word in words if word[0] < numeric_start)
        if not label:
            continue
        cells = []
        for header in headers:
            center = (header[0] + header[2]) / 2
            matching = [word[4] for word in words if abs((word[0] + word[2]) / 2 - center) < 18 and word[0] >= numeric_start]
            cells.append(" ".join(matching))
        if any(re.fullmatch(r"\(?-?\d[\d., ]*\)?", cell) for cell in cells):
            rows.append([label, *cells])
    if rows:
        output.append(rows)
    return output


def recover_pages(path, language="por+eng"):
    chunks = []
    diagnostics = []
    with pymupdf.open(path) as document:
        for number, page in enumerate(document, 1):
            text = page.get_text("text")
            method = "coordinates"
            if len(text.strip()) < 40:
                try:
                    textpage = page.get_textpage_ocr(language=language, dpi=300, full=True)
                    text = page.get_text("text", textpage=textpage)
                    method = "ocr"
                except (RuntimeError, ValueError) as exc:
                    diagnostics.append({"page": number, "status": "ocr_failed", "error": type(exc).__name__})
            chunks.append(f"\n\n<!-- page {number} -->\n\n{text}\n")
            # Text strategy supports borderless tables; cell positions remain explicit.
            try:
                tables = coordinate_tables(page)
                for rows in tables:
                    if len(rows) < 2:
                        continue
                    rendered = ["| " + " | ".join(str(cell or "").replace("\n", "<br>").replace("|", " ") for cell in row) + " |" for row in rows]
                    rendered.insert(1, "|" + "---|" * len(rows[0]))
                    chunks.append("\n".join(rendered) + "\n\n")
                diagnostics.append({"page": number, "status": "recovered", "method": method, "tables": len(tables)})
            except (RuntimeError, ValueError) as exc:
                diagnostics.append({"page": number, "status": "table_recovery_failed", "error": type(exc).__name__})
    return "\n".join(chunks), diagnostics

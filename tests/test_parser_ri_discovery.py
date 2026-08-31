import unittest

from app_parser_operacional import extrair_links_html


def docs(html: str):
    return extrair_links_html(
        html=html,
        url_base="https://ri.example.com/central/",
        ticker="TEST3",
        empresa="Teste",
        ano_inicial=2022,
    )


class ParserRiDiscoveryTests(unittest.TestCase):
    def test_traditional_pdf_link(self):
        found = docs('<a href="/release-2T26.pdf">Release de resultados 2T26</a>')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].periodo, "2T26")
        self.assertEqual(found[0].tipo, "RELEASE_RESULTADOS")

    def test_download_endpoint_without_pdf_extension(self):
        found = docs(
            '<a href="/download?id=10">Release de resultados 2T26 Download</a>'
        )
        self.assertEqual(len(found), 1)
        self.assertIn("/download", found[0].url_documento)

    def test_period_context_in_parent_container(self):
        found = docs(
            '<section><h2>2026</h2><div><h3>2T26</h3>'
            '<a href="/docs/apresentacao?id=10">Download</a>'
            '<span>Apresentacao de resultados</span></div></section>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].periodo, "2T26")
        self.assertEqual(found[0].tipo, "APRESENTACAO_RESULTADOS")

    def test_type_context_in_parent_container(self):
        found = docs(
            '<div><strong>Release de resultados</strong><span>2T26</span>'
            '<button data-download="/api/documento/10">Download</button></div>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].tipo, "RELEASE_RESULTADOS")

    def test_pdf_url_inside_json_script(self):
        found = docs(
            '<script type="application/json">'
            '{"title":"Demonstrações financeiras 2T26",'
            '"url":"https://cdn.example.com/itr-2T26.pdf"}'
            '</script>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].tipo, "DEMONSTRACOES_FINANCEIRAS")

    def test_relative_pdf_url_inside_json_script(self):
        found = docs(
            '<script type="application/json">'
            '{"title":"Release de resultados 2T26",'
            '"url":"/downloads/release-2T26.pdf"}'
            '</script>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].url_documento,
            "https://ri.example.com/downloads/release-2T26.pdf",
        )

    def test_deduplicates_same_url(self):
        found = docs(
            '<div>Release de resultados 2T26 '
            '<a href="/download?id=1">Download</a>'
            '<button data-url="/download?id=1">Baixar</button></div>'
        )
        self.assertEqual(len(found), 1)

    def test_missing_context_does_not_invent_classification(self):
        found = docs('<a href="/download?id=1">Download</a>')
        self.assertEqual(found, [])

    def test_operational_preview_is_accepted(self):
        found = docs('<a href="/previa-operacional-1T26.pdf">Previa operacional 1T26</a>')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].tipo, "PREVIA_OPERACIONAL")

    def test_official_xlsx_spreadsheet_is_accepted(self):
        found = docs('<a href="/fundamentos-2T26.xlsx">Planilha de fundamentos 2T26 Excel</a>')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].tipo, "PLANILHA_RESULTADOS")


if __name__ == "__main__":
    unittest.main()

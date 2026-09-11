import unittest

from app_parser_operacional import extrair_links_html, _discover_result_subpages, documentos_de_network
from unittest.mock import Mock


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

    def test_protocol_relative_and_escaped_json_url(self):
        found = docs(
            '<script>{"title":"Release de resultados 2T26",'
            '"url":"//cdn.example.com\\/release-2T26.pdf"}</script>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].url_documento, "https://cdn.example.com/release-2T26.pdf")

    def test_mziq_opaque_file_manager_url_uses_document_context(self):
        found = docs(
            '<a href="https://api.mziq.com/mzfilemanager/v2/d/id/file?origin=2">'
            'Release de resultados 2T26</a>'
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].tipo, "RELEASE_RESULTADOS")

    def test_mziq_opaque_asset_without_document_context_is_ignored(self):
        self.assertEqual(docs('<img src="https://api.mziq.com/mzfilemanager/v2/d/id/file">'), [])

    def test_result_subpages_are_same_domain_and_ranked(self):
        response = Mock(status_code=200, text='''
            <a href="/random">Home</a>
            <a href="/central-de-resultados/2026">Resultados 2026</a>
            <a href="https://other.example/results">Resultados externo</a>
            <a href="/relatorios">Relatórios</a>
        ''')
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        found = _discover_result_subpages("https://ri.example.com/", session)
        self.assertEqual(found, ["https://ri.example.com/central-de-resultados/2026", "https://ri.example.com/relatorios"])

    def test_network_opaque_url_uses_rendered_page_context(self):
        found = documentos_de_network(
            [{"url": "https://api.mziq.com/mzfilemanager/v2/d/id/file?origin=2",
              "content_type": "application/pdf", "status": 200}],
            ticker="MRVE3", empresa="MRV", ano_inicial=2022,
            url_origem="https://ri.mrv.com.br/",
            page_context="Central de resultados 2T26 Earnings Release",
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].periodo, "2T26")


if __name__ == "__main__":
    unittest.main()

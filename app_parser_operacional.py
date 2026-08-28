from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import pymupdf
import pymupdf4llm
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RELEASES_RELATORIOS_DIR = BASE_DIR / "Releases e relatórios"
PASTA_ENTRADA_PADRAO = RELEASES_RELATORIOS_DIR / "Entrada"
PASTA_SAIDA_PADRAO = RELEASES_RELATORIOS_DIR / "Saída"
ARQUIVO_MANIFESTO_DOWNLOADS = (
    RELEASES_RELATORIOS_DIR / "manifesto_downloads.json"
)
PASTA_DIAGNOSTICO_RI = BASE_DIR / "diagnostico_ri"

ANO_INICIAL_PADRAO = 2022
TIMEOUT_REQUISICAO = 45
INTERVALO_ENTRE_DOWNLOADS = 0.35

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0 Safari/537.36"
)


class PlaywrightIndisponivel(RuntimeError):
    def __init__(self, mensagem: str, documentos: list[Any] | None = None) -> None:
        super().__init__(mensagem)
        self.documentos = documentos or []

EMPRESAS = {
    "RDOR3": {
        "empresa": "Rede D'Or São Luiz",
        "url": (
            "https://ri.rededorsaoluiz.com.br/"
            "informacoes-financeiras/central-de-resultados/"
        ),
    },
    "MATD3": {
        "empresa": "Rede Mater Dei",
        "url": (
            "https://ri.materdei.com.br/"
            "informacoes-aos-acionistas/central-de-resultados/"
        ),
    },
    "FLRY3": {
        "empresa": "Grupo Fleury",
        "url": (
            "https://ri.fleury.com.br/"
            "informacoes-financeiras-e-apresentacoes/"
            "central-de-resultados/"
        ),
    },
    "AALR3": {
        "empresa": "Alliança Saúde",
        "url": (
            "https://ri.allianca.com/"
            "informacoes-financeiras/central-de-resultados/"
        ),
    },
    "DASA3": {
        "empresa": "Dasa",
        "url": (
            "https://www.dasa3.com.br/"
            "informacoes-financeiras/resultado-trimestral/"
        ),
    },
    "ONCO3": {
        "empresa": "Oncoclínicas",
        "url": (
            "https://ri.grupooncoclinicas.com/"
            "informacoes-financeiras/central-de-resultados/"
        ),
    },
    "HAPV3": {
        "empresa": "Hapvida",
        "url": (
            "https://ri.hapvida.com.br/"
            "informacoes-financeiras/central-de-resultados/"
        ),
    },
}

TIPOS_DOCUMENTO = {
    "DEMONSTRACOES_FINANCEIRAS": (
        "demonstracoes financeiras",
        "demonstração financeira",
        "demonstrações financeiras",
        "financial statements",
        "itr",
        "dfp",
        "informacoes trimestrais",
        "informações trimestrais",
    ),
    "RELEASE_RESULTADOS": (
        "release de resultados",
        "release resultados",
        "earnings release",
        "relatorio de resultados",
        "relatório de resultados",
        "press release",
    ),
    "APRESENTACAO_RESULTADOS": (
        "apresentacao de resultados",
        "apresentação de resultados",
        "apresentacao resultados",
        "apresentação resultados",
        "earnings presentation",
        "resultados apresentacao",
        "resultados apresentação",
    ),
    "TRANSCRICAO_WEBCAST": (
        "transcricao",
        "transcrição",
        "transcript",
        "webcast transcript",
        "teleconferencia transcricao",
        "teleconferência transcrição",
        "transcricao da teleconferencia",
        "transcrição da teleconferência",
    ),
}

TERMOS_EXCLUIDOS = (
    "audio",
    "áudio",
    "video",
    "vídeo",
    "webcast ao vivo",
    "calendar",
    "calendario",
    "calendário",
    "planilha",
    "spreadsheet",
    "xlsx",
    "excel",
)


# ============================================================
# MODELOS
# ============================================================

@dataclass
class DocumentoEncontrado:
    ticker: str
    empresa: str
    periodo: str
    ano: int
    tipo: str
    titulo_original: str
    url_origem: str
    url_documento: str


@dataclass
class DownloadRealizado:
    ticker: str
    empresa: str
    periodo: str
    ano: int
    tipo: str
    titulo_original: str
    url_origem: str
    url_documento: str
    arquivo_local: str
    nome_arquivo: str
    sha256: str
    baixado_em: str
    status: str


@dataclass
class RespostaPlaywright:
    html: str
    url_final: str
    network_items: list[dict[str, str | int]]


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def garantir_pastas_padrao() -> None:
    PASTA_ENTRADA_PADRAO.mkdir(parents=True, exist_ok=True)
    PASTA_SAIDA_PADRAO.mkdir(parents=True, exist_ok=True)


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar_nome_arquivo(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", nome)
    nome = nome.encode("ascii", "ignore").decode("ascii")
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", nome)
    return nome.strip("._-") or "documento"


def calcular_sha256(caminho: Path) -> str:
    hash_obj = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            hash_obj.update(bloco)

    return hash_obj.hexdigest()


def criar_sessao_http() -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,application/pdf;q=0.8,*/*;q=0.7"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        }
    )
    return sessao


# ============================================================
# IDENTIFICAÇÃO DOS DOCUMENTOS
# ============================================================

def identificar_periodo(texto: str) -> tuple[str, int] | None:
    """
    Identifica períodos como 1T26, 2T2025, 4Q25, FY2025 e 2025.
    """
    texto_normalizado = normalizar_texto(unquote(texto))

    padroes_trimestrais = (
        r"\b([1-4])\s*[tq]\s*[-_/]?\s*(20\d{2}|\d{2})\b",
        r"\b([1-4])\s*(?:tri|trimestre)\s*[-_/]?\s*(20\d{2}|\d{2})\b",
        r"\b(20\d{2}|\d{2})\s*[-_/]?\s*([1-4])\s*[tq]\b",
    )

    for indice, padrao in enumerate(padroes_trimestrais):
        correspondencia = re.search(padrao, texto_normalizado)

        if not correspondencia:
            continue

        if indice < 2:
            trimestre = int(correspondencia.group(1))
            ano_texto = correspondencia.group(2)
        else:
            ano_texto = correspondencia.group(1)
            trimestre = int(correspondencia.group(2))

        ano = int(ano_texto)
        if ano < 100:
            ano += 2000

        return f"{trimestre}T{str(ano)[-2:]}", ano

    padrao_anual = re.search(
        r"\b(?:fy|dfp|anual|annual)?\s*[-_/]?\s*(20\d{2})\b",
        texto_normalizado,
    )

    if padrao_anual:
        ano = int(padrao_anual.group(1))
        return f"4T{str(ano)[-2:]}", ano

    return None


def classificar_tipo_documento(texto: str) -> str | None:
    texto_normalizado = normalizar_texto(texto)

    if any(
        normalizar_texto(termo) in texto_normalizado
        for termo in TERMOS_EXCLUIDOS
    ):
        return None

    # A transcrição precisa ser avaliada primeiro para não ser confundida
    # com outros documentos associados à teleconferência.
    ordem = (
        "TRANSCRICAO_WEBCAST",
        "DEMONSTRACOES_FINANCEIRAS",
        "RELEASE_RESULTADOS",
        "APRESENTACAO_RESULTADOS",
    )

    for tipo in ordem:
        termos = TIPOS_DOCUMENTO[tipo]

        if any(
            normalizar_texto(termo) in texto_normalizado
            for termo in termos
        ):
            return tipo

    return None


def parece_pdf(url: str, texto: str = "") -> bool:
    caminho = urlparse(url).path.lower()

    if caminho.endswith(".pdf"):
        return True

    combinado = normalizar_texto(f"{url} {texto}")

    return (
        ".pdf" in combinado
        or "download" in combinado
        or "documento" in combinado
        or "arquivo" in combinado
        or "file" in combinado
        or "document" in combinado
        or "download" in caminho
    )


def contexto_elemento(elemento: Any, limite_ancestrais: int = 5) -> str:
    partes: list[str] = []
    atual = elemento

    for _ in range(limite_ancestrais):
        if not atual:
            break
        try:
            texto = atual.get_text(" ", strip=True)
        except Exception:
            texto = ""
        if texto:
            partes.append(texto)
        atual = getattr(atual, "parent", None)

    anterior = elemento.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    if anterior:
        partes.append(anterior.get_text(" ", strip=True))

    return " ".join(partes)


def valores_url_atributos(elemento: Any) -> list[str]:
    urls: list[str] = []
    for nome, valor in elemento.attrs.items():
        valores = valor if isinstance(valor, list) else [valor]
        for item in valores:
            texto = str(item).strip()
            if not texto:
                continue
            nome_normalizado = normalizar_texto(nome)
            texto_normalizado = normalizar_texto(texto)
            if (
                nome in {"href", "src", "data-href", "data-url", "data-download"}
                or nome_normalizado.startswith("data")
                or parece_pdf(texto, nome)
                or any(
                    termo in texto_normalizado
                    for termo in ("download", "document", "arquivo", "documento", "pdf")
                )
            ):
                urls.append(texto)
    return urls


def limpar_url_extraida(url: str) -> str:
    return url.replace("\\/", "/").strip().strip("\"'()[]{};,")


def urls_em_texto(texto: str) -> list[str]:
    urls = [
        limpar_url_extraida(url)
        for url in re.findall(r"""https?://[^"'<>\\\s]+""", texto)
    ]
    relativas = re.findall(
        r"""(?P<url>/[^"'<>\\\s]*(?:\.pdf|download|document|arquivo|documento)[^"'<>\\\s]*)""",
        texto,
        flags=re.IGNORECASE,
    )
    urls.extend(limpar_url_extraida(url) for url in relativas)
    return urls


def montar_documento(
    *,
    ticker: str,
    empresa: str,
    periodo_ano: tuple[str, int] | None,
    tipo: str | None,
    ano_inicial: int,
    titulo: str,
    url_origem: str,
    url_documento: str,
) -> DocumentoEncontrado | None:
    if not tipo or not periodo_ano:
        return None

    periodo, ano = periodo_ano
    if ano < ano_inicial:
        return None

    return DocumentoEncontrado(
        ticker=ticker,
        empresa=empresa,
        periodo=periodo,
        ano=ano,
        tipo=tipo,
        titulo_original=titulo or Path(urlparse(url_documento).path).name,
        url_origem=url_origem,
        url_documento=url_documento.split("#", 1)[0],
    )


def extrair_links_html(
    html: str,
    url_base: str,
    ticker: str,
    empresa: str,
    ano_inicial: int,
) -> list[DocumentoEncontrado]:
    soup = BeautifulSoup(html, "html.parser")
    encontrados: list[DocumentoEncontrado] = []
    urls_vistas: set[str] = set()

    for elemento in soup.find_all(True):
        urls_elemento = valores_url_atributos(elemento)
        titulo = " ".join(elemento.stripped_strings).strip()

        atributos = " ".join(
            str(valor)
            for valor in elemento.attrs.values()
        )
        contexto = contexto_elemento(elemento)

        for href in urls_elemento:
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            url_documento = urljoin(url_base, href)
            texto_completo = f"{titulo} {href} {atributos} {contexto}"

            if not parece_pdf(url_documento, texto_completo):
                continue

            documento = montar_documento(
                ticker=ticker,
                empresa=empresa,
                periodo_ano=identificar_periodo(texto_completo),
                tipo=classificar_tipo_documento(texto_completo),
                ano_inicial=ano_inicial,
                titulo=titulo,
                url_origem=url_base,
                url_documento=url_documento,
            )

            if not documento or documento.url_documento in urls_vistas:
                continue

            urls_vistas.add(documento.url_documento)
            encontrados.append(documento)

    # Captura URLs presentes em scripts/JSON. A URL nao precisa terminar em
    # .pdf, mas precisa ter contexto suficiente de periodo e tipo.
    for url_extraida in urls_em_texto(html):
        url_documento = urljoin(url_base, url_extraida)
        posicao = html.find(url_documento)
        if posicao < 0:
            posicao = html.find(url_extraida)
        contexto = (
            f"{url_extraida} {url_documento} "
            f"{html[max(0, posicao - 600):posicao + 600] if posicao >= 0 else ''}"
        )
        if not parece_pdf(url_documento, contexto):
            continue

        documento = montar_documento(
            ticker=ticker,
            empresa=empresa,
            periodo_ano=identificar_periodo(contexto),
            tipo=classificar_tipo_documento(contexto),
            ano_inicial=ano_inicial,
            titulo=Path(urlparse(url_documento).path).name,
            url_origem=url_base,
            url_documento=url_documento,
        )
        if documento and documento.url_documento not in urls_vistas:
            urls_vistas.add(documento.url_documento)
            encontrados.append(documento)

    return encontrados


# ============================================================
# COLETA DAS PÁGINAS DE RI
# ============================================================

def obter_html_requests(
    sessao: requests.Session,
    url: str,
) -> str:
    resposta = sessao.get(
        url,
        timeout=TIMEOUT_REQUISICAO,
    )
    resposta.raise_for_status()
    return resposta.text


def diagnostico_html(html: str, url_final: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for elemento in soup.find_all(True):
        urls.extend(valores_url_atributos(elemento))
    urls.extend(urls_em_texto(html))
    dominios: dict[str, int] = {}
    for item in urls:
        dominio = urlparse(item).netloc
        if dominio:
            dominios[dominio] = dominios.get(dominio, 0) + 1
    texto = normalizar_texto(html)
    return {
        "url_final": url_final,
        "html_bytes": len(html.encode("utf-8", errors="replace")),
        "links_a": len(soup.find_all("a")),
        "buttons": len(soup.find_all("button")),
        "url_attrs": len(urls),
        "urls_pdf": sum(1 for item in urls if "pdf" in normalizar_texto(item)),
        "urls_download": sum(1 for item in urls if "download" in normalizar_texto(item)),
        "urls_arquivo": sum(1 for item in urls if "arquivo" in normalizar_texto(item)),
        "urls_documento": sum(1 for item in urls if "documento" in normalizar_texto(item) or "document" in normalizar_texto(item)),
        "iframes": len(soup.find_all("iframe")),
        "scripts": len(soup.find_all("script")),
        "principais_dominios": sorted(dominios.items(), key=lambda item: item[1], reverse=True)[:10],
        "contem_textos": {
            termo: normalizar_texto(termo) in texto
            for termo in ("1T26", "2T26", "resultados", "release", "apresentacao", "apresentação", "demonstrações financeiras")
        },
    }


def imprimir_diagnostico(ticker: str, origem: str, dados: dict[str, Any]) -> None:
    print(f"[diagnostico-ri] {ticker} | {origem}")
    for chave, valor in dados.items():
        print(f"  {chave}: {valor}")


def salvar_snapshot_diagnostico(ticker: str, origem: str, html: str) -> None:
    PASTA_DIAGNOSTICO_RI.mkdir(parents=True, exist_ok=True)
    nome = normalizar_nome_arquivo(f"{ticker}_{origem}.html")
    (PASTA_DIAGNOSTICO_RI / nome).write_text(html, encoding="utf-8")


def documento_de_contexto(
    *,
    ticker: str,
    empresa: str,
    ano_inicial: int,
    url_origem: str,
    url_documento: str,
    contexto: str,
) -> DocumentoEncontrado | None:
    if not parece_pdf(url_documento, contexto):
        return None
    return montar_documento(
        ticker=ticker,
        empresa=empresa,
        periodo_ano=identificar_periodo(contexto),
        tipo=classificar_tipo_documento(contexto),
        ano_inicial=ano_inicial,
        titulo=Path(urlparse(url_documento).path).name,
        url_origem=url_origem,
        url_documento=url_documento,
    )


def documentos_de_network(
    network_items: list[dict[str, str | int]],
    ticker: str,
    empresa: str,
    ano_inicial: int,
    url_origem: str,
) -> list[DocumentoEncontrado]:
    documentos: list[DocumentoEncontrado] = []
    vistos: set[str] = set()
    for item in network_items:
        url = str(item.get("url") or "")
        content_type = str(item.get("content_type") or "")
        contexto = f"{url} {content_type} {item.get('body_preview') or ''}"
        if "application/pdf" in content_type.lower():
            contexto = f"{contexto} pdf"
        documento = documento_de_contexto(
            ticker=ticker,
            empresa=empresa,
            ano_inicial=ano_inicial,
            url_origem=url_origem,
            url_documento=url,
            contexto=contexto,
        )
        if documento and documento.url_documento not in vistos:
            vistos.add(documento.url_documento)
            documentos.append(documento)
    return documentos


def obter_html_playwright_resultado(url: str) -> RespostaPlaywright:
    """
    Renderiza páginas dinâmicas. Requer:

        pip install playwright
        playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as erro:
        raise PlaywrightIndisponivel(
            "A página exige JavaScript, mas Playwright não está instalado. "
            "Execute: pip install playwright && playwright install chromium"
        ) from erro

    with sync_playwright() as playwright:
        try:
            navegador = playwright.chromium.launch(
                headless=True,
            )
        except Exception as erro:
            mensagem = str(erro)
            if (
                "Executable doesn't exist" in mensagem
                or "playwright install" in mensagem
                or "was just installed or updated" in mensagem
            ):
                raise PlaywrightIndisponivel(
                    "Playwright estÃ¡ instalado, mas o navegador Chromium nÃ£o foi baixado. "
                    "Execute: python -m playwright install chromium. "
                    "Como alternativa, use --sem-playwright para processar apenas HTML estÃ¡tico/PDFs locais."
                ) from None
            raise

        network_items: list[dict[str, str | int]] = []

        def registrar_resposta(resposta: Any) -> None:
            try:
                content_type = resposta.headers.get("content-type", "")
                url_resposta = resposta.url
                url_norm = normalizar_texto(url_resposta)
                content_norm = normalizar_texto(content_type)
                relevante = (
                    "application/pdf" in content_norm
                    or ".pdf" in url_norm
                    or "download" in url_norm
                    or "document" in url_norm
                    or "arquivo" in url_norm
                    or "json" in content_norm
                )
                if not relevante:
                    return
                item: dict[str, str | int] = {
                    "url": url_resposta,
                    "method": resposta.request.method,
                    "status": resposta.status,
                    "content_type": content_type,
                }
                if "json" in content_norm or "text" in content_norm:
                    try:
                        item["body_preview"] = resposta.text()[:4000]
                    except Exception:
                        pass
                network_items.append(item)
            except Exception:
                return

        pagina = navegador.new_page(
            user_agent=USER_AGENT,
            locale="pt-BR",
        )
        pagina.on("response", registrar_resposta)

        pagina.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        # Algumas centrais carregam anos e documentos de modo assíncrono.
        pagina.wait_for_timeout(5_000)

        # Tenta clicar em botões de ano, "ver mais" e abas recolhidas.
        seletores = (
            "button",
            "[role='button']",
            ".accordion-header",
            ".accordion-button",
            ".year",
            ".ano",
            ".tab",
        )

        for seletor in seletores:
            try:
                elementos = pagina.locator(seletor)
                quantidade = min(elementos.count(), 100)

                for indice in range(quantidade):
                    elemento = elementos.nth(indice)

                    try:
                        texto = normalizar_texto(
                            elemento.inner_text(timeout=500)
                        )

                        if (
                            re.fullmatch(r"20\d{2}", texto)
                            or "ver mais" in texto
                            or "carregar mais" in texto
                            or "resultados" in texto
                        ):
                            elemento.click(
                                timeout=700,
                                force=True,
                            )
                            pagina.wait_for_timeout(300)
                    except Exception:
                        continue
            except Exception:
                continue

        pagina.wait_for_timeout(2_000)
        html = pagina.content()
        url_final = pagina.url
        navegador.close()

    return RespostaPlaywright(
        html=html,
        url_final=url_final,
        network_items=network_items,
    )


def obter_html_playwright(url: str) -> str:
    return obter_html_playwright_resultado(url).html


def coletar_documentos_empresa(
    ticker: str,
    configuracao: dict[str, str],
    sessao: requests.Session,
    ano_inicial: int,
    usar_playwright: bool,
    diagnostico_ri: bool = False,
) -> list[DocumentoEncontrado]:
    empresa = configuracao["empresa"]
    url = configuracao["url"]

    print(f"\n[{ticker}] Consultando {empresa}")
    print(f"Página: {url}")

    documentos_requests: list[DocumentoEncontrado] = []

    try:
        resposta = sessao.get(url, timeout=TIMEOUT_REQUISICAO)
        resposta.raise_for_status()
        html = resposta.text

        if diagnostico_ri:
            dados = diagnostico_html(html, resposta.url)
            dados["status_http"] = resposta.status_code
            imprimir_diagnostico(ticker, "requests", dados)
            salvar_snapshot_diagnostico(ticker, "requests", html)

        documentos_requests = extrair_links_html(
            html=html,
            url_base=url,
            ticker=ticker,
            empresa=empresa,
            ano_inicial=ano_inicial,
        )

        print(
            "Documentos encontrados sem navegador: "
            f"{len(documentos_requests)}"
        )

    except Exception as erro:
        print(
            f"Aviso: falha na leitura HTTP de {ticker}: {erro}",
            file=sys.stderr,
        )

    if documentos_requests and not usar_playwright:
        return documentos_requests

    if not usar_playwright:
        return documentos_requests

    try:
        resposta_playwright = obter_html_playwright_resultado(url)
        html_renderizado = resposta_playwright.html

        if diagnostico_ri:
            dados = diagnostico_html(
                html_renderizado,
                resposta_playwright.url_final,
            )
            dados["network_items_relevantes"] = len(
                resposta_playwright.network_items
            )
            dados["network_pdf"] = sum(
                1
                for item in resposta_playwright.network_items
                if "application/pdf" in str(item.get("content_type", "")).lower()
                or ".pdf" in str(item.get("url", "")).lower()
            )
            imprimir_diagnostico(ticker, "playwright", dados)
            for item in resposta_playwright.network_items[:30]:
                print(
                    "[diagnostico-ri] "
                    f"{ticker} | network | {item.get('method')} "
                    f"{item.get('status')} | {item.get('content_type')} | "
                    f"{item.get('url')}"
                )
            salvar_snapshot_diagnostico(ticker, "playwright", html_renderizado)

        documentos_renderizados = extrair_links_html(
            html=html_renderizado,
            url_base=url,
            ticker=ticker,
            empresa=empresa,
            ano_inicial=ano_inicial,
        )
        documentos_network = documentos_de_network(
            resposta_playwright.network_items,
            ticker=ticker,
            empresa=empresa,
            ano_inicial=ano_inicial,
            url_origem=url,
        )

        combinados = {
            documento.url_documento: documento
            for documento in (
                documentos_requests
                + documentos_renderizados
                + documentos_network
            )
        }

        resultado = list(combinados.values())

        print(
            "Documentos após renderização: "
            f"{len(resultado)}"
        )

        return resultado

    except PlaywrightIndisponivel as erro:
        erro.documentos = documentos_requests
        raise

    except Exception as erro:
        print(
            f"Aviso: falha na renderização de {ticker}: {erro}",
            file=sys.stderr,
        )

        return documentos_requests


# ============================================================
# DOWNLOAD
# ============================================================

def nome_arquivo_documento(
    documento: DocumentoEncontrado,
) -> str:
    return (
        f"{documento.ticker}_"
        f"{documento.periodo}_"
        f"{documento.tipo}.pdf"
    )


def conteudo_e_pdf(
    resposta: requests.Response,
) -> bool:
    content_type = resposta.headers.get(
        "Content-Type",
        "",
    ).lower()

    conteudo = resposta.content

    return (
        "application/pdf" in content_type
        or conteudo.startswith(b"%PDF")
    )


def baixar_documento(
    documento: DocumentoEncontrado,
    sessao: requests.Session,
    sobrescrever: bool,
) -> DownloadRealizado | None:
    garantir_pastas_padrao()

    nome_arquivo = nome_arquivo_documento(documento)
    destino = PASTA_ENTRADA_PADRAO / nome_arquivo

    if destino.exists() and not sobrescrever:
        return DownloadRealizado(
            **asdict(documento),
            arquivo_local=str(destino.resolve()),
            nome_arquivo=nome_arquivo,
            sha256=calcular_sha256(destino),
            baixado_em=datetime.now().astimezone().isoformat(),
            status="ja_existente",
        )

    resposta = sessao.get(
        documento.url_documento,
        timeout=TIMEOUT_REQUISICAO,
        allow_redirects=True,
        headers={
            "Referer": documento.url_origem,
        },
    )
    resposta.raise_for_status()

    if not conteudo_e_pdf(resposta):
        raise ValueError(
            "O endereço não retornou um PDF. "
            f"Content-Type: {resposta.headers.get('Content-Type')}"
        )

    arquivo_temporario = destino.with_suffix(".pdf.part")
    arquivo_temporario.write_bytes(resposta.content)

    validar_pdf(arquivo_temporario)
    arquivo_temporario.replace(destino)

    return DownloadRealizado(
        **asdict(documento),
        arquivo_local=str(destino.resolve()),
        nome_arquivo=nome_arquivo,
        sha256=calcular_sha256(destino),
        baixado_em=datetime.now().astimezone().isoformat(),
        status="baixado",
    )


def salvar_manifesto_downloads(
    registros: list[DownloadRealizado],
) -> None:
    existente: list[dict[str, Any]] = []

    if ARQUIVO_MANIFESTO_DOWNLOADS.exists():
        try:
            existente = json.loads(
                ARQUIVO_MANIFESTO_DOWNLOADS.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            existente = []

    por_chave: dict[tuple[str, str, str], dict[str, Any]] = {}

    for item in existente:
        chave = (
            str(item.get("ticker", "")),
            str(item.get("periodo", "")),
            str(item.get("tipo", "")),
        )
        por_chave[chave] = item

    for registro in registros:
        item = asdict(registro)
        chave = (
            registro.ticker,
            registro.periodo,
            registro.tipo,
        )
        por_chave[chave] = item

    dados = sorted(
        por_chave.values(),
        key=lambda item: (
            item.get("ticker", ""),
            item.get("ano", 0),
            item.get("periodo", ""),
            item.get("tipo", ""),
        ),
    )

    ARQUIVO_MANIFESTO_DOWNLOADS.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def baixar_documentos_ri(
    ano_inicial: int,
    tickers: set[str] | None,
    usar_playwright: bool,
    sobrescrever: bool,
    diagnostico_ri: bool = False,
) -> list[DownloadRealizado]:
    sessao = criar_sessao_http()
    registros: list[DownloadRealizado] = []

    empresas_selecionadas = {
        ticker: configuracao
        for ticker, configuracao in EMPRESAS.items()
        if not tickers or ticker in tickers
    }

    for ticker, configuracao in empresas_selecionadas.items():
        try:
            documentos = coletar_documentos_empresa(
                ticker=ticker,
                configuracao=configuracao,
                sessao=sessao,
                ano_inicial=ano_inicial,
                usar_playwright=usar_playwright,
                diagnostico_ri=diagnostico_ri,
            )
        except PlaywrightIndisponivel as erro:
            print(
                f"Aviso: {erro}",
                file=sys.stderr,
            )
            print(
                "Playwright serÃ¡ ignorado no restante desta execuÃ§Ã£o.",
                file=sys.stderr,
            )
            usar_playwright = False
            documentos = list(erro.documentos)

        # Evita múltiplos arquivos para a mesma combinação.
        por_chave: dict[tuple[str, str], DocumentoEncontrado] = {}

        for documento in documentos:
            chave = (
                documento.periodo,
                documento.tipo,
            )
            por_chave.setdefault(chave, documento)

        for documento in sorted(
            por_chave.values(),
            key=lambda item: (
                item.ano,
                item.periodo,
                item.tipo,
            ),
        ):
            try:
                registro = baixar_documento(
                    documento=documento,
                    sessao=sessao,
                    sobrescrever=sobrescrever,
                )

                if registro:
                    registros.append(registro)
                    print(
                        f"  [{registro.status}] "
                        f"{registro.nome_arquivo}"
                    )

            except Exception as erro:
                print(
                    "  [erro] "
                    f"{documento.ticker} "
                    f"{documento.periodo} "
                    f"{documento.tipo}: {erro}",
                    file=sys.stderr,
                )

            time.sleep(INTERVALO_ENTRE_DOWNLOADS)

    salvar_manifesto_downloads(registros)
    if not registros:
        afetados = ", ".join(sorted(empresas_selecionadas))
        print(
            "0 documentos encontrados nos sites de RI. "
            f"Tickers afetados: {afetados}",
            file=sys.stderr,
        )
    return registros


# ============================================================
# PARSER PDF -> MARKDOWN
# ============================================================

def listar_pdfs_entrada() -> list[Path]:
    garantir_pastas_padrao()

    return sorted(
        arquivo.resolve()
        for arquivo in PASTA_ENTRADA_PADRAO.glob("*.pdf")
        if arquivo.is_file()
    )


def validar_pdf(caminho_pdf: Path) -> None:
    if not caminho_pdf.exists():
        raise FileNotFoundError(
            f"O arquivo não foi encontrado: {caminho_pdf}"
        )

    if not caminho_pdf.is_file():
        raise ValueError(
            f"O caminho informado não é um arquivo: {caminho_pdf}"
        )

    # Arquivos temporários terminam em .pdf.part.
    if not (
        caminho_pdf.name.lower().endswith(".pdf")
        or caminho_pdf.name.lower().endswith(".pdf.part")
    ):
        raise ValueError(
            f"O arquivo precisa ser PDF: {caminho_pdf.name}"
        )

    try:
        with pymupdf.open(str(caminho_pdf)) as documento:
            if documento.page_count <= 0:
                raise ValueError("O PDF não possui páginas.")
    except Exception as erro:
        raise ValueError(
            f"Não foi possível abrir o PDF: {erro}"
        ) from erro


def obter_metadados_pdf(
    caminho_pdf: Path,
) -> dict[str, Any]:
    with pymupdf.open(str(caminho_pdf)) as documento:
        metadados = documento.metadata or {}

        return {
            "arquivo": caminho_pdf.name,
            "caminho_original": str(caminho_pdf.resolve()),
            "numero_paginas": documento.page_count,
            "titulo": metadados.get("title") or None,
            "autor": metadados.get("author") or None,
            "assunto": metadados.get("subject") or None,
            "criador": metadados.get("creator") or None,
            "produtor": metadados.get("producer") or None,
            "palavras_chave": metadados.get("keywords") or None,
        }


def extrair_catalogacao_nome(
    caminho_pdf: Path,
) -> dict[str, str | None]:
    padrao = re.fullmatch(
        (
            r"(?P<ticker>[A-Z]{4}\d)_"
            r"(?P<periodo>[1-4]T\d{2})_"
            r"(?P<tipo>[A-Z_]+)"
        ),
        caminho_pdf.stem,
    )

    if not padrao:
        return {
            "ticker": None,
            "periodo": None,
            "tipo_documento": None,
        }

    return {
        "ticker": padrao.group("ticker"),
        "periodo": padrao.group("periodo"),
        "tipo_documento": padrao.group("tipo"),
    }


def criar_cabecalho_markdown(
    caminho_pdf: Path,
    catalogacao: dict[str, str | None],
) -> str:
    nome_pdf = caminho_pdf.name.replace('"', '\\"')

    linhas = [
        "---",
        f'arquivo_origem: "{nome_pdf}"',
        'formato_origem: "PDF"',
        'formato_destino: "Markdown"',
    ]

    for chave in ("ticker", "periodo", "tipo_documento"):
        valor = catalogacao.get(chave)

        if valor:
            linhas.append(f'{chave}: "{valor}"')

    linhas.extend(
        [
            "---",
            "",
            f"# {caminho_pdf.stem}",
            "",
        ]
    )

    return "\n".join(linhas)


def extrair_imagens_pdf(
    caminho_pdf: Path,
    pasta_imagens: Path,
    nome_documento: str,
    largura_minima: int = 100,
    altura_minima: int = 100,
) -> list[dict[str, Any]]:
    pasta_imagens.mkdir(parents=True, exist_ok=True)
    imagens_extraidas: list[dict[str, Any]] = []

    with pymupdf.open(str(caminho_pdf)) as documento:
        for numero_pagina, pagina in enumerate(
            documento,
            start=1,
        ):
            imagens_pagina = pagina.get_images(full=True)
            imagens_processadas: set[int] = set()

            for numero_imagem, imagem in enumerate(
                imagens_pagina,
                start=1,
            ):
                xref = imagem[0]

                if xref in imagens_processadas:
                    continue

                imagens_processadas.add(xref)

                try:
                    dados_imagem = documento.extract_image(xref)

                    if not dados_imagem:
                        continue

                    conteudo = dados_imagem.get("image")
                    largura = int(dados_imagem.get("width", 0))
                    altura = int(dados_imagem.get("height", 0))

                    if (
                        not conteudo
                        or largura < largura_minima
                        or altura < altura_minima
                    ):
                        continue

                    extensao = (
                        dados_imagem.get("ext")
                        or "png"
                    ).lower()

                    nome_arquivo = (
                        f"{nome_documento}"
                        f"_pagina_{numero_pagina:04d}"
                        f"_imagem_{numero_imagem:02d}"
                        f".{extensao}"
                    )

                    caminho_imagem = pasta_imagens / nome_arquivo
                    caminho_imagem.write_bytes(conteudo)

                    imagens_extraidas.append(
                        {
                            "pagina": numero_pagina,
                            "numero_imagem": numero_imagem,
                            "xref": xref,
                            "arquivo": nome_arquivo,
                            "caminho": str(
                                caminho_imagem.resolve()
                            ),
                            "largura": largura,
                            "altura": altura,
                            "extensao": extensao,
                        }
                    )

                except Exception as erro:
                    print(
                        "Aviso: não foi possível extrair "
                        f"a imagem {numero_imagem} "
                        f"da página {numero_pagina}: {erro}",
                        file=sys.stderr,
                    )

    return imagens_extraidas


def criar_secao_imagens_markdown(
    imagens: list[dict[str, Any]],
) -> str:
    if not imagens:
        return (
            "\n\n---\n\n"
            "## Imagens extraídas\n\n"
            "Nenhuma imagem incorporada foi encontrada no PDF.\n"
        )

    imagens_por_pagina: dict[int, list[dict[str, Any]]] = {}

    for imagem in imagens:
        pagina = int(imagem["pagina"])
        imagens_por_pagina.setdefault(pagina, []).append(imagem)

    partes = [
        "\n\n---\n\n",
        "## Imagens extraídas\n\n",
    ]

    for pagina in sorted(imagens_por_pagina):
        partes.append(f"### Página {pagina}\n\n")

        for imagem in imagens_por_pagina[pagina]:
            arquivo = imagem["arquivo"]
            largura = imagem["largura"]
            altura = imagem["altura"]

            partes.append(
                f"![Imagem da página {pagina}]"
                f"(images/{arquivo})\n\n"
            )
            partes.append(
                f"*Dimensões: {largura} × {altura} pixels.*\n\n"
            )

    return "".join(partes)


def converter_pdf_para_markdown(
    caminho_pdf: str | Path,
    diretorio_saida: str | Path | None = None,
    idioma_ocr: str = "por+eng",
    forcar_ocr: bool = False,
    extrair_imagens: bool = True,
    estrategia_tabelas: str = "lines_strict",
    mostrar_progresso: bool = True,
    largura_minima_imagem: int = 100,
    altura_minima_imagem: int = 100,
) -> dict[str, Any]:
    pdf = Path(caminho_pdf).expanduser().resolve()
    validar_pdf(pdf)

    pasta_base_saida = (
        PASTA_SAIDA_PADRAO.resolve()
        if diretorio_saida is None
        else Path(diretorio_saida).expanduser().resolve()
    )

    pasta_base_saida.mkdir(parents=True, exist_ok=True)

    catalogacao = extrair_catalogacao_nome(pdf)
    nome_documento = normalizar_nome_arquivo(pdf.stem)

    # A saída começa pelo ticker para facilitar o consumo posterior.
    ticker = catalogacao.get("ticker")
    periodo = catalogacao.get("periodo")
    tipo = catalogacao.get("tipo_documento")

    if ticker and periodo and tipo:
        nome_catalogado = f"{ticker}_{periodo}_{tipo}"
    else:
        nome_catalogado = nome_documento

    pasta_saida = (
        pasta_base_saida
        / nome_catalogado
    ).resolve()

    pasta_imagens = (pasta_saida / "images").resolve()
    arquivo_markdown = (
        pasta_saida / f"{nome_catalogado}.md"
    ).resolve()
    arquivo_metadados = (
        pasta_saida / f"{nome_catalogado}_metadata.json"
    ).resolve()

    pasta_saida.mkdir(parents=True, exist_ok=True)

    if extrair_imagens:
        pasta_imagens.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 70)
    print(f"PDF de entrada: {pdf}")
    print(f"Pasta de saída: {pasta_saida}")
    print(f"Markdown: {arquivo_markdown}")
    print("=" * 70)

    funcao_use_layout = getattr(
        pymupdf4llm,
        "use_layout",
        None,
    )

    if callable(funcao_use_layout):
        try:
            funcao_use_layout(False)
        except Exception:
            pass

    parametros_markdown: dict[str, Any] = {
        "use_ocr": True,
        "force_ocr": forcar_ocr,
        "ocr_language": idioma_ocr,
        "ocr_dpi": 300,
        "table_strategy": estrategia_tabelas,
        "show_progress": mostrar_progresso,
        "page_separators": True,
        "write_images": False,
        "ignore_images": True,
    }

    try:
        conteudo_markdown = pymupdf4llm.to_markdown(
            str(pdf),
            **parametros_markdown,
        )
    except Exception as erro:
        raise RuntimeError(
            "Erro durante a conversão de texto e tabelas.\n"
            f"PDF: {pdf}\n"
            f"Erro original: {erro}"
        ) from erro

    if not isinstance(conteudo_markdown, str):
        raise TypeError(
            "O PyMuPDF4LLM não retornou uma string Markdown."
        )

    imagens_extraidas: list[dict[str, Any]] = []

    if extrair_imagens:
        imagens_extraidas = extrair_imagens_pdf(
            caminho_pdf=pdf,
            pasta_imagens=pasta_imagens,
            nome_documento=nome_catalogado,
            largura_minima=largura_minima_imagem,
            altura_minima=altura_minima_imagem,
        )

    cabecalho = criar_cabecalho_markdown(
        pdf,
        catalogacao,
    )

    secao_imagens = (
        criar_secao_imagens_markdown(imagens_extraidas)
        if extrair_imagens
        else ""
    )

    arquivo_markdown.write_text(
        cabecalho + conteudo_markdown + secao_imagens,
        encoding="utf-8",
    )

    metadados = obter_metadados_pdf(pdf)
    metadados.update(catalogacao)
    metadados.update(
        {
            "nome_documento_normalizado": nome_catalogado,
            "arquivo_markdown": str(arquivo_markdown),
            "pasta_saida": str(pasta_saida),
            "pasta_imagens": (
                str(pasta_imagens)
                if extrair_imagens
                else None
            ),
            "extracao_imagens": extrair_imagens,
            "quantidade_imagens": len(imagens_extraidas),
            "imagens": imagens_extraidas,
            "ocr_habilitado": True,
            "ocr_forcado": forcar_ocr,
            "idioma_ocr": idioma_ocr,
            "estrategia_tabelas": estrategia_tabelas,
        }
    )

    arquivo_metadados.write_text(
        json.dumps(
            metadados,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "markdown": str(arquivo_markdown),
        "metadados": str(arquivo_metadados),
        "imagens": (
            str(pasta_imagens)
            if extrair_imagens
            else ""
        ),
        "quantidade_imagens": len(imagens_extraidas),
    }


# ============================================================
# ARGUMENTOS E EXECUÇÃO
# ============================================================

def criar_parser_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa documentos trimestrais dos sites de RI e "
            "converte PDFs para Markdown."
        )
    )

    parser.add_argument(
        "pdf",
        nargs="?",
        default=None,
        help=(
            "PDF específico. Quando omitido, os PDFs da pasta "
            "de entrada são processados."
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Pasta de saída dos arquivos Markdown.",
    )

    parser.add_argument(
        "--ano-inicial",
        type=int,
        default=ANO_INICIAL_PADRAO,
        help=(
            "Primeiro ano a baixar. Padrão: "
            f"{ANO_INICIAL_PADRAO}."
        ),
    )

    parser.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help=(
            "Tickers específicos. Exemplo: "
            "--tickers RDOR3 FLRY3."
        ),
    )

    parser.add_argument(
        "--somente-download",
        action="store_true",
        help="Baixa os PDFs, mas não executa o parser.",
    )

    parser.add_argument(
        "--sem-download",
        action="store_true",
        help=(
            "Não consulta os sites de RI; processa apenas "
            "os PDFs já existentes."
        ),
    )

    parser.add_argument(
        "--sem-playwright",
        action="store_true",
        help=(
            "Não usa navegador para páginas dinâmicas. "
            "Pode reduzir a quantidade de documentos encontrados."
        ),
    )
    parser.add_argument("--sector", choices=("saude", "construcao_civil"), default="saude")

    parser.add_argument(
        "--diagnostico-ri",
        action="store_true",
        help=(
            "Registra diagnostico controlado da descoberta de documentos "
            "nos sites de RI e salva snapshots HTML em diagnostico_ri/."
        ),
    )

    parser.add_argument(
        "--sobrescrever-downloads",
        action="store_true",
        help="Baixa novamente documentos já existentes.",
    )

    parser.add_argument(
        "--ocr-language",
        default="por+eng",
    )

    parser.add_argument(
        "--force-ocr",
        action="store_true",
    )

    parser.add_argument(
        "--no-images",
        action="store_true",
    )

    parser.add_argument(
        "--table-strategy",
        choices=["lines_strict", "lines", "text"],
        default="lines_strict",
    )

    parser.add_argument(
        "--no-progress",
        action="store_true",
    )

    parser.add_argument(
        "--min-image-width",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--min-image-height",
        type=int,
        default=100,
    )

    return parser


def main() -> int:
    parser = criar_parser_argumentos()
    argumentos = parser.parse_args()

    garantir_pastas_padrao()

    tickers = (
        {ticker.upper() for ticker in argumentos.tickers}
        if argumentos.tickers
        else None
    )

    if tickers:
        invalidos = tickers - set(EMPRESAS)

        if invalidos:
            print(
                "Tickers inválidos: "
                + ", ".join(sorted(invalidos)),
                file=sys.stderr,
            )
            return 1

    if not argumentos.sem_download and not argumentos.pdf:
        print("\nINICIANDO DOWNLOAD DOS SITES DE RI")

        registros = baixar_documentos_ri(
            ano_inicial=argumentos.ano_inicial,
            tickers=tickers,
            usar_playwright=not argumentos.sem_playwright,
            sobrescrever=argumentos.sobrescrever_downloads,
            diagnostico_ri=argumentos.diagnostico_ri,
        )

        print(
            "\nDownloads identificados/concluídos: "
            f"{len(registros)}"
        )
        print(
            f"Manifesto: {ARQUIVO_MANIFESTO_DOWNLOADS}"
        )

    if argumentos.somente_download:
        return 0

    if argumentos.pdf:
        pdfs = [
            Path(argumentos.pdf).expanduser().resolve()
        ]
    else:
        pdfs = listar_pdfs_entrada()

        if tickers:
            pdfs = [
                pdf
                for pdf in pdfs
                if pdf.name.split("_", 1)[0] in tickers
            ]

    if not pdfs:
        print(
            "Nenhum PDF disponível para processamento em:\n"
            f"{PASTA_ENTRADA_PADRAO}",
            file=sys.stderr,
        )
        return 1

    sucessos = 0
    erros = 0

    for pdf in pdfs:
        try:
            resultado = converter_pdf_para_markdown(
                caminho_pdf=pdf,
                diretorio_saida=argumentos.output,
                idioma_ocr=argumentos.ocr_language,
                forcar_ocr=argumentos.force_ocr,
                extrair_imagens=not argumentos.no_images,
                estrategia_tabelas=argumentos.table_strategy,
                mostrar_progresso=not argumentos.no_progress,
                largura_minima_imagem=argumentos.min_image_width,
                altura_minima_imagem=argumentos.min_image_height,
            )

            sucessos += 1

            print("\nConversão concluída.")
            print(f"Markdown: {resultado['markdown']}")
            print(f"Metadados: {resultado['metadados']}")

        except Exception as erro:
            erros += 1
            print(
                f"\nErro ao processar '{pdf.name}': {erro}",
                file=sys.stderr,
            )

    print()
    print("=" * 70)
    print("RESUMO")
    print(f"PDFs processados: {len(pdfs)}")
    print(f"Sucessos: {sucessos}")
    print(f"Erros: {erros}")
    print("=" * 70)

    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())

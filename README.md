# Nerias RI Tracker V2

## Objetivo

O Nerias RI Tracker V2, ou Acompanhador de Mercado, consolida demonstrativos financeiros CVM, cotações de mercado e dados operacionais de RI para acompanhar AALR3, DASA3, FLRY3, HAPV3, MATD3, ONCO3 e RDOR3.

## Arquitetura

CVM, Yahoo Finance e sites de RI alimentam scripts de extração. Esses scripts geram JSONs locais em `resultados/`, calculam indicadores e expõem os dados no dashboard Flask.

Fluxo principal:

```text
CVM + Yahoo Finance + sites de RI
-> extracao
-> JSONs
-> indicadores
-> dashboard Flask
```

## Requisitos

Use Python 3.11 ou superior. O projeto usa tipagem moderna, `from __future__ import annotations`, unions com `|` e `zoneinfo`.

Dependências Python:

```bash
pip install -r requirements.txt
```

O parser operacional pode usar Playwright/Chromium para páginas de RI dinâmicas. Quando esse recurso for necessário:

```bash
python -m playwright install chromium
```

Se o Chromium não estiver instalado, o código mantém fallback/erro controlado e a opção `--sem-playwright` continua disponível.

## Instalação local

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Execução local

Para abrir o dashboard usando os JSONs já existentes:

```bash
python dashboard.py
```

Por padrão, o dashboard sobe em `127.0.0.1:8050`. É possível alterar:

```bash
python dashboard.py --host 0.0.0.0 --port 8050
```

Em ambiente cloud, se a variável `PORT` existir, ela é usada quando `--port` não for informado.

## Atualização completa

Para baixar novamente os dados e recalcular o pipeline antes de iniciar o dashboard:

```bash
python dashboard.py --atualizar
```

Também existe um botão no dashboard para executar a atualização completa em uma thread.

## Exportação HTML

Para gerar uma versão HTML estática compartilhável:

```bash
python dashboard.py --export-html acompanhador_de_mercado.html
```

## Estrutura Principal

- `app_balancos.py`: extrai BP a partir de ITR/DFP CVM.
- `app_dre.py`: extrai DRE a partir de ITR/DFP CVM.
- `app_dfc.py`: extrai DFC a partir de ITR/DFP CVM.
- `app_parser_operacional.py`: baixa releases/relatórios de RI e converte PDFs para Markdown.
- `app_extrator_operacional.py`: extrai KPIs operacionais dos documentos baixados.
- `app_divida_liquida.py`: calcula dívida líquida a partir do BP.
- `app_ciclo_financeiro.py`: calcula ciclo financeiro a partir do BP e DRE.
- `app_market_cap.py`: calcula market cap atual.
- `app_market_cap_historico.py`: calcula market cap histórico.
- `app_indicadores.py`: calcula indicadores financeiros derivados.
- `app_reconciliacao.py`: gera relatório técnico de reconciliação.
- `metric_definitions.py`: centraliza definições metodológicas e regras por companhia.
- `dashboard.py`: aplicação Flask e exportação HTML.
- `wsgi.py`: entrypoint WSGI para produção.

## Dados Não Versionados

Os seguintes itens são gerados em runtime e não entram no Git:

- `resultados/`;
- downloads CVM;
- ZIPs;
- PDFs;
- planilhas baixadas;
- Markdown e imagens gerados de releases;
- temporários;
- HTMLs estáticos exportados.

O código cria diretórios de saída quando necessário. Em cloud, o filesystem pode ser efêmero; para persistência durável será necessário configurar storage externo em uma etapa futura.

## Segurança

Não versionar `.env`, chaves, tokens ou credenciais. Caso alguma integração futura exija segredo, ler por variável de ambiente com `os.getenv` e documentar apenas o nome da variável, nunca o valor.

URLs públicas da CVM, Yahoo Finance e RI são fontes públicas e não são segredos.

## Deploy

A aplicação é Flask e pode ser importada via WSGI:

```bash
gunicorn wsgi:app
```

Para deploy em Linux/cloud, defina a porta pela variável `PORT` ou pelo comando do provedor. Se quiser apontar para uma pasta de resultados fora da raiz do projeto, use opcionalmente `NERIAS_RESULTADOS_DIR`.

Playwright pode exigir instalação do navegador Chromium no build do ambiente. Não há instalação automática de navegador na inicialização da aplicação.

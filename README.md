# Nerias RI Tracker V2

## Objetivo

O Nerias RI Tracker V2, ou Acompanhador de Mercado, consolida demonstrativos financeiros CVM, cotacoes de mercado e dados operacionais de RI para acompanhar AALR3, DASA3, FLRY3, HAPV3, MATD3, ONCO3 e RDOR3.

O tracker também atende construção civil: AVLL3, CALI3, CURY3, CYRE3, DIRR3,
EVEN3, EZTC3, FIEI3, GFSA3, HBOR3, INNC3, JFEN3, JHSF3, LAVV3, MDNE3,
MELK3, MRVE3, MTRE3, PDGR3, PLPL3, RDNI3, RSID3, TCSA3, TEND3, TRIS3 e
VIVR3. O cadastro auditável está centralizado em `company_registry.py`.
INNC3 e o ticker atual da INC Empreendimentos; INNT3 e mantido como ticker
historico/compatibilidade para consultas e leitura de dados legados.
Construção civil usa somente dados financeiros; não há indicadores ou
overrides operacionais nesse setor.

```bash
python update_data.py --sector saude --scope all --mode incremental
python update_data.py --sector construcao_civil --scope financial --mode full
python update_data.py --sector all --scope financial --mode incremental
python -m data_publication validate resultados --sector saude --scope financial
python -m data_publication publish resultados data-repo/data --sector saude --scope financial
python dashboard.py --export-html painel.html --sector construcao_civil
```

Sem `--sector`, o padrão retrocompatível é `saude`. A combinação construção +
operacional é rejeitada; construção + tudo executa apenas financeiro com aviso;
e todos + operacional executa apenas saúde. Publicações setoriais usam manifesto
v2, `data/sectors/<setor>/` e `charts/<setor>/`. O formato plano anterior é
somente fallback de leitura e representa saúde. A publicação substitui apenas a
interseção setor × componente e preserva os demais snapshots e overrides.

## Metodologia dos agregados setoriais

O market cap setorial usa apenas empresas ativas do setor selecionado com
market cap valido, positivo e numerico. A participacao de cada empresa e:
`market_cap_empresa / soma_market_cap_empresas_validas`. Empresas sem dado
valido sao excluidas e reportadas no diagnostico; ausencias nao viram zero.

O EV/EBITDA setorial e calculado pela divisao do enterprise value agregado pelo
EBITDA LTM agregado das empresas incluidas. Nao representa uma media simples ou
ponderada dos multiplos individuais. A formula e `soma(EV) / soma(EBITDA LTM)`,
com EV definido pela metodologia vigente como `market cap historico + divida
liquida padronizada`. EBITDAs negativos validos entram na soma agregada; se o
EBITDA LTM agregado for menor ou igual a zero, o multiplo fica nulo e o
diagnostico explicita a causa.

Os retornos setoriais de preco de 30 e 360 dias usam fechamento nao ajustado,
coerente com o market cap historico. Para cada empresa, o retorno e
`preco_final / preco_inicial - 1`, usando o fechamento do proprio dia ou o
ultimo pregao anterior disponivel. A ponderacao setorial usa o market cap do
inicio do intervalo: `preco_inicial x quantidade historica de acoes em ou antes
da data inicial`. A cobertura minima inicial e 70%; abaixo dela, o retorno
setorial nao e publicado como representativo.

Todos os agregados registram metodologia, empresas incluidas, empresas
excluidas, cobertura, datas efetivas dos componentes e limitacoes de dados
historicos.

## Cache CVM e workflows sem coleta

Os ZIPs brutos da CVM ficam em `resultados/<setor>/downloads/<itr|dfp>/`,
separados por tipo de documento e ano. O workflow principal restaura esse
diretorio via GitHub Actions cache; como o cache do GitHub e imutavel por chave
e nao e permanente, a chave inclui setor, politica de refresh e run id, com
restore por prefixo. Anos historicos podem ser reutilizados, mas nao sao
tratados como imutaveis para sempre.

A politica `--refresh-cvm-files` aceita:

- `auto`: usa ZIP local valido; quando nao houver base valida, tenta baixar. Se
  uma consulta externa falhar e houver cache valido, reutiliza o cache com
  diagnostico de fallback.
- `force`: exige novo download validado antes de substituir o ZIP anterior. Se
  falhar, preserva a copia valida antiga e falha a execucao.
- `never`: nao faz chamada externa; exige ZIPs persistidos validos.

Downloads sao atomicos: baixam para arquivo temporario, validam tamanho minimo,
assinatura ZIP e CSVs esperados, calculam checksum e so entao substituem o
destino. O diagnostico estruturado fica em
`resultados/<setor>/downloads/cvm_download_events.json`.

Os workflows manuais sem coleta sao:

- `Recalcular indicadores`: recalcula derivados usando snapshots ja persistidos.
- `Recriar graficos`: recria PNGs e manifests a partir dos JSONs existentes.
- `Reconstruir dashboard - sem coleta`: recompõe derivados, graficos e manifests
  sem consultar CVM, RI ou Yahoo.

Nesses workflows `EXTERNAL_FETCH_ENABLED=false` documenta e protege a intencao:
se faltar dado bruto, a rotina reporta dependencia ausente em vez de buscar
externamente. `publish=false` gera artefatos para inspecao e nao altera o
repositorio de dados.

## Arquitetura

CVM, Yahoo Finance e sites de RI alimentam scripts de extracao. Esses scripts geram JSONs locais em `resultados/`, calculam indicadores e expoem os dados no dashboard Flask.

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

Dependencias Python:

```bash
pip install -r requirements.txt
```

O parser operacional pode usar Playwright/Chromium para paginas de RI dinamicas. Quando esse recurso for necessario:

```bash
python -m playwright install chromium
```

Se o Chromium nao estiver instalado, o codigo mantem fallback/erro controlado e a opcao `--sem-playwright` continua disponivel.

## Instalacao local

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

## Execucao local

Para abrir o dashboard usando os JSONs ja existentes:

```bash
python dashboard.py
```

Por padrao, o dashboard sobe em `127.0.0.1:8050`. E possivel alterar:

```bash
python dashboard.py --host 0.0.0.0 --port 8050
```

Em ambiente cloud, se a variavel `PORT` existir, ela e usada quando `--port` nao for informado.

## Atualizacao completa

Para baixar novamente os dados e recalcular o pipeline antes de iniciar o dashboard:

```bash
python dashboard.py --atualizar
```

Tambem existe um botao no dashboard para executar a atualizacao completa em uma thread.

## Modos de atualizacao

O `update_data.py` aceita dois modos:

- `incremental`: modo padrao. Reutiliza arquivos/downloads existentes quando os modulos ja suportam isso e recalcula os outputs finais.
- `full`: preserva o comportamento historico de reconstrucao completa, forcando redownload/reprocessamento nos modulos que possuem flags para isso.

Exemplos:

```bash
python update_data.py --mode incremental
python update_data.py --mode full
```

No GitHub Actions, o modo e escolhido no botao `Run workflow`.

## Resiliencia da atualizacao

Falhas na coleta operacional de RI nao bloqueiam a atualizacao financeira. Se o parser ou o extrator operacional falhar, o pipeline termina com warnings, continua recalculando os dados financeiros e preserva o ultimo snapshot operacional valido ja publicado.

Falhas financeiras continuam bloqueantes: BP, DRE, DFC, divida liquida, ciclo financeiro, market cap, indicadores e reconciliacao precisam concluir com sucesso para permitir publicacao.

## Arquitetura de dados em producao

Em producao, a separacao recomendada e:

```text
GitHub Actions -> gera JSONs
ri-tracker-data -> publica JSONs em data/
Render -> consome JSONs publicados via HTTPS
```

O dashboard aceita tres modos de fonte pela variavel `NERIAS_DATA_SOURCE`:

- `local`: le os JSONs em `resultados/`.
- `remote`: le os JSONs publicos de `ri-tracker-data`.
- `auto`: tenta remoto, usa cache remoto anterior se houver falha, depois tenta local e, por fim, exibe estado sem dados.

Default: `auto`.

Variaveis uteis para Render:

```text
NERIAS_DATA_SOURCE=remote
NERIAS_REMOTE_DATA_BASE_URL=https://raw.githubusercontent.com/pedroatnerias/ri-tracker-data/main/data
NERIAS_REMOTE_CACHE_TTL_SECONDS=600
```

O cache remoto fica em memoria no processo Flask/Gunicorn. O endpoint `POST /api/refresh-data` invalida esse cache e recarrega os JSONs publicados, sem executar ETL e sem usar token GitHub.

## Atualizacao de dados via GitHub Actions

O pipeline pesado deve ser executado manualmente no GitHub Actions, nao no Render Free.

1. Abra o repositorio privado `pedroatnerias/ri-tracker` no GitHub.
2. Entre na aba `Actions`.
3. Selecione o workflow `Atualizar dados Nerias`.
4. Clique em `Run workflow`.
5. Escolha o modo `incremental` ou `full`.
6. Aguarde a conclusao da execucao.
7. Os JSONs finais validados serao publicados no repositorio publico `pedroatnerias/ri-tracker-data`, dentro da pasta `data/`.

O workflow usa o secret `DATA_REPO_TOKEN` configurado no GitHub. O valor do token nao deve ser exposto em logs, codigo ou documentacao.

## Exportacao HTML

Para gerar uma versao HTML estatica compartilhavel:

```bash
python dashboard.py --export-html acompanhador_de_mercado.html
```

## Estrutura Principal

- `app_balancos.py`: extrai BP a partir de ITR/DFP CVM.
- `app_dre.py`: extrai DRE a partir de ITR/DFP CVM.
- `app_dfc.py`: extrai DFC a partir de ITR/DFP CVM.
- `app_parser_operacional.py`: baixa releases/relatorios de RI e converte PDFs para Markdown.
- `app_extrator_operacional.py`: extrai KPIs operacionais dos documentos baixados.
- `app_divida_liquida.py`: calcula divida liquida a partir do BP.
- `app_ciclo_financeiro.py`: calcula ciclo financeiro a partir do BP e DRE.
- `app_market_cap.py`: calcula market cap atual.
- `app_market_cap_historico.py`: calcula market cap historico.
- `app_indicadores.py`: calcula indicadores financeiros derivados.
- `app_reconciliacao.py`: gera relatorio tecnico de reconciliacao.
- `metric_definitions.py`: centraliza definicoes metodologicas e regras por companhia.
- `dashboard.py`: aplicacao Flask e exportacao HTML.
- `wsgi.py`: entrypoint WSGI para producao.

## Dados Nao Versionados

Os seguintes itens sao gerados em runtime e nao entram no Git:

- `resultados/`;
- downloads CVM;
- ZIPs;
- PDFs;
- planilhas baixadas;
- Markdown e imagens gerados de releases;
- temporarios;
- HTMLs estaticos exportados.

O codigo cria diretorios de saida quando necessario. Em cloud, o filesystem pode ser efemero; para persistencia duravel sera necessario configurar storage externo em uma etapa futura.

## Seguranca

Nao versionar `.env`, chaves, tokens ou credenciais. Caso alguma integracao futura exija segredo, ler por variavel de ambiente com `os.getenv` e documentar apenas o nome da variavel, nunca o valor.

URLs publicas da CVM, Yahoo Finance e RI sao fontes publicas e nao sao segredos.

## Deploy

A aplicacao e Flask e pode ser importada via WSGI:

```bash
gunicorn wsgi:app
```

Para deploy em Linux/cloud, defina a porta pela variavel `PORT` ou pelo comando do provedor. Se quiser apontar para uma pasta de resultados fora da raiz do projeto, use opcionalmente `NERIAS_RESULTADOS_DIR`.

Playwright pode exigir instalacao do navegador Chromium no build do ambiente. Nao ha instalacao automatica de navegador na inicializacao da aplicacao.

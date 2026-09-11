# Diagnóstico de duplicidades e compartimentalização

### Lote 25 executado: matching do ciclo financeiro centralizado

`app_ciclo_financeiro._text` agora delega ao normalizador compartilhado, preservando remoção de acentos, lowercase e matching de descrições. O parser numérico e as regras de ciclo não foram alterados. Testes direcionados: **6 passed**; suíte completa: **207 passed, 43 subtests passed**.

Data: 2026-09-04  
Baseline: `python -m pytest -q` → **196 passed, 43 subtests passed em 8,16s**.

## Método e limitações

Foi feita análise estática com AST dos módulos Python de primeiro nível, busca textual de referências em todo o repositório e leitura dos entrypoints, workflows e testes. A contagem de chamadas diretas por nome é apenas evidência inicial: não detecta imports por alias, chamadas via atributo, Flask routes, CLI, reflexão ou consumidores externos.

Consequentemente, `calls=0` não significa automaticamente código morto. Endpoints, funções exportadas e funções chamadas por `app.run`, decorators ou consumidores externos foram classificados como **órfãos aparentes** até validação adicional.

## Fluxos e grafo de chamadas

### Atualização financeira

```text
update_data.py
  -> pipeline_tasks / módulos app_*
  -> CVM/Yahoo e snapshots locais
  -> app_indicadores / sector_aggregates
  -> chart_generation
  -> data_publication.validate_results
  -> data_publication.publish_validated_data
```

### Operacional

```text
app_parser_operacional.py
  -> operational_sources / coleta requests ou Playwright
  -> manifesto e PDFs/Markdown locais
  -> app_extrator_operacional.py
  -> construction_operational / operational_dictionary
  -> tracking.py
  -> snapshots operacionais
  -> data_publication quality gate
```

### Dashboard

```text
wsgi.py ou dashboard.py
  -> create_app
  -> load_json / load_optional / remote cache
  -> normalização de identidade e métricas
  -> sector_aggregates / payloads de comparação
  -> rotas e HTML/JSON
```

O dashboard concentra carregamento, cache, cálculo, montagem de payload e apresentação no mesmo módulo. Esta é a maior concentração arquitetural observada.

## Matriz de duplicidade e sobreposição

| Área | Evidência | Classificação | Risco | Próximo passo |
|---|---|---|---|---|
| Texto | `normalise_text` em `app_extrator_operacional`, `normalize_text` em `construction_operational`/`app_balancos`, `normalizar_texto` em `app_parser_operacional`, além de normalizadores financeiros | Regras parcialmente sobrepostas, com diferenças de domínio e idioma | Alto | Extrair núcleo compartilhado e manter adapters de domínio |
| Períodos | `normalise_period`, `normalize_period`, `identificar_periodo`, `calcular_periodo`, `period_key` e variantes | Duplicidade funcional com contratos distintos | Alto | Definir tipos/contratos canônicos e preservar parsers de entrada |
| Empresas | `company_registry`, `construction_company_profiles`, `operational_sources`, aliases no dashboard e aliases do parser | Identidade central existe, mas configuração é repetida | Alto | Registry canônico; perfis/fontes somente complementares |
| JSON | `load_json`, `load_optional_json`, `read_json`, `read_existing_json`, `read_json_if_exists` | Duplicidade intencional parcial, sem contrato unificado de erro | Médio | Criar política única de leitura/erro e adapters locais/remotos |
| Validação | `validate_json_file`, validações específicas de market cap, snapshots operacionais, manifestos e quality reports | Camadas diferentes, mas fronteiras pouco explícitas | Alto | Separar validação de entrada, quality gate e publicação |
| Manifestos | `data_manifest_payload`, `build_publish_manifest`, manifests de gráficos, tracking e downloads | Cada manifesto tem objetivo legítimo, mas há campos e reconciliações repetidos | Médio | Definir contratos por tipo e um identificador de execução comum |
| Warnings/erros | `safe_print`, warnings em payload, tracking events, logs do dashboard e exceções CLI | Observabilidade duplicada em formatos diferentes | Médio | Criar evento/diagnóstico estruturado e adaptadores de saída |
| Extração operacional | Parser coleta; extrator processa; `construction_operational` extrai tabelas; funções de planilha continuam disponíveis | Separação correta, com API de planilha legada ainda paralela | Médio | Não remover sem consumidor explícito; marcar como compatibilidade |
| Cálculos setoriais | `sector_aggregates` e transformações de comparação no dashboard | Possível recomputação da mesma informação | Alto | Dashboard deve consumir agregados prontos ou serviço único |

## Funções sem chamadas diretas

### Candidatas a validação de órfão

O AST apontou funções como `extract_workbook_observations`, `calculate_credit_loss_proxy`, `calculate_roe`, `buscar_preco_yfinance`, `all_companies`, `metric_ids`, `sector_dictionary`, `resolve_operational_results_dir`, `load_optional`, `load_remote_optional`, `validate_operational_manifest_consistency` e algumas funções de exportação/compatibilidade.

Nenhuma deve ser removida automaticamente:

- `extract_workbook_observations` é coberta por testes e representa compatibilidade explícita.
- `calculate_credit_loss_proxy` e `calculate_roe` podem ser API de domínio futura; precisam de busca em documentação e consumers externos.
- `all_companies`, `metric_ids`, `sector_dictionary` e funções semelhantes são possíveis APIs públicas.
- Funções Flask como `api_data`, `api_update`, `index`, `logos` e endpoints manuais têm consumidores via rota, não chamadas Python diretas.
- `resolve_operational_results_dir` e funções de carregamento opcional precisam ser comparadas com os fallbacks de caminhos antes de qualquer remoção.

### Órfão confirmado nesta rodada

`discover_latest_operational_pdf` foi confirmado como sem consumidor após a centralização da descoberta no parser e foi removido anteriormente. O teste de regressão confirmou que o extrator permanece offline e que a coleta continua no parser.

## Regras repetidas ou potencialmente conflitantes

- Resolução de ticker ocorre no registry, no parser por nome de arquivo, no extrator por conteúdo e no dashboard ao migrar tickers legados. Isso é necessário em entradas diferentes, mas deve convergir sempre para `canonical_ticker`.
- Leitura de dados aceita formatos `empresas` e `companies` em vários módulos. É compatibilidade necessária, mas deve ficar em uma camada de normalização.
- Validação de existência, schema e qualidade aparece em mais de uma etapa. A repetição é válida somente quando cada etapa tiver objetivo documentado.
- Os módulos financeiros antigos usam helpers em português e os módulos novos usam helpers em inglês; isso é uma fonte de paralelismo semântico e dificulta manutenção.
- `dashboard.py` monta dados diretamente e também consome agregadores, criando risco de cálculo duplicado ou divergente.

## Proposta de compartimentalização futura

1. `domain_identity.py`: `Company`, ticker canônico, aliases e resolução.
2. `domain_normalization.py`: texto, datas, períodos, números, unidades e escalas; adapters preservam nomes antigos.
3. `data_access.py`: leitura local/remota, cache, fallback e schemas de entrada.
4. `operational_pipeline.py`: interfaces para descoberta, parsing, extração, validação, tracking e persistência.
5. `dashboard_services.py`: carregamento, agregados, comparação e payloads; rotas permanecem em `dashboard.py`.
6. `publication_contracts.py`: manifestos, validações de entrada, quality gates e publicação.

As interfaces externas permanecem inalteradas; os módulos atuais passam a delegar gradualmente para os novos serviços.

## Lotes recomendados

### Lote 2 executado: normalização textual compartilhada

Foi criado `domain_normalization.py` como núcleo compartilhado e sem efeitos colaterais para reparo de mojibake e normalização textual. Os nomes públicos existentes continuam funcionando como adapters: `construction_operational.repair_mojibake`, `construction_operational.normalize_text` e `app_extrator_operacional.normalise_text` delegam ao núcleo sem alterar suas interfaces.

O adapter do extrator usa `repair=False` para preservar a semântica anterior. A opção `strip_accents=False` usa NFC para preservar acentos; o padrão usa NFKD e remove diacríticos para matching. Foram adicionados três testes unitários. Resultado após o lote: **199 passed, 43 subtests passed**.

Parsers de período, unidade e valores financeiros permanecem separados neste lote porque suas regras de domínio ainda não são equivalentes o suficiente para substituição segura.

O normalizador textual de `app_balancos.py` também passou a delegar ao mesmo núcleo, mantendo seu adapter em caixa alta e sem reparo automático de mojibake. Os testes financeiros confirmam que o matching de contas permanece equivalente.

### Lote 7 executado: validação de órfãos e contratos de fontes

### Lote 8 executado: normalização de identificadores financeiros

Foi adicionada `domain_normalization.normalize_identifier`. Os adapters `app_dre.normalizar` e `app_indicadores._normalizar` agora usam o mesmo núcleo para remoção de acentos e limpeza alfanumérica, preservando suas diferenças de caixa e regras específicas. Resultado: **202 passed, 43 subtests passed**.

O helper `app_dfc.sem_acentos` também passou a delegar ao núcleo compartilhado, mantendo a regra de caixa alta e espaços. Os testes de DFC/ciclo e a suíte completa permaneceram verdes.

Foi confirmada a classificação dos símbolos com `calls=0`: endpoints Flask, APIs exportadas, helpers de compatibilidade e funções cobertas por testes não são código morto. O cadastro financeiro local agora usa o registry canônico e `operational_sources` possui validação automática contra o mesmo registry. Nenhum símbolo público foi removido por análise estática isolada.

### Lote 5 executado: identidade financeira canônica

O cadastro financeiro duplicado de `app_balancos.py` foi substituído por `financial_companies("saude")` do `company_registry.py`. O nome local `COMPANIES` permanece como adapter para o pipeline existente, evitando alteração dos consumidores. O teste financeiro direcionado passou com **15 passed, 33 subtests passed**, e a suíte completa com **201 passed, 43 subtests passed**.

### Lote 6 executado: contrato de fontes operacionais

`operational_sources.py` agora valida automaticamente seu universo contra `company_registry.py`, incluindo ticker, nome societário e tickers legados. Isso preserva URLs e políticas de coleta locais, mas impede divergência silenciosa de identidade. Foi adicionado teste de contrato; a suíte completa passou com **202 passed, 43 subtests passed**.

### Estado da próxima frente

A normalização integral de itens operacionais no dashboard ainda não foi movida, pois contém regras de quarantine, escala e evidência que precisam ser extraídas junto com seus testes, sem deixar uma cópia morta no módulo Flask. Ela permanece como próximo lote de alto impacto; o serviço `dashboard_services.py` já contém a derivação anual pura, validada separadamente.

### Lote 4 executado: serviço puro do dashboard

A derivação de séries anuais operacionais foi extraída para `dashboard_services.py`. O wrapper privado `_operational_annual_series` permanece em `dashboard.py`, preservando os consumidores existentes, enquanto a regra pura deixa de ficar misturada ao módulo Flask. Os testes de comparação, dashboard e rótulos CAGR passaram: **18 passed**.

### Lote 3 executado: acesso local compartilhado

Foi criado `data_access.py` com as primitivas únicas `read_json` e `read_json_if_exists`. `dashboard.load_json`, `data_publication.read_json` e `sector_paths.read_json_if_exists` continuam como adapters públicos, preservando erros, fallbacks e formatos aceitos. A suíte completa após a mudança terminou com **199 passed, 43 subtests passed**.

1. **Contratos:** testes de identidade, schemas, aliases e formatos legados.
2. **Normalização:** extrair funções puras e comparar outputs antigos/novos em fixtures.
3. **Acesso a dados:** unificar leitura/cache sem alterar fallback.
4. **Domínio operacional:** separar pipeline e manter adapters de planilha/PDF.
5. **Dashboard:** extrair serviços e deixar rotas finas.
6. **Publicação:** consolidar manifestos e quality gates com testes de compatibilidade.
7. **Remoção:** apagar somente funções sem consumidores após dois ciclos de execução e suíte verde.

## Testes e instrumentação

- Unitários: normalização, identidade, cálculos e schemas.
- Integração: parser → extrator → snapshot → quality gate.
- Publicação: manifestos, hashes, isolamento setorial e sanitização.
- Filesystem: caminhos locais, snapshots anteriores e execução sem coleta.
- Rede: testes mockados para cache, requests e Playwright; nenhum teste unitário deve depender de rede real.
- Instrumentação futura: registrar `run_id`, etapa, função/serviço, duração, chamadas externas e arquivos lidos.

Critério de aceite da próxima refatoração: payloads e artefatos byte-equivalentes quando a normalização não tiver mudança intencional, ou diferenças explicitamente aprovadas por fixture.
# Registro adicional de execução

Lote 7: removidos os imports órfãos de `unicodedata` em `app_dre.py` e `app_indicadores.py` após a centralização dos normalizadores. Suíte completa: **202 passed, 43 subtests passed em 12,40s**.
# Registro adicional de execução

Foi adicionada uma proteção de contrato para comparar o adapter `_operational_annual_series` do dashboard com `dashboard_services.operational_annual_series`. O teste cobre a derivação anual de fluxo e confirma igualdade de saída; a suíte passou com **203 passed, 43 subtests passed**.
# Lote 9 executado: leitura opcional compartilhada

`dashboard.load_optional_json` passou a delegar para `data_access.read_json_if_exists`, preservando o retorno `None` para arquivos ausentes ou JSONs não mapeados. O contrato foi coberto por teste dedicado; a suíte completa passou com **204 passed, 43 subtests passed**.
# Lote 10 executado: normalização operacional extraída

`normalize_operational_metric_item` foi movida para `dashboard_services.py`; `dashboard.py` mantém apenas o adapter público. A regra de quarantine, escala, evidência, períodos derivados, unidade e fonte foi preservada. Durante a migração foi detectada e coberta a variante histórica de encoding em rótulos “Por Região”. Testes direcionados: **16 passed**; suíte completa: **204 passed, 43 subtests passed**.
# Lote 11 executado: fallback de statements centralizado

`dashboard.load_optional_statement` agora reutiliza `load_optional_json`, mantendo seu contrato específico de retornar `{}` quando o caminho é nulo ou inexistente. O comportamento foi protegido por testes; a suíte completa passou com **205 passed, 43 subtests passed**.
# Lote 12 executado: agregados setoriais auditados

Foi rastreado o fluxo de `dashboard_payload`: `build_sector_aggregates` é executado uma única vez no backend e seu resultado é anexado ao payload sem recomputação Python. A camada JavaScript recalcula alguns valores apenas para apresentação; isso foi classificado como duplicação de apresentação, não como divergência do cálculo oficial, e permanece candidato a um lote próprio com testes de equivalência visual.
# Lote 13 executado: parser operacional usa normalizador canônico

`app_parser_operacional.normalizar_texto` deixou de manter uma implementação paralela de NFKD, remoção de acentos e compactação de espaços; agora delega a `domain_normalization.normalize_text` e preserva a saída em minúsculas. A normalização de nomes de arquivo continua local porque possui regra distinta de caracteres permitidos. Testes direcionados: **14 passed**; suíte completa: **205 passed, 43 subtests passed**.
# Lote 14 executado: nomes de arquivo centralizados

O parser e o fallback defensivo do extrator tinham cópias equivalentes da sanitização de nomes de arquivo. A regra foi consolidada em `domain_normalization.normalize_filename`; os nomes públicos e o fallback continuam disponíveis. Testes direcionados: **14 passed**; suíte completa: **205 passed, 43 subtests passed**.
# Lote 15 executado: imports órfãos do parser removidos

Após os lotes de normalização, `unicodedata` não possuía mais consumidores em `app_parser_operacional.py` nem em `app_extrator_operacional.py`. Os imports foram removidos; usos de `re` e demais dependências continuam ativos. Suíte completa: **205 passed, 43 subtests passed**.
# Lote 16 executado: isolamento de importação do dashboard

`dashboard_services` deixou de importar `construction_operational` no carregamento do módulo. O parser de construção agora é carregado apenas quando a normalização recebe observações do setor de construção, evitando acoplamento e custo desnecessário no fluxo de saúde. Smoke check confirmou que o módulo de serviços de saúde não carrega o parser; suíte completa: **205 passed, 43 subtests passed**.
# Lote 17 executado: limpeza estática de imports

Busca AST/textual confirmou e removeu imports sem consumidores em `app_balancos.py`, `app_dre.py`, `app_divida_liquida.py`, `app_indicadores.py` e `dashboard.py`. APIs, funções e fluxos não foram removidos. Suíte completa: **205 passed, 43 subtests passed**.
# Lote 18 executado: segunda rodada de imports órfãos

A análise AST/textual residual encontrou e removeu `sys` de `app_dre.py`, `field` de `cvm_downloads.py` e `dataclass` de `sector_aggregates.py`. O parâmetro chamado `field` em uma função não era o import removido. Suíte completa: **205 passed, 43 subtests passed**.
# Lote 19 executado: remoção de módulo legado confirmado

`app_AV_AH.py` foi removido após busca de referências em código, README, workflows e testes: não havia consumidores; o dashboard atual já implementa a apresentação AV/AH e os cálculos financeiros atuais usam os módulos `app_*` vigentes. Não houve referências residuais. `compileall` e a suíte completa passaram: **205 passed, 43 subtests passed**.
# Lote 20 executado: contrato de nomes de métricas

Foi adicionada `unknown_metric_names` em `operational_dictionary.py`. O dashboard agora reporta chaves de métricas não catalogadas em `operational_coverage.unknown_metrics`, sem descartar dados ou quebrar compatibilidade futura. Testes direcionados: **22 passed**; suíte completa: **206 passed, 43 subtests passed**.
# Auditoria de exceções amplas

Os `except Exception` restantes foram classificados: boundaries de rede, conversão PDF/Playwright, fallback opcional do parser e handler HTTP de erro interno. Não foram estreitados neste lote porque suas exceções concretas incluem dependências externas variadas e os testes dependem da resiliência. O próximo desenho deve substituir mensagens soltas por eventos estruturados com etapa, ticker e causa, sem reduzir os fallbacks operacionais.
# Lote 21 executado: diagnóstico de migração legada

`migrate_legacy_company_tickers` agora registra `compatibility_diagnostics` quando converte `INNT3` para `INNC3`, identificando origem, destino e escopo somente leitura. A migração continua não destrutiva e o evento é aditivo ao payload. Teste direcionado: **7 passed**; suíte completa: **206 passed, 43 subtests passed**.
# Lote 22 executado: fallback de importação estreitado

O fallback defensivo de `app_extrator_operacional.py` passou de `except Exception` para `except ImportError`. Dependências ausentes continuam acionando o fallback, enquanto erros reais durante a inicialização do parser deixam de ser mascarados. Suíte completa: **206 passed, 43 subtests passed**.
# Lote 23 executado: coerção numérica compartilhada

`sector_aggregates.as_number` agora delega a `domain_normalization.coerce_number`. O contrato preserva números JSON, valores brasileiros com separadores, rejeição de booleanos e valores não finitos; os parsers com `Decimal` permanecem separados. Testes direcionados: **14 passed**; suíte completa: **207 passed, 43 subtests passed**.
# Lote 24 executado: chaves de dívida normalizadas pelo núcleo

`app_divida_liquida._normalise_key` deixou de duplicar a remoção de acentos/lowercase e passou a delegar a `domain_normalization.normalize_text`. O matching de contas e o contrato Decimal permanecem inalterados. Testes direcionados: **8 passed, 33 subtests passed**; suíte completa: **207 passed, 43 subtests passed**.
# Lote 26 executado: normalização de CD_CVM consolidada

`app_balancos.normalize_cd_cvm` passou a delegar à definição canônica de `company_identity`, preservando o wrapper público e o formato de seis dígitos. A seleção de companhias permanece inalterada. Testes direcionados: **10 passed, 33 subtests passed**; suíte completa: **207 passed, 43 subtests passed**.
# Lote 27 executado: cache local por execução

`DashboardDataSource` passou a memoizar leituras locais por chave durante sua instância, incluindo o resultado `None` para arquivos ausentes. O cache não é persistente e não altera payloads; evita reabrir o mesmo JSON em reutilizações da fonte. Testes direcionados: **19 passed**; suíte completa: **208 passed, 43 subtests passed**.
# Lote 28 executado: CAGR da apresentação alinhado ao payload

O resumo JavaScript do dashboard agora usa `comparison.companies[ticker].cagr_receita` e `.cagr_lucros`, calculados pelo backend. O cálculo JavaScript permanece apenas como fallback para payloads históricos sem esses campos, evitando quebra de compatibilidade. Testes direcionados: **14 passed**; suíte completa: **208 passed, 43 subtests passed**.
# Lote 29 executado: EV/EBITDA da apresentação alinhado

O resumo JavaScript agora prioriza `comparison.ev_ebitda.value`, calculado e qualificado no backend, em vez de recompor o múltiplo com dados brutos. O cálculo local permanece como fallback para payloads históricos. Testes direcionados: **14 passed**; suíte completa: **208 passed, 43 subtests passed**.
# Lote 30 executado: leitura JSON sem mascaramento amplo

Os dois caminhos de fallback de `load_operational_data` que envolvem exclusivamente `load_json` agora capturam somente `OSError`, `ValueError` e `UnicodeError`. Falhas inesperadas de normalização/estrutura passam a ser visíveis, sem perder a resiliência para arquivos ausentes ou inválidos. Testes direcionados: **11 passed**; suíte completa: **208 passed, 43 subtests passed**.

# Lote 31 executado: baseline classificável e eventos de compatibilidade

Foi adicionada a classificação formal da suíte em `pytest.ini` e `tests/conftest.py`, permitindo execuções por risco sem alterar a lógica dos testes. A suíte completa passou com **210 passed, 43 subtests passed**; os grupos de publicação, filesystem e integração foram executados separadamente.

`contract_validation.py` passou a concentrar a criação de diagnósticos serializáveis de compatibilidade e a leitura dos envelopes atuais e históricos de empresas. A migração de ticker no dashboard usa esse núcleo, preservando a interface e o comportamento somente-leitura. O lote não removeu dados nem APIs públicas.

# Lote 32 executado: contrato de métricas do dashboard isolado

O catálogo `COMPARISON_METRICS` foi movido para `dashboard_services.py`; `dashboard.py` continua expondo o mesmo nome por importação compatível e mantém as rotas e payloads inalterados. Testes direcionados e suíte completa passaram: **212 passed, 43 subtests passed**.

# Lote 33 executado: assets de gráficos isolados do Flask

A transformação de manifestos em URLs de assets foi extraída para `dashboard_services.build_chart_assets_payload`. O adapter `dashboard.build_chart_assets` preserva o cache, o versionamento, o prefixo por setor e a interface pública. Testes direcionados: **16 passed**; suíte completa: **213 passed, 43 subtests passed**.

# Lote 34 executado: separação da apresentação do dashboard

Foi criado `dashboard_presentation.py` para os contratos de métricas comparativas e assets de gráficos. `dashboard_services.py` permanece focado nas transformações de domínio operacional, mas reexporta os símbolos antigos como compatibilidade. O dashboard importa diretamente o módulo de apresentação e mantém as APIs existentes. Suíte completa: **214 passed, 43 subtests passed**.

# Lote 35 executado: contratos de publicação isolados

As regras puras de montagem e merge de manifestos foram movidas para `publication_contracts.py`. `data_publication.py` permanece como orquestrador de filesystem e expõe os wrappers públicos existentes. A implementação duplicada foi removida após os testes de publicação, isolamento setorial e resiliência: **33 testes direcionados** e **214 testes/43 subtestes na suíte completa**.

# Lote 36 executado: métricas de cache local do dashboard

`DashboardDataSource` passou a expor `cache_stats()` e o payload inclui `data_access` com entradas, hits e misses da memoização local por execução. O comportamento dos dados não foi alterado; o contrato foi protegido por testes de cache, fontes remotas e dashboard. Suíte completa: **214 passed, 43 subtests passed**.

# Lote 37 executado: persistência atômica do tracking

`TrackingRun.write` agora grava em arquivo temporário no mesmo diretório, força o flush e substitui o destino com `os.replace`. Em falha, o temporário é removido; o arquivo anterior permanece preservado. Teste específico de substituição atômica e suíte completa passaram: **215 passed, 43 subtests passed**.

# Lote 38 executado: remoção de helper de caminho órfão

`sector_paths.resolve_operational_results_dir` foi removida após busca textual, AST, entrypoints, workflows, documentação e suíte confirmarem ausência de consumidores. A composição equivalente continua disponível por `resolve_sector_results_dir` e pelos caminhos explícitos do pipeline. `buscar_preco_yfinance` foi mantida por ser API pública potencial sem evidência suficiente de remoção segura. Testes direcionados: **22 passed**; suíte completa: **215 passed, 43 subtests passed**.

# Lote 39 executado: fronteira de configuração de perfis

O carregamento de perfis deixou de silenciar qualquer exceção do registry de fontes. Apenas `ImportError` continua sendo fallback válido para ambientes sem o módulo opcional; erros de configuração agora são propagados e auditáveis. Os testes de perfis e operação passaram (**17 passed**) e a suíte completa permaneceu em **215 passed, 43 subtests passed**.

# Lote 40 executado: fallback remoto com exceção específica

`remote_http_get_json` agora converte somente falhas de transporte/decodificação esperadas em `RemoteDataError`, e `cached_remote_json` trata `RemoteDataError` e `KeyError` de mocks/ausência de chave como fallback remoto. Erros de implementação não são mais absorvidos genericamente. Testes remotos: **14 passed**; suíte completa: **215 passed, 43 subtests passed**.

# Lote 41 executado: classificação mutuamente exclusiva da suíte

Os markers de teste foram corrigidos para que cada arquivo pertença a uma categoria principal (`unit`, `integration`, `publication`, `filesystem` ou `network`), com `slow` e `stateful` como atributos complementares. As execuções focadas passaram: unit **80**, integration **29**, publication **35**, filesystem **42**, network **29**; suíte completa **215 passed, 43 subtests passed**.

# Lote 42 executado: escrita atômica compartilhada de artefatos mutáveis

`data_access.atomic_write_text` foi criada como primitiva única de persistência segura e aplicada ao catálogo documental e aos overrides operacionais manuais. O conteúdo e os caminhos públicos permanecem iguais; a substituição agora ocorre por temporário, `fsync` e `os.replace`. Testes direcionados: **12 passed**; suíte completa: **216 passed, 43 subtests passed**.

# Lote 43 executado: escrita atômica de outputs financeiros selecionados

Foi adicionada `data_access.atomic_write_json`, baseada na mesma persistência atômica, e aplicada aos outputs de reconciliação e market cap atual. Schemas, caminhos e serialização JSON foram preservados. Testes direcionados: **13 passed**; suíte completa: **217 passed, 43 subtests passed**.

# Lote 44 executado: manifestos de publicação com escrita atômica

Os manifestos, metadados, quality reports e overrides produzidos por `data_publication.py` passaram a usar `atomic_write_json`. A ordem de staging/cópia/merge e a preservação setorial permanecem inalteradas. Testes direcionados: **38 passed**; suíte completa: **217 passed, 43 subtests passed**.

# Lote 45 executado: outputs de gráfico e dívida líquida com escrita atômica

O manifesto de geração de gráficos e o JSON produzido pelo CLI de dívida líquida passaram a usar as primitivas atômicas compartilhadas. Testes de metodologia, assets e publicação: **21 passed**; suíte completa: **217 passed, 43 subtests passed**.

# Lote 46 executado: snapshots operacionais com escrita atômica

Snapshots por ticker, agregados de observações e resultados JSON do parser/extrator operacional passaram a usar `atomic_write_json`. A política de quarantine, preservação de snapshots anteriores e retorno dos CLIs foi mantida. Testes operacionais direcionados: **44 passed**; suíte completa: **217 passed, 43 subtests passed**.

# Lote 47 executado: writers restantes do parser operacional

O manifesto de downloads, metadados PDF, Markdown e snapshots HTML de diagnóstico passaram a usar `atomic_write_json` ou `atomic_write_text`. O parser mantém seus caminhos, conteúdo, modo diagnóstico e comportamento offline. Testes de parser/resiliência/isolamento: **37 passed**; suíte completa: **217 passed, 43 subtests passed**.

# Lote 48 executado: benchmark e eventos CVM com escrita atômica

O resultado do benchmark offline e o registro de eventos de downloads CVM passaram a usar `atomic_write_json`. Os fluxos continuam locais, substituíveis e sem alteração de schema. Testes direcionados: **6 passed**; suíte completa: **217 passed, 43 subtests passed**; `compileall` aprovado.

# Lote 49 executado: manifests legados e staging atômicos

Os manifests `execucao.json` do DFC, os manifests legados gerados pelo dashboard e as cópias sanitizadas do staging passaram a usar `atomic_write_json`. Os três `write_text` restantes são exclusivamente gravações em arquivos temporários seguidas de substituição atômica. Testes direcionados: **22 passed**; suíte completa: **217 passed, 43 subtests passed**; `compileall` aprovado.

# Lote 50 executado: padrão de persistência financeira consolidado

Os writers JSON finais de balanço, DRE e DFC deixaram de repetir manualmente o padrão temporário/substituição e passaram a usar `atomic_write_json`. Os downloads ZIP e o Excel continuam com seus temporários específicos, pois possuem validação binária própria. Testes financeiros direcionados: **27 passed, 33 subtests passed**; suíte completa: **217 passed, 43 subtests passed**.

## Lote 52 executado: helpers financeiros puros

Os helpers de períodos, filtros anuais, CAGR, qualidade, células comparativas e seleção de métricas foram centralizados em `dashboard_financial_services.py`. `dashboard.py` mantém bindings de compatibilidade durante a migração, sem alterar rotas ou payloads. Testes direcionados: **15 passed**; suíte completa: **218 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Auditoria consolidada do estado atual

## Lote 72 executado: saída do ciclo financeiro atômica

`app_ciclo_financeiro.py` passou a usar `data_access.atomic_write_json` para o artefato final. As leituras de entrada permanecem locais com `utf-8-sig`, pois esse contrato aceita arquivos CVM com BOM e não é equivalente ao leitor JSON genérico. Testes direcionados: **9 passed**; suíte completa: **220 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 71 executado: writer de overrides manual unificado

`manual_operational.write_manual_overrides_file` passou a usar `data_access.atomic_write_json`, removendo a duplicação de serialização + gravação textual. O formato, encoding, indentação e newline final permanecem iguais; as serializações HTTP continuam separadas. Testes direcionados: **18 passed, 10 subtests passed**; suíte completa: **220 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 70 executado: revisão de exceções no market cap

As capturas amplas restantes em `app_market_cap.py` foram classificadas como fronteiras externas: `get_shares_full`, `fast_info`, `get_info`, tentativas alternativas de ticker e o fallback por companhia. Estreitar essas exceções sem um contrato estável do yfinance poderia interromper a recuperação de dados. Permanecem documentadas e cobertas pelos testes de fallback; nenhuma alteração foi feita neste lote.

## Lote 69 executado: proteção dos wrappers públicos de leitura

Embora `ruff`, `pyflakes` e `pylint` não estejam disponíveis no ambiente, a análise AST não encontrou novos imports não utilizados além dos reexports intencionais. Foram adicionados testes para confirmar que `data_publication.read_json` e `sector_paths.read_json_if_exists` continuam delegando ao contrato canônico e preservando seus formatos públicos. Suíte completa: **220 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 68 executado: auditoria dos temporários remanescentes e baseline por categoria

A revisão dos padrões `mkstemp`/`os.replace` confirmou que os únicos writers fora de `data_access` são o Excel de `app_balancos` e o ZIP de downloads CVM, que exigem temporários binários e validações específicas. Não foram unificados artificialmente. Baseline categorizado: unit **81 passed, 33 subtests**; integration **29 passed**; publication **36 passed**; filesystem **44 passed, 10 subtests**; network **29 passed**. A suíte geral permanece em **219 passed, 43 subtests**.

## Lote 67 executado: persistência atômica do tracking centralizada

`tracking.TrackingRun.write` deixou de repetir o fluxo temporário/`fsync`/`replace` e passou a usar `data_access.atomic_write_text`. O JSON, encoding, newline e semântica de substituição foram preservados; a dependência de limpeza duplicada foi removida. Testes direcionados: **31 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 66 executado: manifesto do parser com erro delimitado

O parser passou a ler o manifesto legado por `data_access.read_json` e substituiu `except Exception` por tratamento de `OSError`, `JSONDecodeError` e `TypeError`. O fallback para lista vazia permanece inalterado para arquivo ausente, inválido ou com formato incompatível. Testes direcionados: **37 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 65 executado: leituras operacionais pelo acesso canônico

Leituras locais de metadados, snapshots operacionais, contagem de observações, manifestos de gráfico e overrides manuais passaram a usar `data_access.read_json`. A serialização JSON em memória, respostas HTTP e assinaturas de conteúdo continuam usando o módulo `json` quando essa é a operação correta. Testes direcionados: **45 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 64 executado: validações usando leitor JSON canônico

As validações finais de balanços, DFC, DRE e reconciliação deixaram de repetir `json.loads(path.read_text(...))` e passaram a usar `data_access.read_json`. Os imports `json` exclusivos dessas leituras foram removidos; serialização e handlers que realmente dependem de `json` permaneceram intactos. Testes direcionados: **14 passed, 33 subtests passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 63 executado: leitura canônica dentro da publicação

`data_publication.py` mantém `read_json` como wrapper de compatibilidade, mas suas rotinas internas agora usam diretamente `data_access.read_json`. A cadeia de publicação deixou de atravessar o wrapper, sem mudar a interface disponível para consumidores externos. Testes direcionados: **20 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 62 executado: publicação usando acesso canônico

`data_publication.py` deixou de depender do wrapper intermediário `sector_paths.read_json_if_exists` e passou a importar diretamente `data_access.read_json_if_exists`. O wrapper setorial foi preservado como API de compatibilidade, mas não participa mais da cadeia interna de publicação. Testes direcionados: **27 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 61 executado: revisão das normalizações remanescentes

A revisão confirmou que as variantes restantes são adapters ou regras de domínio, não cópias acidentais: `construction_operational.normalize_text`, `app_parser_operacional.normalizar_texto` e `app_extrator_operacional.normalise_text` já delegam à normalização compartilhada com parâmetros distintos; `app_balancos.normalize_text` aplica regra específica de maiúsculas para contas CVM; `app_dre.normalizar` acrescenta regra societária `S A`; e os normalizadores de período têm contratos diferentes para operação manual, construção e períodos contábeis. Nenhuma remoção adicional foi autorizada por esta evidência.

## Lote 60 executado: contrato explícito de reexportação

`dashboard_services.py` recebeu `__all__` documentando os símbolos de apresentação mantidos como compatibilidade (`COMPARISON_METRICS` e `build_chart_assets_payload`) e os serviços operacionais canônicos. Testes confirmam que os símbolos reexportados são exatamente os objetos de `dashboard_presentation`, sem cópias paralelas. Suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 59 executado: remoção de binding financeiro não utilizado

Após a remoção dos corpos locais, `_period_sort_key` permaneceu apenas como import sem consumidores em `dashboard.py`; a análise AST e a busca textual confirmaram isso. O binding foi removido, enquanto os demais aliases continuam sendo usados por `build_comparison_payload` ou mantidos como compatibilidade interna. Suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 58 executado: imports não utilizados

A análise AST e a busca textual confirmaram que os imports `json` de `app_market_cap.py`, `construction_benchmark.py` e `data_publication.py` não eram referenciados. Eles foram removidos; imports de compatibilidade em `dashboard_services.py` foram mantidos por serem parte da superfície reexportada. Testes direcionados: **7 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 57 executado: classificação de APIs aparentemente órfãs

A busca textual/AST confirmou que `build_workbook`, `verify_workbook` e `exportar_excel` não possuem consumidores internos. Eles permanecem classificados como **API legada potencial**, pois formam a trilha de exportação Excel e não há evidência suficiente para afirmar ausência de consumidores externos. `Handler.do_GET` e `Handler.do_POST` foram classificados como **ativos**: são despachados pelo servidor HTTP padrão, mesmo sem chamadas textuais diretas. Nenhum desses itens foi removido.

## Lote 56 executado: remoção de coletor HTTP órfão

`obter_html_requests` foi removida após busca textual, AST, workflows e documentação confirmarem ausência de consumidores. O parser mantém o mesmo fluxo HTTP em `coletar_documentos_empresa`, que continua usando a sessão `requests` compartilhada. Testes direcionados: **37 passed**; suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 55 executado: preservação do contrato numérico

Após a extração dos helpers financeiros, o tratamento de `NaN` e booleanos foi alinhado ao comportamento anterior (`None`/ausente), evitando ampliação silenciosa do contrato. Foram adicionados testes de regressão para essa fronteira. Suíte completa: **219 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 54 executado: consolidação dos bindings financeiros

Os quatro imports intermediários criados durante a migração foram consolidados em um único bloco de compatibilidade em `dashboard.py`. A busca AST confirmou uma única importação de `dashboard_financial_services`; não foram encontrados consumidores externos dos nomes privados migrados. Suíte completa: **218 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 53 executado: remoção dos corpos duplicados do dashboard

Os corpos locais dos helpers puros de períodos, CAGR, qualidade, células comparativas, ciclos e seleção operacional foram removidos de `dashboard.py`. Os nomes internos continuam disponíveis por bindings compatíveis importados de `dashboard_financial_services.py`. Testes direcionados: **22 passed**; suíte completa: **218 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

## Lote 51 executado: contrato backend do resumo do dashboard

`build_comparison_payload` passou a expor `current_summary` para dívida líquida, capital de giro e capital de giro/receita. O JavaScript usa esses valores como fonte primária e conserva fallback explícito para payloads antigos. O contrato é aditivo: as 12 métricas comparativas e as rotas existentes não foram alteradas. Testes direcionados: **11 passed**; suíte completa: **218 passed, 43 subtests passed**; `compileall` e `git diff --check` aprovados.

### Itens removidos com evidência

- `app_AV_AH.py`: arquivo sem referências em código, testes, workflows ou documentação.
- `sector_paths.resolve_operational_results_dir`: helper sem consumidores; composição equivalente permanece explícita.
- Implementações duplicadas de normalização textual, identificadores, nomes de arquivo, leitura JSON, contratos de manifesto e persistência JSON.

### Itens mantidos deliberadamente

- `buscar_preco_yfinance`, `exportar_excel`, `metric_ids` e `sector_dictionary`: funções públicas potenciais, sem consumidor interno, mas sem autorização suficiente para quebra de compatibilidade externa.
- `extract_workbook_observations`, `calculate_roe` e `calculate_credit_loss_proxy`: APIs de domínio cobertas por testes e úteis para compatibilidade/futuras entradas.
- Fallbacks de saúde, construção, tickers históricos e formatos `companies`/`empresas`: contratos históricos documentados.
- Temporários de ZIP e Excel: necessários para validação binária antes da substituição.

### Pendências arquiteturais não removidas

- `dashboard.py` ainda contém rotas, HTML embutido e alguns serviços de domínio; os serviços puros já extraídos devem continuar sendo ampliados em lotes próprios.
- Exceções amplas restantes pertencem principalmente a limites de rede, Playwright, subprocessos e handlers HTTP; cada uma requer teste específico antes de estreitamento.
- Algumas recomputações JavaScript são somente de apresentação e só devem ser removidas após equivalência visual/payload.

Auditoria específica da apresentação: dívida líquida e capital de giro ainda são calculados a partir de fontes brutas no resumo JavaScript. O payload comparativo atual não possui células backend equivalentes com a mesma granularidade temporal; a remoção segura exige primeiro definir esse contrato, adicionar fixtures de paridade e só então retirar o fallback JavaScript.

### Evidência de regressão

Baseline vigente: **217 passed, 43 subtests passed**, com grupos unit, integração, publicação, filesystem e rede executáveis isoladamente; `compileall`, smoke tests do dashboard e `git diff --check` aprovados após os lotes de limpeza.

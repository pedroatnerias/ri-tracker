# Auditoria de limpeza e arquitetura — Nerias RI Tracker V2

Data da auditoria: 2026-09-04  
Escopo: código Python, testes, workflows, documentação e contratos de dados do diretório V2.

## 1. Baseline de validação

Comando executado:

```text
python -m pytest -q --maxfail=3
```

Resultado observado: **73 testes passaram, 3 falharam e 43 subtestes passaram**.

Falhas reproduzidas:

| Teste | Diagnóstico | Prioridade |
|---|---|---|
| `test_document_resolution_uses_company_alias_not_generic_words` | `Cyrela Brazil Realty` não está entre os aliases do registro/perfil; `resolve_company_for_document` retorna `None` em vez de `CYRE3`. | Alta |
| `test_unknown_company_has_safe_empty_profile` | `profile_for("NEW3")` retorna apenas `schema_version` e `ticker`, mas o contrato do consumidor exige `metrics: {}`. | Alta |
| `test_material_discrepancy_blocks_market_cap` | `diferenca_pct` é calculada como diferença relativa (`90.0`), enquanto o contrato/teste espera a diferença percentual em pontos percentuais (`900.0`). | Alta |

O teste completo foi interrompido após a terceira falha para evitar etapas potencialmente lentas de coleta ou fixtures externas. Deve existir uma execução posterior separando testes unitários, integração, filesystem e rede.

## 2. Matriz de componentes

| Componente | Responsabilidade | Consumidores/entrada | Status de auditoria |
|---|---|---|---|
| `update_data.py` | Orquestra atualização por setor, escopo e modo | CLI, workflow GitHub Actions | Ativo; contrato público |
| `dashboard.py` | Flask, carregamento, transformação, agregação e apresentação | `wsgi.py`, execução local, endpoints | Ativo; alto acoplamento |
| `wsgi.py` | Ponto de entrada WSGI | Gunicorn/cloud | Ativo |
| `data_publication.py` | Validação, manifesto e publicação de artefatos | CLI, pipeline, workflow | Ativo; preservar compatibilidade |
| `app_extrator_operacional.py` | Extração operacional de RI | pipeline de saúde/construção | Ativo; dependência externa |
| `app_parser_operacional.py` | Parsing e descoberta documental | extrator operacional | Ativo; alto risco de regressão |
| `operational_sources.py` | URLs/domínios/fontes por setor | extrator e perfis | Ativo; fonte de configuração |
| `company_registry.py` | Cadastro canônico de empresas, tickers e aliases | módulos financeiros, operacionais e dashboard | Ativo; fonte única desejada |
| `construction_company_profiles/` | Regras declarativas por empresa | extrator de construção | Ativo; schema inconsistente para desconhecidos |
| `app_*` financeiros | Demonstrações, dívida, ciclo, market cap e indicadores | `update_data.py`, dashboard | Ativos; revisar fronteiras e duplicação |
| `sector_aggregates.py` | Agregação setorial e diagnósticos | pipeline e dashboard | Ativo; revisar dependências de market cap |
| `chart_generation.py` | Gráficos e manifests | pipeline/publicação/dashboard | Ativo |
| `manual_operational.py` | Fluxo manual de dados operacionais | workflows/uso assistido | Ativo ou legado controlado; confirmar consumidores |
| `document_catalog.py` e `tracking.py` | Catálogo e auditoria documental | extratores/publicação | Ativos; consolidar contratos |

Arquivos de dados, diretórios `resultados/`, `dados_cvm/`, logos e perfis JSON não devem ser tratados como código removível sem verificar manifesto, fallback e publicação histórica.

## 3. Contratos de nomes e compatibilidade

`company_registry.py` deve permanecer como fonte canônica para ticker atual, ticker histórico, nome societário, aliases, CVM e setor. Perfis e fontes devem consumir esse cadastro, sem redefinir nomes em cada módulo.

Pendências identificadas:

- Adicionar explicitamente `Cyrela Brazil Realty` ao conjunto de aliases de `CYRE3`, com teste de conteúdo e teste de empate entre empresas.
- Fazer o perfil desconhecido retornar o schema mínimo completo (`metrics: {}` e campos opcionais seguros), ou formalizar um `empty_profile()` único.
- Definir uma única convenção para `diferenca_pct`: percentual relativo de 0–100 ou pontos percentuais; alinhar cálculo, teste, logs e dashboard.
- Catalogar todos os nomes de métricas (`metric_definitions.py`, dicionários operacionais, JSONs e dashboard) e introduzir validação centralizada.
- Manter adapters explícitos para `INNT3`/`INNC3`, formato plano antigo e snapshots históricos, com diagnóstico quando usados.
- Eliminar strings duplicadas de setor, escopo e nomes de campos; preferir enums/constantes centrais quando não quebrar os JSONs existentes.

## 4. Candidatos a remoção ou refatoração

Nenhum item deve ser apagado antes da etapa seguinte. Os candidatos precisam ser confirmados por busca de referências, entrypoints, workflows e execução dos testes.

- Código duplicado entre módulos `app_*` para leitura, normalização, logs e tratamento de datas.
- Responsabilidades de cálculo e apresentação concentradas em `dashboard.py`.
- Fallbacks históricos sem função de compatibilidade nomeada ou telemetria de uso.
- Imports opcionais dentro de funções que podem mascarar dependências ausentes com `except Exception` amplo.
- Definições de aliases/perfis que não passam por validação uniforme.
- Rotinas de leitura e recomputação que podem carregar o mesmo JSON/DataFrame várias vezes na mesma requisição.
- Arquivos ou funções encontrados apenas por busca estática devem ser classificados como `incertos` até uma execução instrumentada confirmar ausência de uso.

## 5. Riscos arquiteturais e melhorias priorizadas

### P0 — contratos quebrados

1. Corrigir aliases da Cyrela, perfil vazio e semântica de `diferenca_pct`.
2. Criar testes de contrato para registry, perfis, normalização e payloads publicados.
3. Validar schemas na fronteira de leitura e publicação, com mensagens de erro estruturadas.

### P1 — segurança de manutenção

1. Separar `dashboard.py` em carregamento de dados, serviços de domínio, serialização/payload e rotas; preservar as rotas atuais.
2. Centralizar identidade de empresas e nomes de métricas.
3. Criar camadas claras para coleta externa, cache, transformação e publicação.
4. Substituir `except Exception` amplo por exceções específicas e diagnósticos com contexto.

### P2 — eficiência e operação

1. Cachear leituras imutáveis por execução e evitar recomputação por requisição.
2. Isolar testes de rede e tornar o modo sem coleta determinístico.
3. Medir duração por etapa, quantidade de chamadas externas, cache hit/miss e volume de dados processado.
4. Adicionar validação de consistência entre manifesto, gráficos, market cap e snapshot financeiro.

## 6. Lotes de implementação posteriores

1. **Contratos e regressões:** corrigir as três falhas, adicionar aliases/schema/semântica centralizados e deixar a suíte unitária verde.
2. **Inventário confirmado:** remover imports, funções e arquivos mortos somente após evidência de não uso; atualizar testes e documentação.
3. **Fronteiras de domínio:** extrair identidade, métricas, carregamento e cálculos do dashboard sem alterar endpoints.
4. **Pipeline e publicação:** consolidar coleta/cache/publicação, mantendo fallbacks históricos e isolamento setorial.
5. **Performance e observabilidade:** cache por execução, métricas de duração/chamadas, testes de resiliência e validação dos artefatos.

## 7. Critérios de aceite

- Suíte unitária e de integração classificadas e executáveis separadamente.
- Zero remoções sem consumidor analisado e teste de regressão correspondente.
- Todos os aliases canônicos resolvem de forma determinística, com empate bloqueado.
- Saúde e construção permanecem isoladas e os modos sem coleta não fazem chamadas externas.
- Rotas principais, CLI, publicação parcial, snapshots históricos, gráficos e manifestos permanecem válidos.
- Cada lote produz diff pequeno, reversível e validado por compilação, testes relacionados e suíte completa.

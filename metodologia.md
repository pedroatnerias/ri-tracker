---
title: "Metodologia do Novo RI Tracker"
version: "2.0"
date: "2026-08-17"
language: "pt-BR"
purpose: "Documentação técnica para leitura pelo Codex e posterior incorporação em HTML"
---

# Metodologia do Novo RI Tracker

## 1. Objetivo

Este documento descreve a metodologia utilizada pelo sistema **Novo RI Tracker** para:

1. extrair dados financeiros, operacionais e de mercado;
2. normalizar e validar os dados;
3. calcular indicadores financeiros;
4. estruturar os dados em JSON;
5. disponibilizar os resultados para consumo pelo dashboard e posterior renderização em HTML.

A arquitetura geral do sistema é:

```text
CVM + Yahoo Finance + Sites de RI
        ↓
Extração e validação
        ↓
Normalização
        ↓
JSONs padronizados
        ↓
Cálculos financeiros e operacionais
        ↓
Dashboard / HTML
```

---

# 1.1. Atualizacao Metodologica 2.0

A versao 2.0 formaliza a separacao entre dados oficiais, indicadores
calculados pelo sistema, indicadores ajustados divulgados pelas companhias e
diferencas metodologicas. O objetivo e aumentar comparabilidade historica,
auditabilidade e seguranca analitica, sem alterar dados oficiais para forcar
reconciliacoes.

Principios obrigatorios:

1. Demonstracoes financeiras continuam usando CVM como fonte primaria.
2. Dados de releases de RI nao substituem valores contabeis CVM.
3. Releases, apresentacoes e planilhas de fundamentos sao usados para metricas
   operacionais, metricas ajustadas divulgadas, reconciliacoes e validacao.
4. Contas ausentes permanecem `null` ou vazias; ausencia nao e zero.
5. Todo indicador calculado deve preservar formula, componentes, periodo,
   fonte, escopo e flags de qualidade quando disponiveis.

## 1.1.1. Camada central de definicoes

As definicoes metodologicas foram centralizadas no modulo:

```text
metric_definitions.py
```

Esse modulo define:

- versao metodologica;
- escopo financeiro por companhia;
- regra de receita usada em margens;
- tratamento IFRS 17;
- regra de divida liquida;
- inclusao ou nao de arrendamentos;
- formulas de EBITDA, EBITDA LTM, EV e EV/EBITDA LTM;
- limites iniciais de materialidade;
- status de qualidade.

Versao atual:

```text
methodology_version = 2.0
```

## 1.1.2. Escopo de RDOR3

RDOR3 deve permanecer como demonstrativo individual nos extratores financeiros
de BP, DRE e DFC. Essa excecao e explicita no sistema:

```text
RDOR3: individual
demais companhias: consolidado
```

Isso deve aparecer na auditoria e na metodologia. Comparacoes envolvendo RDOR3
devem considerar que o escopo contábil difere do escopo consolidado usado nas
demais companhias.

## 1.1.3. EBITDA contabil e EBITDA ajustado divulgado

O sistema possui duas metricas distintas:

```text
ebitda_contabil
ebitda_ajustado_divulgado
```

O EBITDA contabil e calculado pelo sistema a partir das demonstracoes CVM:

```text
ebitda_contabil = EBIT CVM 3.05 + depreciacao e amortizacao da DFC
```

O EBITDA ajustado divulgado so pode ser preenchido quando houver valor
explicitamente divulgado em fonte oficial de RI, como release, apresentacao,
planilha de fundamentos ou outro documento oficial.

O sistema nao deriva ajustes automaticamente. Quando o valor ajustado divulgado
nao estiver disponivel:

```text
ebitda_ajustado_divulgado = null
```

O campo legado `ebitda`, quando presente, corresponde ao EBITDA contabil
calculado e e mantido apenas para compatibilidade com visualizacoes existentes.

## 1.1.4. Controle de qualidade do EBITDA

Quando houver EBITDA contabil e EBITDA ajustado divulgado, sao calculadas:

```text
diferenca_absoluta = ebitda_ajustado_divulgado - ebitda_contabil
```

```text
diferenca_percentual =
(ebitda_ajustado_divulgado / ebitda_contabil - 1) * 100
```

Como parametro inicial, diferencas percentuais absolutas acima de 5% devem ser
marcadas como diferenca metodologica relevante. O EBITDA contabil nao deve ser
alterado para coincidir com o EBITDA ajustado divulgado.

## 1.1.5. HAPV3 e IFRS 17

Para HAPV3, a linha CVM `3.01` continua disponivel como dado contabil:

```text
receita_contabil_cvm
```

Porem, apos IFRS 17, ela nao deve ser usada automaticamente como denominador de
margens gerenciais quando a definicao economica comparavel depender da receita
operacional divulgada pela companhia.

O sistema separa:

```text
receita_contabil_cvm
receita_operacional_divulgada
receita_para_margens
denominador_margens
```

Enquanto a receita operacional divulgada nao for extraida de fonte oficial com
confianca suficiente, margens gerenciais de HAPV3 devem receber flag de
qualidade como `not_comparable` ou `incomplete`, em vez de serem calculadas com
denominador inadequado.

## 1.1.6. Divida liquida padronizada e divulgada

O sistema separa:

```text
divida_liquida_padronizada
divida_liquida_divulgada
```

A divida liquida padronizada e calculada a partir do BP CVM:

```text
divida_bruta =
emprestimos_e_financiamentos_cp
+ emprestimos_e_financiamentos_lp
+ arrendamentos_incluidos
```

```text
caixa_financeiro =
caixa_e_equivalentes
+ aplicacoes_financeiras_deduzidas
```

```text
divida_liquida_padronizada =
divida_bruta - caixa_financeiro
```

Configuracao padrao atual:

```text
deduct_financial_investments = true
net_debt_include_leases = false
```

Arrendamentos nao sao incluidos ou excluidos silenciosamente. A flag
`net_debt_include_leases` deve estar documentada e auditavel.

A divida liquida divulgada pela companhia, quando disponivel, fica em campo
separado e nao substitui a padronizada.

## 1.1.7. EV, EBITDA LTM e EV/EBITDA LTM

O multiplo principal do sistema passa a ser:

```text
ev_ebitda_ltm = enterprise_value / ebitda_contabil_ltm
```

Enterprise Value:

```text
enterprise_value = market_cap_historico + divida_liquida_padronizada
```

EBITDA LTM:

```text
ebitda_contabil_ltm =
soma dos quatro ultimos trimestres individuais comparaveis
```

Reconstrucao de trimestres isolados quando a CVM divulga valores acumulados:

```text
1T isolado = 1T
2T isolado = 6M - 1T
3T isolado = 9M - 6M
4T isolado = FY - 9M
```

O sistema calcula LTM somente quando existem quatro trimestres individuais
comparaveis. Se nao houver:

```text
ev_ebitda_ltm = null
```

Nao ha anualizacao silenciosa.

Para coerencia temporal:

```text
EV(t) = market_cap(t) + divida_liquida_padronizada(t)
```

O JSON deve registrar, quando disponivel:

- `data_market_cap`;
- `data_divida_liquida`;
- `data_ebitda_ltm`;
- `quality_flag`.

## 1.1.8. Market cap historico

O market cap historico continua sendo:

```text
market_cap = preco_acao * quantidade_acoes_total
```

A quantidade de acoes vem da composicao do capital da CVM. O preco historico e
o fechamento na data de referencia ou o ultimo pregao anterior. Devem ser
preservados:

- `data_referencia`;
- `data_preco`;
- `quantidade_acoes_total`;
- `preco_acao`;
- `market_cap`.

## 1.1.9. Quality flags

Indicadores calculados podem receber status como:

```text
validated
methodology_difference
estimated
incomplete
not_comparable
requires_review
error
```

Exemplos:

- EBITDA contabil diferente do EBITDA ajustado divulgado: `methodology_difference`;
- falta de quatro trimestres para LTM: `incomplete`;
- extracao operacional textual ambigua: `requires_review`;
- escopos incompatíveis: `not_comparable`.

## 1.1.10. Dados operacionais e falsos positivos

Dados operacionais extraidos de documentos textuais exigem evidencia
contextual. O sistema usa niveis de confianca:

```text
HIGH: tabela, planilha de fundamentos, linha rotulada, secao de indicadores
MEDIUM: bullet ou frase declarando KPI e unidade de forma clara
LOW: palavra-chave em texto corrido ou numero semanticamente ambiguo
```

Somente `HIGH` e `MEDIUM` bem definidos devem alimentar automaticamente o
dashboard. Casos `LOW` devem ser mantidos como candidatos para revisao, sem
preencher valor automaticamente.

Regressoes explicitamente bloqueadas:

- texto contratual sobre aluguel ou unidades operacionais nao pode virar numero
  de unidades.

O sistema preserva a regra:

```text
Pacientes-dia != numero de pacientes
```

## 1.1.11. Relatorio de reconciliacao

O pipeline gera:

```text
resultados/relatorio_reconciliacao.json
```

O relatorio organiza, por empresa e periodo, informacoes criticas de CVM,
metricas calculadas e metricas divulgadas quando disponiveis. As classificacoes
possiveis incluem:

```text
MATCH
IMMATERIAL_DIFFERENCE
METHODOLOGY_DIFFERENCE
MATERIAL_DIFFERENCE
MISSING_DATA
NOT_COMPARABLE
```

O objetivo nao e exigir igualdade entre metricas de metodologias distintas, mas
permitir auditoria clara das diferencas.

---

# 2. Empresas acompanhadas

| Ticker | Companhia | Escopo CVM |
|---|---|---|
| AALR3 | Alliança Saúde | Consolidado |
| DASA3 | Dasa | Consolidado |
| FLRY3 | Fleury | Consolidado |
| HAPV3 | Hapvida | Consolidado |
| MATD3 | Mater Dei | Consolidado |
| ONCO3 | Oncoclínicas | Consolidado |
| RDOR3 | Rede D'Or São Luiz | Individual |

O escopo utilizado nos demonstrativos da CVM é consolidado para todas as companhias, exceto RDOR3, que utiliza dados individuais.

---

# 3. Fontes de dados

## 3.1. CVM

As principais fontes financeiras são os conjuntos de dados abertos da Comissão de Valores Mobiliários:

- ITR — Informações Trimestrais;
- DFP — Demonstrações Financeiras Padronizadas.

Os arquivos anuais são baixados diretamente dos ZIPs publicados pela CVM.

São utilizados dados de:

- Balanço Patrimonial Ativo — BPA;
- Balanço Patrimonial Passivo — BPP;
- Demonstração do Resultado — DRE;
- Demonstração dos Fluxos de Caixa — DFC;
- Composição do Capital.

## 3.2. Yahoo Finance

O Yahoo Finance é acessado através da biblioteca `yfinance`.

É utilizado para:

- preço atual das ações;
- histórico de preços;
- quantidade atual de ações em circulação;
- preço histórico nas datas de referência trimestrais.

Os tickers da B3 são convertidos para o padrão Yahoo:

```text
TICKER_B3 + ".SA"
```

Exemplo:

```text
RDOR3 → RDOR3.SA
```

## 3.3. Sites de Relações com Investidores

São consultadas as páginas de Relações com Investidores das sete companhias.

O sistema procura:

- demonstrações financeiras;
- releases ou relatórios de resultados;
- apresentações de resultados;
- transcrições de webcast, quando disponíveis;
- planilhas de fundamentos ou dados históricos.

## 3.4. PDFs de RI

Quando necessário, os PDFs disponibilizados pelos RIs são baixados, validados, catalogados e convertidos para Markdown.

Esses documentos funcionam como fonte complementar para dados operacionais quando as planilhas de fundamentos não contêm determinada informação.

---

# 4. Seleção e validação dos dados CVM

## 4.1. Identificação das companhias

A identificação das empresas utiliza:

- `CD_CVM`;
- `CNPJ_CIA`;
- `DENOM_CIA`.

O `CD_CVM` é a chave preferencial nos balanços.

O CNPJ funciona como validação e fallback em diferentes módulos.

## 4.2. Reapresentações

Quando existem reapresentações para a mesma companhia e período:

1. utiliza-se `ORDEM_EXERC = ULTIMO`;
2. registros comparativos `PENULTIMO` são descartados quando não são necessários ao cálculo;
3. utiliza-se a maior versão disponível;
4. mantém-se a observação mais recente para uma mesma conta e período.

## 4.3. Ausência de informação

Uma conta não divulgada por determinada companhia permanece:

```text
null
```

ou célula vazia.

Ausência de informação não é interpretada como zero.

---

# 5. Normalização monetária

Os arquivos CVM podem divulgar valores em diferentes escalas.

O sistema utiliza:

| ESCALA_MOEDA | FATOR_ESCALA |
|---|---:|
| UNIDADE | 1 |
| UNIDADES | 1 |
| MIL | 1.000 |
| MILHAR | 1.000 |
| MILHARES | 1.000 |
| MILHAO | 1.000.000 |
| MILHOES | 1.000.000 |

São preservadas duas variáveis:

```text
VL_CONTA_CVM
```

Valor originalmente recebido da CVM.

E:

```text
VL_CONTA
```

Valor convertido para reais integrais.

Fórmula:

```text
VL_CONTA = VL_CONTA_CVM × FATOR_ESCALA
```

Todos os cálculos financeiros posteriores utilizam os valores normalizados.

---

# 6. Estrutura mestra das demonstrações

Balanço Patrimonial, DRE e DFC são padronizados através de uma estrutura mestra de contas.

A lógica é:

```text
União de todos os códigos CVM encontrados
        ↓
Ordenação hierárquica por CD_CONTA
        ↓
Aplicação da mesma estrutura a todas as companhias
```

Se uma empresa não apresentar determinada conta:

```text
valor = null
```

A conta continua presente na estrutura.

Isso garante comparabilidade estrutural entre as empresas.

---

# 7. Metodologia da DRE

## 7.1. Principais contas CVM

| Indicador | Código CVM |
|---|---|
| Receita Líquida | 3.01 |
| Resultado Bruto | 3.03 |
| EBIT | 3.05 |
| Lucro Líquido | 3.11 |

## 7.2. Períodos

Cada período contém:

- data inicial;
- data final;
- ano;
- trimestre;
- indicação de período acumulado.

`is_ytd = true` indica que o período começa em 1º de janeiro.

## 7.3. Quarto trimestre isolado

Quando o quarto trimestre não é divulgado isoladamente, pode ser derivado a partir do resultado anual:

```text
4T = FY - 1T - 2T - 3T
```

onde:

```text
FY = exercício completo
```

O cálculo é realizado conta a conta.

---

# 8. Metodologia da DFC

A DFC pode ser divulgada pelos métodos:

- MD — Método Direto;
- MI — Método Indireto.

O sistema preserva o método identificado.

Quando uma empresa apresenta simultaneamente MD e MI de maneira ambígua para o mesmo período, o sistema evita escolher automaticamente.

## 8.1. Linhas sintéticas

O sistema cria agregações auxiliares.

### Aquisição ou alienação de imobilizado

```text
6.02.AG =
6.02.01 +
6.02.02 +
6.02.03 +
6.02.04
```

### Captação de empréstimos e financiamentos

```text
6.03.CA =
6.03.01 +
6.03.04
```

### Depreciação e amortização

```text
6.01.DA =
6.01.01.02 +
6.01.01.04
```

Linhas calculadas recebem:

```text
synthetic = true
```

---

# 9. Market Cap Atual

## 9.1. Preço da ação

O sistema tenta obter o preço nesta sequência:

1. `fast_info.last_price`;
2. `fast_info.previous_close`;
3. último `Close` disponível no histórico recente.

## 9.2. Número de ações

A prioridade é:

```text
get_shares_full()
```

Fallbacks:

```text
fast_info.shares
sharesOutstanding
impliedSharesOutstanding
```

## 9.3. Fórmula

```text
market_cap = ultimo_preco × acoes_em_circulacao
```

---

# 10. Variação de preço

São calculadas variações aproximadas de 30 e 360 dias.

Fórmula geral:

```text
variacao_pct =
(preco_atual / preco_referencia - 1) × 100
```

Logo:

```text
variacao_30d_pct =
(preco_atual / preco_30d - 1) × 100
```

```text
variacao_360d_pct =
(preco_atual / preco_360d - 1) × 100
```

É utilizado o último fechamento disponível em ou antes da data-alvo.

---

# 11. Market Cap Histórico

## 11.1. Quantidade de ações

Fonte:

```text
CVM — composição do capital
```

Campo:

```text
QT_ACAO_TOTAL_CAP_INTEGR
```

As observações são coletadas para:

- 31/03;
- 30/06;
- 30/09;
- 31/12.

Em reapresentações:

1. prevalece a maior `VERSAO`;
2. em 31/12, o DFP tem precedência sobre eventual ITR equivalente.

## 11.2. Preço histórico

Fonte:

```text
Yahoo Finance — Close
```

Critério:

```text
fechamento da data de referência;
se não houver pregão, último fechamento anterior
```

## 11.3. Fórmula

```text
market_cap_historico =
preco_acao × quantidade_acoes_total
```

---

# 12. Dívida Líquida

## 12.1. Contas utilizadas

| Componente | Código CVM |
|---|---|
| Caixa e equivalentes | 1.01.01 |
| Aplicações financeiras | 1.01.02 |
| Dívida de curto prazo | 2.01.04 |
| Dívida de longo prazo | 2.02.01 |

## 12.2. Dívida bruta

```text
divida_bruta =
divida_curto_prazo +
divida_longo_prazo +
arrendamentos
```

Arrendamentos só entram quando:

```text
include_leases = true
```

## 12.3. Dívida líquida

Fórmula genérica:

```text
divida_liquida =
divida_bruta -
caixa -
aplicacoes_financeiras_deduzidas
```

Na configuração padrão utilizada pelo dashboard:

```text
include_leases = false
deduct_financial_investments = true
```

Assim, atualmente:

```text
divida_liquida_padronizada =
divida_curto_prazo +
divida_longo_prazo -
caixa -
aplicacoes_financeiras_deduzidas
```

---

# 13. Enterprise Value

Fórmula:

```text
enterprise_value =
market_cap_historico +
divida_liquida
```

O cálculo não inclui ajustes adicionais explícitos para:

- participações minoritárias;
- preferred shares;
- participações em coligadas;
- outros ativos financeiros.

---

# 14. EBITDA

Fórmula:

```text
EBITDA =
EBIT +
Depreciacao_Amortizacao
```

A depreciação e amortização é obtida preferencialmente da DFC.

Em períodos acumulados, pode ser derivada por diferença.

Exemplo:

```text
D&A_2T =
D&A_6M -
D&A_3M
```

---

# 15. Margens

Nota da metodologia 2.0: as formulas historicas abaixo devem ser lidas como
formulas genericas. A implementacao atual exige identificacao explicita do
denominador (`receita_para_margens` e `denominador_margens`). Para HAPV3, por
IFRS 17, a conta CVM `3.01` nao deve ser usada automaticamente como denominador
gerencial quando a receita operacional divulgada for a base economica adequada.

## 15.1. Margem Bruta

```text
margem_bruta =
resultado_bruto / receita_liquida × 100
```

## 15.2. Margem Operacional

```text
margem_operacional =
EBIT / receita_liquida × 100
```

## 15.3. Margem EBITDA

```text
margem_ebitda =
EBITDA / receita_liquida × 100
```

## 15.4. Margem Líquida

```text
margem_liquida =
lucro_liquido / receita_liquida × 100
```

Se:

```text
receita_liquida = 0
```

o resultado é:

```text
null
```

---

# 16. EV / EBITDA

Nota da metodologia 2.0: o multiplo principal atual e `ev_ebitda_ltm`, isto e,
EV dividido pelo EBITDA contabil LTM. O campo legado `ev_ebitda`, quando
presente nos JSONs, deve ser interpretado como alias de `ev_ebitda_ltm`. O
sistema nao usa EBITDA trimestral isolado como multiplo principal de valuation
e nao anualiza EBITDA silenciosamente.

Fórmula:

```text
ev_ebitda_ltm =
enterprise_value / ebitda_contabil_ltm
```

O indicador só é calculado quando:

```text
enterprise_value != null
ebitda_contabil_ltm != null
ebitda_contabil_ltm != 0
```

---

# 17. Capital de Giro

O sistema utiliza:

| Conta | Código |
|---|---|
| Ativo Circulante | 1.01 |
| Passivo Circulante | 2.01 |

Fórmula:

```text
capital_giro =
ativo_circulante -
passivo_circulante
```

Metodologicamente, esta variável corresponde ao **Capital Circulante Líquido**, e não ao capital de giro operacional estrito.

## 17.1. Capital de Giro / Receita

```text
capital_giro_percentual_receita =
capital_giro / receita_liquida × 100
```

---

# 18. CAGR

CAGR significa Compound Annual Growth Rate.

Fórmula:

```text
CAGR =
((valor_final / valor_inicial) ^ (1 / anos) - 1) × 100
```

onde:

```text
anos =
(numero_de_observacoes - 1) / periodos_por_ano
```

São calculados:

- CAGR da Receita Líquida;
- CAGR do Lucro Líquido.

Quando:

```text
valor_inicial <= 0
```

ou:

```text
valor_final <= 0
```

o CAGR convencional não é calculado.

---

# 19. Ciclo Financeiro

## 19.1. Contas utilizadas

| Componente | Código CVM |
|---|---|
| Contas a receber | 1.01.03 |
| Estoques | 1.01.04 |
| Fornecedores | 2.01.02 |
| Receita líquida | 3.01 |
| CMV / Custo | 3.02 |

## 19.2. Dias do período

```text
dias =
data_fim -
data_inicio +
1
```

## 19.3. Contas a receber média

```text
contas_a_receber_medio =
(contas_a_receber_inicial +
 contas_a_receber_final) / 2
```

## 19.4. Estoque médio

```text
estoque_medio =
(estoque_inicial +
 estoque_final) / 2
```

## 19.5. Fornecedores médios

```text
fornecedores_medio =
(fornecedores_inicial +
 fornecedores_final) / 2
```

## 19.6. Compras estimadas

O CMV é convertido para módulo:

```text
CMV = abs(conta_3_02)
```

Fórmula:

```text
compras_estimadas =
CMV +
estoque_final -
estoque_inicial
```

## 19.7. PMR

Prazo Médio de Recebimento:

```text
PMR =
contas_a_receber_medio /
receita_liquida ×
dias
```

Unidade:

```text
dias
```

## 19.8. PME

Prazo Médio de Estoque:

```text
PME =
estoque_medio /
CMV ×
dias
```

## 19.9. PMP

Prazo Médio de Pagamento:

```text
PMP =
fornecedores_medio /
compras_estimadas ×
dias
```

## 19.10. Ciclo Financeiro

```text
ciclo_financeiro =
PMR +
PME -
PMP
```

---

# 20. Análise Horizontal

Fórmula:

```text
analise_horizontal_pct =
(valor_atual / valor_periodo_anterior - 1) × 100
```

Se:

```text
valor_atual = null
```

ou:

```text
valor_anterior = null
```

ou:

```text
valor_anterior = 0
```

o resultado é:

```text
null
```

---

# 21. Análise Vertical

## 21.1. Ativo

```text
analise_vertical_pct =
valor_conta /
ativo_total ×
100
```

## 21.2. Passivo e Patrimônio Líquido

```text
analise_vertical_pct =
valor_conta /
passivo_total ×
100
```

O lado do balanço é identificado principalmente pelo primeiro bloco do código CVM.

```text
1.* → Ativo
2.* → Passivo / Patrimônio Líquido
```

---

# 22. Dados Operacionais

As métricas operacionais buscadas pelo extrator são:

```text
Ticket Médio
N. Atendimentos
N. Unidades
N. Pacientes
Receita Bruta
Glosa/PCLD
```

O conjunto operacional fica restrito a essas seis métricas para reduzir falsos positivos e melhorar comparabilidade. Cada observação recebe natureza, escopo, unidade, método de extração, nível de confiança e eventual indicação de revisão. `Receita Bruta` e `Glosa/PCLD` são extraídas pelo mesmo app operacional, mas no dashboard são exibidas junto à DRE, não na tabela operacional geral.

## 22.1. Princípio de não equivalência

O sistema não converte automaticamente métricas conceitualmente diferentes em equivalentes.

Exemplos:

```text
Pacientes-Dia != N. Pacientes
Procedimentos != Atendimentos
Exames != Procedimentos
Leitos != Unidades
Beneficiários != Pacientes
```

Quando determinado indicador não é divulgado, sua série permanece vazia. Proxies só são aceitos quando estiverem explicitamente configurados para a companhia e ficam marcados como `nature = "proxy"`.

```text
serie = []
```

A existência de uma métrica no dicionário não significa que ela foi divulgada por todas as companhias.

## 22.2. Disclaimer dos dados operacionais

Os dados operacionais são capturados de forma experimental.

Eles podem ser extraídos de:

- planilhas de fundamentos;
- releases de resultados;
- apresentações;
- transcrições;
- PDFs convertidos para Markdown.

Como esses documentos não seguem um padrão único entre empresas, períodos e tipos de documento, a captura pode conter:

- dados incompletos;
- classificações incorretas;
- leitura equivocada de tabelas;
- confusão entre indicadores parecidos;
- valores extraídos de contexto narrativo e não de tabela estruturada;
- diferenças de unidade, como milhares, milhões, vidas, atendimentos, exames, leitos ou unidades.

Portanto, os dados operacionais devem ser tratados como apoio exploratório.

Antes de qualquer uso analítico ou decisório, recomenda-se validar os valores contra os documentos originais indicados na aba de auditoria.

## 22.3. Método de localização nas planilhas

O extrator procura rótulos nas primeiras colunas das planilhas utilizando padrões textuais genéricos, o dicionário central `operational_dictionary.py` e, quando necessário, padrões específicos por companhia.

Exemplos de famílias de rótulos aceitos:

| Métrica | Exemplos de rótulos reconhecidos |
|---|---|
| Ticket Médio | ticket medio, average ticket |
| N. Atendimentos | atendimentos, número de atendimentos, volume de atendimentos, consultas |
| N. Unidades | unidades, unidades de atendimento, unidades operacionais, unidades próprias |
| N. Pacientes | pacientes, número de pacientes, pacientes oncológicos |
| Receita Bruta | receita bruta, gross revenue |
| Glosa/PCLD | glosas, PCLD, provisões de crédito/glosas |

Os padrões funcionam como regras de identificação; eles não alteram a definição econômica do dado divulgado.

## 22.3.1. Natureza, confiança e auditoria

Cada observação operacional passa a ser classificada como:

```text
reported   = indicador explicitamente divulgado no rótulo aceito
calculated = indicador calculado a partir de componentes divulgados
proxy      = indicador aproximado aceito apenas quando configurado
```

O item extraído preserva a estrutura legada de `metricas`, `serie`, `escopo` e `unidade`, e acrescenta campos de auditoria:

```text
nature
mapping_type
confidence
confidence_score
requires_review
observations
```

Os níveis determinísticos de confiança são:

```text
HIGH   >= 85
MEDIUM >= 70 e < 85
LOW    < 70
NOT_FOUND = nenhuma observação válida localizada
```

Somente observações HIGH ou MEDIUM alimentam automaticamente o dashboard. Candidatos LOW ficam marcados como `requires_review = true`, permanecem auditáveis e não são usados como dado final.

## 22.3.2. Prioridade de fontes

A prioridade de fontes operacionais é:

```text
1. planilha histórica/fundamentos oficial do RI
2. release ou apresentação convertidos para Markdown
3. outro documento oficial de RI
```

Quando a planilha traz observação HIGH, ela não é substituída por Markdown. Quando a planilha não traz observação válida, o Markdown funciona como complemento. Candidatos alternativos e rejeitados permanecem em auditoria.

## 22.3.3. Proxies permitidos

Os proxies aceitos são específicos por companhia e sempre aparecem como `nature = "proxy"` e `confidence = "medium"`.

Exemplos relevantes:

| Companhia | Métrica | Proxy permitido | Observação |
|---|---|---|---|
| DASA3 | N. Atendimentos | Exames - Total | Proxy aceito porque a operação é predominantemente diagnóstica; exame ainda não é atendimento único |
| FLRY3 | N. Pacientes | Atendimentos | Não representa pacientes únicos |
| MATD3 | N. Atendimentos / N. Pacientes | Pacientes-dia | Não representa pacientes únicos |
| ONCO3 | N. Atendimentos / N. Pacientes | Total de Procedimentos | Não representa pacientes únicos |
| RDOR3 | N. Atendimentos / N. Pacientes | Pacientes-dia | Escopo hospitalar individual |
| RDOR3 | N. Unidades | Hospitais próprios | Proxy de unidades |

## 22.3.4. Avisos operacionais no dashboard

Na aba Dados Operacionais, observações HIGH aparecem sem aviso. Observações MEDIUM aparecem na tabela e geram aviso abaixo dela. Métricas NOT_FOUND ficam vazias/N.A. e geram aviso informativo. Candidatos LOW não aparecem na tabela principal e geram aviso de rejeição quando preservados pela auditoria.

## 22.3. Identificação dos períodos

O extrator reconhece períodos:

```text
1T26
2T26
3T26
4T26
2026
```

e também equivalentes com `Q` ou ano com quatro dígitos.

Para uma linha financeira ou operacional, o programa procura o cabeçalho temporal mais próximo acima da linha e associa cada valor à respectiva coluna de período.

## 22.4. Limite de leitura das planilhas

Para evitar problemas causados por dimensões XML artificialmente infladas em arquivos Excel, cada aba é transformada em um snapshot limitado a:

```text
máximo de 2.000 linhas
máximo de 300 colunas
```

Esse limite é uma restrição operacional do extrator e deve ser considerado caso uma planilha de fundamentos passe a posicionar dados relevantes além desses limites.

## 22.5. Remoção de períodos futuros pré-formatados

Algumas planilhas possuem colunas futuras preenchidas com zero apenas por formatação.

O extrator identifica o período mais recente com ao menos um valor diferente de zero e remove das séries os períodos posteriores a ele.

Assim:

```text
zero em coluna futura pré-formatada
!=
observação econômica efetivamente divulgada
```

## 22.6. Fallback para Markdown

A planilha de fundamentos é a fonte preferencial.

Quando uma métrica não é encontrada na planilha, o sistema pode buscar a informação nos Markdown gerados pelo `app_parser_operacional.py`.

Fluxo:

```text
Planilha de fundamentos
        ↓
métrica encontrada?
   ├─ sim → preserva a série da planilha
   └─ não → procura nos Markdown de releases/relatórios
```

Se a própria planilha falhar completamente, o extrator pode construir o JSON apenas com dados encontrados nos Markdown, registrando:

```text
fonte_planilha = null
fonte_alternativa = "Markdown gerado pelo app_parser_operacional.py"
erro_planilha = motivo da falha
```

O fallback pode ser desativado com:

```text
--no-md-fallback
```

e os Markdown podem ser regenerados antes da extração com:

```text
--force-md-parser
```

## 22.7. Tratamento de valores no Markdown

O parser de Markdown:

- reconhece períodos trimestrais e anuais;
- ignora percentuais quando está procurando valores absolutos;
- interpreta números no padrão brasileiro;
- reconhece valores negativos entre parênteses;
- em linhas isoladas, pode reconhecer escala textual subsequente.

Exemplos:

```text
10 milhões → 10.000.000
250 mil → 250.000
```

Quando a escala não é explicitamente identificada no contexto, o valor é preservado conforme lido.

---

# 23. Regras Operacionais Específicas por Companhia

A busca operacional ativa inclui:

```text
Ticket Médio
N. Atendimentos
N. Unidades
N. Pacientes
Receita Bruta
Glosa/PCLD
```

Essas métricas são controladas pelo módulo `operational_dictionary.py`, que centraliza aliases, rótulos preferidos, proxies permitidos, escopos aceitos e contextos proibidos. A existência de uma regra não obriga preenchimento: se o documento não divulgar a métrica com evidência suficiente, a série permanece vazia.

## 23.1. RDOR3

Para `Receita Bruta`, a planilha de fundamentos deve estar no contexto:

```text
Hospitais, oncologia e outros
```

Para `Glosa/PCLD`, é priorizado o contexto consolidado divulgado pela companhia.

Nos documentos textuais da Rede D'Or, o extrator procura manter o escopo
hospitalar/oncológico e rejeitar contextos associados a:

```text
SulAmérica
seguros e previdência
eliminações
ajustes
pro forma
```

`RDOR3` permanece explícita como escopo individual/hospitalar na camada operacional. Dados da SulAmérica não alimentam os seis indicadores operacionais usados no dashboard.

## 23.2. FLRY3

Para `N. Unidades`, utiliza a linha:

```text
Medicina Diagnóstica
```

quando localizada dentro do bloco:

```text
Número de Unidades
```

Para `N. Atendimentos`, prioriza linhas explicitamente denominadas:

```text
Atendimentos
```

`Receita Bruta por Exame` pode ser usada apenas quando o rótulo representar diretamente `Ticket Médio`. Exames por atendimento não transformam automaticamente exames em atendimentos.

Quando a companhia não publica uma linha explícita de `Ticket Médio`, o indicador
pode ser calculado por:

```text
ticket_medio =
receita_bruta_R$_mil /
atendimentos_mil
```

A saída registra:

```text
calculado = true
formula = "Receita Bruta (R$ milhares) / Atendimentos (milhares)"
```

## 23.3. MATD3

Para `N. Pacientes`, prioriza:

```text
Pacientes oncológicos
Pacientes
```

`Pacientes-dia` não é tratado como paciente único. Para MATD3, pode ser aceito apenas como proxy configurado quando a companhia divulga essa base operacional, sempre com `nature = "proxy"`.

## 23.4. DASA3

Mapeamento de abas:

| Aba | Escopo |
|---|---|
| 1 | Consolidado |
| 2 | Diagnósticos Nacional |
| 3 | Hospitais/Onco NE |
| 4 | Américas |

Os segmentos operacionais são mantidos separados quando necessário.

Para `Receita Bruta` e `Glosa/PCLD`, a aba consolidada é priorizada.

Em diagnósticos, o sistema procura apenas os seis indicadores ativos. Em hospitais e oncologia, métricas fora desse conjunto não alimentam automaticamente o dashboard. Os escopos não são misturados.

## 23.5. ONCO3

Para:

```text
Receita Bruta
Glosa/PCLD
```

é priorizada:

```text
DRE Trimestral
```

Procedimentos ou tratamentos só podem aparecer como proxy de `N. Atendimentos` ou `N. Pacientes` quando a regra da companhia permitir e sempre com `nature = "proxy"`.

## 23.6. HAPV3

Para `N. Unidades`, `N. Pacientes`, `Receita Bruta` e `Glosa/PCLD`, o valor
somente deve ser aceito quando estiver claramente rotulado em planilha de
fundamentos, release ou documento oficial de RI.

PDD, reversão de glosa e glosa recorrente não são somados automaticamente quando a companhia não apresentar uma definição explícita.

Como HAPV3 tem tratamento específico de IFRS 17, `Receita Bruta` e qualquer
receita operacional/gerencial extraída de RI não substituem a receita contábil
CVM `3.01`; elas ficam em camada separada para análise gerencial.

Essas regras são heurísticas de identificação dos rótulos divulgados pela companhia; o valor continua sendo armazenado com a fonte original em `fonte_linha` e `escopo`.

---

## 23.7. Camada Comparativo

A aba `Comparativo` mostra simultaneamente as sete companhias acompanhadas:

```text
AALR3
DASA3
FLRY3
HAPV3
MATD3
ONCO3
RDOR3
```

Ela consome os JSONs já produzidos pelo sistema e não cria metodologia financeira ou operacional nova.

### 23.7.1. Métricas da tabela comparativa

A tabela possui exatamente 11 métricas:

| Métrica | Fonte | Seleção temporal |
|---|---|---|
| CAGR Receita | `indicadores.json` | mesma janela anual usada no dashboard individual |
| CAGR Lucros | `indicadores.json` | mesma janela anual usada no dashboard individual |
| Ciclo Financeiro | `ciclo_financeiro.json` | último exercício anual completo |
| Margem Bruta | `indicadores.json` | último exercício anual completo |
| Margem Operacional | `indicadores.json` | último exercício anual completo |
| Margem EBITDA | `indicadores.json` | último exercício anual completo |
| Margem Líquida | `indicadores.json` | último exercício anual completo |
| EV/EBITDA | `indicadores.json` | último trimestre com `ev_ebitda_ltm` válido |
| Delta Preço da Ação 30 dias | `market_cap.json` | snapshot atual, campo `variacao_30d_pct` |
| Delta Preço da Ação 360 dias | `market_cap.json` | snapshot atual, campo `variacao_360d_pct` |
| N. Unidades | `dados_operacionais` | período operacional válido mais recente |

Cada célula pode ter seu próprio período. O comparativo não força uma data comum entre métricas que possuem naturezas temporais diferentes.

### 23.7.2. CAGR

O CAGR do comparativo usa a mesma regra da visão individual:

```text
CAGR = (valor_final / valor_inicial) ^ (1 / anos) - 1
```

A janela é determinada pelos registros anuais disponíveis para cada companhia. Se não houver base válida, o valor permanece `N/A`.

### 23.7.3. Gráficos históricos

Somente métricas que fazem sentido como série temporal recebem gráfico:

```text
Ciclo Financeiro
Margem Bruta
Margem Operacional
Margem EBITDA
Margem Líquida
```

Os cinco gráficos comparativos são gerados a partir dos dados anuais comparáveis já presentes nos JSONs finais. O `EV/EBITDA LTM` permanece disponível na tabela comparativa, mas não é exibido como gráfico nessa aba.

Não há gráfico para:

```text
CAGR Receita
CAGR Lucros
Delta Preço da Ação 30 dias
Delta Preço da Ação 360 dias
N. Unidades
EV/EBITDA LTM
```

### 23.7.4. EV/EBITDA histórico

O EV/EBITDA histórico reutiliza o campo já calculado:

```text
ev_ebitda_ltm
```

Esse campo é produzido a partir da metodologia existente:

```text
EV(t) = Market Cap Histórico(t) + Dívida Líquida Padronizada(t)
EV/EBITDA LTM(t) = EV(t) / EBITDA Contábil LTM(t)
```

O comparativo apenas seleciona e apresenta na tabela os períodos onde o valor já existe. Quando os componentes não estão disponíveis ou não são comparáveis, o valor permanece ausente e não é convertido em zero.

### 23.7.4.1. Gráficos como artefatos derivados

Os gráficos do Acompanhador de Mercado são artefatos derivados dos JSONs financeiros, operacionais e de indicadores. Eles não são fonte primária de dados, não substituem os JSONs publicados e não alteram qualquer metodologia de cálculo.

No fluxo automatizado, o GitHub Actions gera os PNGs com Matplotlib depois da atualização dos dados e antes da publicação no repositório público de dados. O manifesto publicado registra os caminhos dos PNGs permitidos e uma versão de dados para controle de cache. O dashboard remoto consome esses PNGs versionados como imagens estáticas, evitando gerar gráficos dinamicamente no Render durante o carregamento normal.

Se um PNG não estiver presente no manifesto publicado, o dashboard mostra o gráfico como indisponível para aquela atualização, sem criar dados fictícios e sem recalcular métricas no frontend.

### 23.7.5. N. Unidades

`N. Unidades` vem da mesma métrica operacional usada na visão individual. O comparativo não reinterpreta hospitais, clínicas ou outros proxies nesta camada.

Regras:

```text
HIGH   -> mostra normalmente
MEDIUM -> mostra com indicação discreta de confiança média
LOW    -> não mostra como valor válido
NOT_FOUND -> N/A
```

### 23.7.6. N/A e quality flags

Ausências são exibidas como `N/A`. Valores `null` não são convertidos em zero.

Quality flags como:

```text
incomplete
not_comparable
methodology_difference
requires_review
```

são preservadas em campos de qualidade e podem aparecer como indicação discreta/tooltip na interface.

---

# 24. Download e catalogação de PDFs

Os PDFs são catalogados por:

```text
ticker
empresa
periodo
ano
tipo
titulo_original
url_origem
url_documento
```

Padrão de nome:

```text
TICKER_PERIODO_TIPO.pdf
```

Exemplo:

```text
RDOR3_2T26_RELEASE_RESULTADOS.pdf
```

## 24.1. Validação

O arquivo é considerado PDF quando:

```text
Content-Type contém application/pdf
```

ou:

```text
arquivo começa com bytes "%PDF"
```

## 24.2. Hash

Cada documento recebe um hash:

```text
SHA-256
```

utilizado como identificador de integridade.

---

# 25. Conversão de PDF para Markdown

Os PDFs são convertidos utilizando:

```text
PyMuPDF
PyMuPDF4LLM
```

O Markdown gerado pode conter:

- texto;
- tabelas;
- estrutura por página;
- metadados;
- imagens extraídas.

Os arquivos Markdown podem servir como fonte complementar ao extrator operacional.

---

# 26. Orquestração do pipeline

A atualização completa executa aproximadamente:

```text
1. app_balancos.py
2. app_dre.py
3. app_dfc.py
4. app_parser_operacional.py
5. app_extrator_operacional.py
6. app_divida_liquida.py
7. app_ciclo_financeiro.py
8. app_market_cap.py
9. app_market_cap_historico.py
10. app_indicadores.py
11. dashboard.py consome os JSONs
```

O `app_AV_AH.py` continua existindo como módulo independente e não é chamado pelo `run_full_update()`.

Entretanto, o dashboard atual **calcula AV/AH diretamente na camada de apresentação**, sem depender do JSON gerado por `app_AV_AH.py`.

Na visão do dashboard:

```text
AH =
(valor_atual / valor_periodo_anterior - 1) × 100
```

Para o Balanço Patrimonial:

```text
AV_ativo =
valor_conta / ativo_total × 100
```

```text
AV_passivo =
valor_conta / passivo_total × 100
```

Para a DRE:

```text
AV_DRE =
valor_conta / receita_liquida_3.01 × 100
```

Assim, existe uma diferença de escopo entre os dois componentes:

- `app_AV_AH.py`: AV para BP e AH para BP/DRE;
- `dashboard.py`: exibe AV e AH tanto para BP quanto para DRE.

A análise horizontal do dashboard compara sempre com o **período anterior exibido na visão selecionada**.

---

## 26.1. Visões anual e trimestral no dashboard

O dashboard organiza demonstrações e indicadores em visões anual e trimestral.

Para fluxos como DRE e DFC, quando a série disponível é acumulada e a visão trimestral exige um trimestre isolado, o dashboard pode calcular:

```text
valor_trimestre_atual =
valor_acumulado_atual -
valor_acumulado_anterior
```

Exemplo:

```text
2T isolado =
6M acumulado -
3M acumulado
```

O 1T não necessita desse ajuste porque o acumulado de janeiro a março coincide com o trimestre isolado.

O Balanço Patrimonial não passa por essa transformação porque representa estoque em uma data, não fluxo acumulado.

## 26.2. Tabela operacional no dashboard

O dashboard utiliza uma lista fechada de métricas operacionais para reduzir falsos positivos:

```text
Ticket Médio
N. Atendimentos
N. Unidades
N. Pacientes
```

`Receita Bruta` e `Glosa/PCLD` também são extraídas pelo app operacional, mas possuem tratamento próprio e são exibidas junto à DRE. A tabela operacional separa períodos anuais (`YYYY`) de períodos trimestrais (`nTYY`) e não adiciona dinamicamente outras métricas.

## 26.3. Exportação HTML

O dashboard suporta exportação para HTML estático por duas formas:

```text
--export-html CAMINHO
```

ou pelo endpoint:

```text
/export/dashboard.html
```

A exportação utiliza o mesmo payload de dados e as mesmas regras de visualização do dashboard.

---

# 27. Dicionário de Dados

## 27.1. Identificação da companhia

| Variável | Definição |
|---|---|
| ticker | Ticker da companhia na B3 |
| ticker_b3 | Ticker B3 |
| ticker_yahoo | Ticker utilizado no Yahoo Finance |
| empresa | Nome comercial |
| DENOM_CIA | Denominação CVM |
| CNPJ_CIA | CNPJ da companhia |
| CD_CVM | Código CVM |
| scope | Escopo dos demonstrativos |
| escopo | Escopo ou segmento |
| TIPO_DRE | Tipo de DRE utilizado |

## 27.2. Identificação dos documentos CVM

| Variável | Definição |
|---|---|
| DOCUMENTO_CVM | ITR ou DFP |
| ANO_ARQUIVO | Ano do ZIP de origem |
| DT_REFER | Data de referência |
| VERSAO | Versão do formulário |
| VERSAO_NUM | Versão em formato numérico |
| GRUPO_DFP | Grupo da demonstração |
| ORDEM_EXERC | Atual ou comparativo |
| ST_CONTA_FIXA | Identificador de conta fixa |
| DEMONSTRACAO | BPA, BPP, DRE ou DFC |
| METODO_DFC | MD ou MI |

## 27.3. Contas contábeis

| Variável | Definição |
|---|---|
| CD_CONTA | Código hierárquico CVM |
| DS_CONTA | Descrição da conta |
| CONTA_CHAVE | Chave interna da conta |
| code | Código normalizado |
| description | Descrição normalizada |
| account_type | Conta fixa ou não fixa |
| synthetic | Linha calculada |
| source_codes | Contas que originaram uma linha sintética |
| values | Série período → valor |

## 27.4. Valores monetários

| Variável | Definição |
|---|---|
| MOEDA | Moeda da demonstração |
| ESCALA_MOEDA | Escala original |
| FATOR_ESCALA | Multiplicador de normalização |
| VL_CONTA_CVM | Valor original CVM |
| VL_CONTA | Valor em reais integrais |
| unit | Unidade do JSON |

## 27.5. Períodos

| Variável | Definição |
|---|---|
| periodo | Identificação do período |
| periods | Lista dos períodos |
| DT_INI_EXERC | Data inicial |
| DT_FIM_EXERC | Data final |
| DIAS_PERIODO | Dias inclusivos |
| start_date | Data inicial normalizada |
| end_date | Data final normalizada |
| year | Ano |
| quarter | Trimestre |
| is_ytd | Período acumulado desde janeiro |
| derived | Origem de período calculado |
| period_metadata | Metadados do período |

## 27.6. DRE e Indicadores

| Variável | Definição |
|---|---|
| receita_liquida | Conta CVM 3.01 |
| resultado_bruto | Conta CVM 3.03 |
| ebit | Conta CVM 3.05 |
| depreciacao_amortizacao | D&A |
| fonte_depreciacao_amortizacao | Origem da D&A |
| ebitda | EBIT + D&A |
| lucro_liquido | Conta CVM 3.11 |
| margem_bruta | Resultado Bruto / Receita × 100 |
| margem_operacional | EBIT / Receita × 100 |
| margem_ebitda | EBITDA / Receita × 100 |
| margem_liquida | Lucro Líquido / Receita × 100 |
| capital_giro | AC − PC |
| capital_giro_percentual_receita | Capital de Giro / Receita × 100 |
| market_cap_historico | Preço histórico × ações |
| divida_liquida | Dívida financeira menos deduções |
| enterprise_value | Market Cap + Dívida Líquida |
| ev_ebitda | EV / EBITDA |
| fonte_ev_ebitda | Origem dos componentes |

## 27.7. CAGR

| Variável | Definição |
|---|---|
| cagr_ultimos_5_periodos_percentual | Bloco de CAGR |
| receita_liquida | CAGR da Receita |
| lucro_liquido | CAGR do Lucro |
| observacoes_utilizadas | Número de observações |
| periodos_por_ano | Frequência temporal |
| base | Base temporal utilizada |
| erros | Motivo de cálculo indisponível |

## 27.8. Dívida Líquida

| Variável | Definição |
|---|---|
| short_term_debt | Dívida de curto prazo |
| long_term_debt | Dívida de longo prazo |
| leases_included | Arrendamentos incluídos |
| gross_debt | Dívida bruta |
| cash_and_cash_equivalents | Caixa |
| financial_investments_identified | Aplicações identificadas |
| financial_investments_deducted | Aplicações deduzidas |
| value | Dívida líquida |
| deduct_financial_investments | Flag de dedução |
| include_leases | Flag de inclusão de leases |
| audit | Contas utilizadas |

## 27.9. Ciclo Financeiro

| Variável | Definição |
|---|---|
| CMV | Custo da conta 3.02 em módulo |
| estoque_inicial | Estoque de abertura |
| estoque_final | Estoque final |
| estoque_medio | Média dos estoques |
| contas_a_receber_medio | Média de recebíveis |
| fornecedores_medio | Média de fornecedores |
| compras_estimadas | CMV + Estoque final − Estoque inicial |
| PMR | Prazo Médio de Recebimento |
| PME | Prazo Médio de Estoque |
| PMP | Prazo Médio de Pagamento |
| ciclo_financeiro | PMR + PME − PMP |
| bp_inicial | Data de BP inicial |
| bp_final | Data de BP final |

## 27.10. Market Cap Atual

| Variável | Definição |
|---|---|
| ultimo_preco | Último preço identificado |
| acoes_em_circulacao | Número atual de ações |
| data_acoes | Data da quantidade de ações |
| market_cap | Preço × ações |
| preco_30d | Preço de referência 30 dias |
| data_30d | Data efetiva da referência |
| variacao_30d_pct | Variação de 30 dias |
| preco_360d | Preço de referência 360 dias |
| data_360d | Data efetiva |
| variacao_360d_pct | Variação de 360 dias |
| fonte_preco | Fonte Yahoo usada |
| fonte_acoes | Fonte das ações |
| timestamp_extracao_utc | Timestamp UTC |
| timestamp_extracao_brasilia | Timestamp Brasília |
| erro | Erro de consulta |

## 27.11. Market Cap Histórico

| Variável | Definição |
|---|---|
| data_referencia | Data trimestral |
| quantidade_acoes_total | QT_ACAO_TOTAL_CAP_INTEGR |
| fonte_documento | ITR ou DFP |
| preco_acao | Close histórico |
| data_preco | Data do pregão |
| market_cap | Preço × ações |
| versao | Versão CVM |
| denominacao | Nome CVM |

## 27.11.1. Campos metodologicos da versao 2.0

Quando houver divergencia entre campos legados e campos 2.0, a leitura
metodologica correta deve priorizar os campos 2.0. Os aliases legados sao
mantidos para compatibilidade visual e tecnica.

### DRE e indicadores

| Variavel | Definicao |
|---|---|
| methodology_version | Versao metodologica usada no calculo |
| receita_liquida | Alias legado da conta CVM 3.01 |
| receita_contabil_cvm | Conta CVM 3.01 preservada como dado contabil oficial |
| receita_operacional_divulgada | Receita gerencial divulgada oficialmente, quando extraida |
| receita_para_margens | Receita usada como denominador das margens, quando comparavel |
| denominador_margens | Descricao da receita usada como denominador |
| ebitda | Alias legado de EBITDA contabil calculado |
| ebitda_contabil | EBIT CVM 3.05 + depreciacao e amortizacao da DFC |
| ebitda_ajustado_divulgado | EBITDA ajustado oficialmente divulgado pela companhia |
| diferenca_ebitda_ajustado_vs_contabil | Diferenca absoluta entre ajustado e contabil |
| diferenca_pct_ebitda_ajustado_vs_contabil | Diferenca percentual entre ajustado e contabil |
| ebitda_contabil_ltm | Soma dos quatro ultimos trimestres individuais comparaveis |
| periodo_individual | Metadados e valores reconstruidos do trimestre isolado |
| margem_ebitda | Alias legado de margem EBITDA contabil |
| margem_ebitda_contabil | EBITDA contabil / receita utilizada * 100 |
| ev | Alias de enterprise value |
| enterprise_value | Market cap historico + divida liquida padronizada |
| ev_ebitda | Alias legado de EV/EBITDA LTM |
| ev_ebitda_ltm | EV / EBITDA contabil LTM |
| data_market_cap | Data do market cap usado no EV historico |
| data_divida_liquida | Data da divida liquida usada no EV historico |
| data_ebitda_ltm | Data-base do EBITDA LTM |
| quality_ev_ebitda_ltm | Status e avisos especificos do multiplo |
| quality_flags | Lista de alertas metodologicos e de comparabilidade |

### Divida liquida

| Variavel | Definicao |
|---|---|
| metric | `divida_liquida_padronizada` |
| value | Alias legado da divida liquida padronizada |
| divida_bruta | Emprestimos CP + emprestimos LP + arrendamentos incluidos |
| caixa_equivalentes | Caixa e equivalentes identificados no BP |
| aplicacoes_financeiras_identificadas | Aplicacoes financeiras localizadas no BP |
| aplicacoes_financeiras_deduzidas | Aplicacoes efetivamente deduzidas pelo criterio vigente |
| arrendamentos_incluidos | Arrendamentos incluidos quando `include_leases = true` |
| divida_liquida_padronizada | Divida bruta - caixa - aplicacoes deduzidas |
| divida_liquida_divulgada | Divida liquida oficial divulgada pela companhia, quando extraida |
| diferenca | Diferenca entre padronizada e divulgada, quando aplicavel |
| metodologia | Formula, versao e opcoes metodologicas aplicadas |
| quality | Status e avisos de qualidade |

### Reconciliacao

| Variavel | Definicao |
|---|---|
| relatorio_reconciliacao.json | Relatorio tecnico CVM versus RI/divulgado |
| MATCH | Diferenca dentro do limite de arredondamento |
| IMMATERIAL_DIFFERENCE | Diferenca pequena, abaixo do limite de revisao |
| METHODOLOGY_DIFFERENCE | Diferenca esperada por definicao diferente |
| MATERIAL_DIFFERENCE | Diferenca material a investigar |
| MISSING_DATA | Uma ou ambas as fontes estao ausentes |
| NOT_COMPARABLE | Escopo ou metodologia nao comparavel |

## 27.12. Análise Vertical e Horizontal

| Variável | Definição |
|---|---|
| analise_horizontal_pct | Variação percentual entre períodos |
| analise_vertical_pct | Participação percentual no total do BP |
| codigo | Código da conta |
| descricao | Descrição da conta |
| valor | Valor financeiro |
| inicio_periodo | Data inicial |

## 27.13. Dados Operacionais

| Variável | Definição |
|---|---|
| Ticket Médio | Ticket divulgado ou calculado |
| N. Atendimentos | Quantidade de atendimentos ou indicador equivalente explicitamente rotulado como atendimento/consulta |
| N. Unidades | Número de unidades conforme definição divulgada pela companhia |
| N. Pacientes | Quantidade de pacientes; não incorpora automaticamente pacientes-dia |
| Receita Bruta | Receita bruta operacional segundo a regra de companhia |
| Glosa/PCLD | Glosas e/ou provisões de crédito conforme divulgação |
| escopo | Segmento, aba ou contexto da fonte |
| fonte_linha | Linha original que originou a série |
| unidade | Unidade associada à métrica |
| calculado | Indica se o valor foi produzido por fórmula |
| formula | Fórmula utilizada quando `calculado = true` |
| serie | Série período → valor |
| fonte_planilha | URL ou caminho da planilha utilizada |
| arquivo_fundamentos | Nome do arquivo de fundamentos |
| fonte_documento | Markdown/release que originou a observação alternativa |
| fonte_alternativa | Descrição da fonte alternativa |
| erro_planilha | Erro da planilha quando o Markdown foi usado como fallback |
| extraido_em_utc | Timestamp da extração |


## 27.14. PDFs e documentos de RI

| Variável | Definição |
|---|---|
| ticker | Companhia |
| empresa | Nome da companhia |
| periodo | Período |
| ano | Ano |
| tipo | Tipo de documento |
| titulo_original | Título original |
| url_origem | Página RI |
| url_documento | Link do PDF |
| arquivo_local | Caminho local |
| nome_arquivo | Nome padronizado |
| sha256 | Hash do documento |
| baixado_em | Timestamp |
| status | Status do download |
| numero_paginas | Número de páginas |
| titulo | Metadado do PDF |
| autor | Autor |
| assunto | Assunto |
| criador | Criador |
| produtor | Produtor |
| palavras_chave | Keywords |
| quantidade_imagens | Número de imagens |
| ocr_habilitado | Disponibilidade de OCR |
| ocr_forcado | OCR obrigatório |
| idioma_ocr | Idioma do OCR |
| estrategia_tabelas | Método de extração de tabelas |

---

# 28. Pontos Metodológicos Críticos

## 28.1. Valores monetários

Todos os cálculos financeiros usam valores convertidos para reais integrais.

## 28.2. Valores ausentes

Ausência de dado não é substituída por zero.

## 28.3. RDOR3

Rede D'Or utiliza demonstrativos individuais.

## 28.4. Capital de Giro

O indicador atualmente chamado de Capital de Giro corresponde a:

```text
Ativo Circulante - Passivo Circulante
```

Tecnicamente, trata-se de Capital Circulante Líquido.

## 28.5. Dívida Líquida

Na execução padrão atual:

```text
aplicações financeiras identificadas são deduzidas quando enquadradas na configuracao padrao
arrendamentos não são incluídos
```

## 28.6. Métricas operacionais

O sistema evita converter indicadores operacionalmente diferentes em métricas equivalentes.

## 28.7. Contas ausentes

Contas não divulgadas permanecem `null`.


## 28.8. Escopo controlado de métricas operacionais

A busca operacional automática é controlada pelo dicionário central `operational_dictionary.py` e cobre apenas: `Ticket Médio`, `N. Atendimentos`, `N. Unidades`, `N. Pacientes`, `Receita Bruta` e `Glosa/PCLD`.

Somente observações com confiança HIGH ou MEDIUM alimentam automaticamente o dashboard. Candidatos LOW permanecem como material de auditoria/revisão.

A nomenclatura e o escopo divulgados por cada RI permanecem parte da definição da observação.

## 28.9. Fallback documental

Dados encontrados em Markdown são utilizados apenas quando a métrica correspondente não foi obtida na planilha ou quando a planilha falha.

A fonte alternativa deve permanecer auditável através de:

```text
fonte_documento
fonte_linha
fonte_alternativa
erro_planilha
```

## 28.10. AV/AH do dashboard

A AV/AH exibida no dashboard é calculada dinamicamente na interface e não depende do `app_AV_AH.py`.

Para a DRE, a base da análise vertical é a Receita Líquida (`3.01`).

---

# 29. Contrato para Incorporação em HTML

Ao converter este documento em HTML, recomenda-se preservar os seguintes IDs ou equivalentes semânticos:

```text
metodologia-overview
fontes-dados
normalizacao
dre
dfc
market-cap
market-cap-historico
divida-liquida
enterprise-value
ebitda
margens
capital-giro
cagr
ciclo-financeiro
analise-horizontal
analise-vertical
dados-operacionais
regras-por-companhia
dashboard-visualizacao
dicionario-dados
pontos-metodologicos-criticos
```

Sugestão de estrutura HTML:

```html
<section id="metodologia-overview">...</section>
<section id="fontes-dados">...</section>
<section id="calculos">...</section>
<section id="dados-operacionais">...</section>
<section id="dicionario-dados">...</section>
<section id="pontos-metodologicos-criticos">...</section>
```

Para fórmulas, utilizar preferencialmente:

```html
<code>...</code>
```

ou:

```html
<pre><code>...</code></pre>
```

Para tabelas, manter cabeçalhos semânticos:

```html
<table>
  <thead>...</thead>
  <tbody>...</tbody>
</table>
```

---

# 30. Resumo do Pipeline

```text
CVM
 ├─ Balanço Patrimonial
 ├─ DRE
 ├─ DFC
 └─ Composição do Capital

Yahoo Finance
 ├─ Preço Atual
 ├─ Preço Histórico
 └─ Ações em Circulação

Relações com Investidores
 ├─ Planilhas de Fundamentos
 ├─ Releases
 ├─ Apresentações
 ├─ Demonstrações Financeiras
 └─ Transcrições

Dados operacionais
 - Ticket Médio
 - Atendimentos
 - Unidades
 - Pacientes
 - Receita Bruta
 - Glosa/PCLD

        ↓

Normalização e validação

        ↓

JSONs

        ↓

Indicadores
 ├─ EBITDA
 ├─ Margens
 ├─ CAGR
 ├─ Dívida Líquida
 ├─ Market Cap
 ├─ Enterprise Value
 ├─ EV/EBITDA
 ├─ Capital de Giro
 ├─ PMR
 ├─ PME
 ├─ PMP
 └─ Ciclo Financeiro

        ↓

dashboard.py

        ↓

HTML / interface final
```

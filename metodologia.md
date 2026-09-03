---
title: "Metodologia do Acompanhador de Mercado"
version: "4.0"
date: "2026-09-03"
language: "pt-BR"
purpose: "Premissas, fontes, fórmulas, critérios de qualidade e limitações analíticas"
---

# Metodologia do Acompanhador de Mercado

> **Atualização metodológica 4.0 — 03/09/2026**
>
> Esta versão incorpora as mudanças recentes do pipeline. A quantidade histórica
> de ações é buscada primeiro no Yahoo Finance e comparada com a CVM. Diferenças
> superiores a 5% recebem o status `shares_discrepancy`; os dois valores ficam
> preservados para auditoria e o market cap, EV e EV/EBITDA do período não são
> calculados automaticamente. Se o Yahoo não fornecer uma quantidade válida, a
> CVM é usada como fallback.
>
> A regra financeira é idêntica para Saúde e Construção Civil. A separação por
> setor aplica-se somente ao bloco operacional: Saúde pode usar planilhas e
> documentos de RI; Construção Civil usa exclusivamente PDFs oficiais de RI.
>
> O tracking transversal registra descoberta, importação, conversão, leitura,
> resolução, parsing, validação, publicação e preservação de cada documento.
> Os contadores de documentos são derivados dos eventos, inclusive quando um
> documento foi processado sem gerar observações.

## 1. Objetivo e princípios

O Acompanhador de Mercado consolida informações financeiras, de mercado e, no setor de saúde, operacionais para permitir comparação histórica e entre companhias abertas.

A metodologia prioriza cinco princípios:

1. **fonte oficial antes de estimativa**: demonstrações financeiras da CVM são a base dos dados contábeis; documentos de RI complementam dados operacionais e métricas divulgadas;
2. **ausência não é zero**: informações não encontradas permanecem nulas ou indisponíveis;
3. **comparabilidade antes de completude artificial**: métricas conceitualmente diferentes não são tratadas como equivalentes sem regra explícita;
4. **separação entre reportado e calculado**: valores divulgados pelas companhias não substituem silenciosamente indicadores padronizados calculados pelo modelo;
5. **rastreabilidade**: sempre que possível, valores derivados preservam período, componentes, fonte e sinais de qualidade.

O modelo cobre dois setores:

- **Saúde**, com dados financeiros, de mercado e operacionais;
- **Construção Civil**, com dados financeiros e de mercado.

As companhias acompanhadas são definidas no cadastro central do modelo. O escopo contábil é, em regra, **consolidado**; a principal exceção é **RDOR3**, cujos demonstrativos financeiros são tratados no escopo **individual**.

---

# 2. Fontes e insumos

## 2.1. CVM

A CVM é a fonte primária das demonstrações financeiras.

São utilizados principalmente:

- **ITR** — Informações Trimestrais;
- **DFP** — Demonstrações Financeiras Padronizadas;
- Balanço Patrimonial Ativo e Passivo;
- DRE;
- DFC;
- composição do capital.

### Seleção das observações

Quando existem reapresentações ou versões concorrentes:

1. prioriza-se `ORDEM_EXERC = ULTIMO`;
2. utiliza-se a maior versão disponível;
3. registros comparativos `PENULTIMO` são descartados quando representam apenas repetição do período anterior, mas podem ser usados quando necessários para obter saldos iniciais;
4. em 31/12, a DFP prevalece sobre uma observação equivalente de ITR quando aplicável.

### Normalização monetária

Os valores são convertidos para reais integrais:

```text
valor_normalizado = valor_CVM × fator_de_escala
```

Principais escalas:

| Escala CVM | Fator |
|---|---:|
| Unidade | 1 |
| Mil / Milhar | 1.000 |
| Milhão | 1.000.000 |

Todos os cálculos posteriores utilizam o valor normalizado.

---

## 2.2. Yahoo Finance

O Yahoo Finance é utilizado para:

- preço atual da ação;
- histórico de fechamentos;
- quantidade atual de ações em circulação, quando necessária ao market cap atual.

A prioridade para preço atual é:

1. último preço disponível;
2. fechamento anterior;
3. último fechamento válido do histórico recente.

Quando se busca uma data histórica sem pregão, utiliza-se o **último fechamento disponível em ou antes da data-alvo**.

---

## 2.3. Relações com Investidores

Documentos oficiais de RI são usados principalmente para:

- indicadores operacionais;
- métricas ajustadas divulgadas;
- validação e reconciliação;
- complementação de informações não estruturadas.

As fontes preferidas são, nesta ordem:

1. planilhas históricas ou de fundamentos divulgadas pela companhia;
2. releases e apresentações de resultados;
3. outros documentos oficiais de RI.

PDFs podem ser convertidos para texto estruturado para permitir busca e extração, mas a informação continua sendo tratada como proveniente do documento original.

---

# 3. Períodos e comparabilidade temporal

O modelo trabalha com:

- períodos anuais;
- períodos trimestrais;
- séries LTM quando quatro trimestres comparáveis estão disponíveis.

Para fluxos de DRE e DFC, valores trimestrais isolados podem ser reconstruídos quando a companhia divulga acumulados:

```text
1T = 3M
2T = 6M - 3M
3T = 9M - 6M
4T = FY - 9M
```

Não há anualização silenciosa de um único trimestre.

O Balanço Patrimonial não é transformado dessa forma, pois representa um estoque em determinada data.

---

# 4. Métricas financeiras centrais

## 4.1. Receita e margens

A conta contábil de receita utilizada como referência geral é a CVM `3.01`.

As principais margens são:

```text
Margem Bruta = Resultado Bruto / Receita
Margem Operacional = EBIT / Receita
Margem EBITDA = EBITDA Contábil / Receita
Margem Líquida = Lucro Líquido / Receita
```

Se o denominador for zero, ausente ou metodologicamente inadequado, a margem fica indisponível.

### HAPV3 e IFRS 17

Para HAPV3, a receita contábil CVM permanece disponível como dado oficial, mas pode não ser o denominador econômico mais comparável para análise gerencial após IFRS 17.

Quando a receita operacional/gerencial adequada não estiver disponível com confiança suficiente, margens dependentes dessa base podem ser classificadas como **incompletas** ou **não comparáveis**, em vez de calculadas sobre um denominador inadequado.

---

## 4.2. EBITDA

O EBITDA padronizado do modelo é o **EBITDA contábil calculado**:

```text
EBITDA Contábil = EBIT CVM 3.05 + Depreciação e Amortização
```

Depreciação e amortização são obtidas preferencialmente da DFC.

Quando a companhia divulga um EBITDA ajustado, ele é armazenado separadamente como **EBITDA ajustado divulgado**. O modelo não cria ajustes não divulgados para fazer os dois valores coincidirem.

Quando ambos existem:

```text
Diferença Absoluta =
EBITDA Ajustado Divulgado - EBITDA Contábil
```

```text
Diferença % =
(EBITDA Ajustado Divulgado / EBITDA Contábil - 1) × 100
```

Diferenças relevantes são tratadas como diferenças metodológicas, não como erro automático.

---

## 4.3. EBITDA LTM

O EBITDA LTM corresponde à soma dos quatro últimos trimestres individuais comparáveis:

```text
EBITDA LTM = EBITDA T + EBITDA T-1 + EBITDA T-2 + EBITDA T-3
```

Se os quatro trimestres não estiverem disponíveis de forma comparável, o valor permanece nulo.

---

## 4.4. Dívida líquida

A dívida líquida padronizada utiliza, como referência:

| Componente | Código CVM |
|---|---|
| Caixa e equivalentes | `1.01.01` |
| Aplicações financeiras | `1.01.02` |
| Dívida de curto prazo | `2.01.04` |
| Dívida de longo prazo | `2.02.01` |

Configuração atual:

```text
deduz aplicações financeiras = sim
inclui arrendamentos = não
```

Assim:

```text
Dívida Líquida Padronizada =
Dívida CP
+ Dívida LP
- Caixa
- Aplicações Financeiras Dedutíveis
```

A dívida líquida divulgada pela companhia, quando disponível, é mantida separadamente e não substitui automaticamente a fórmula padronizada.

---

## 4.5. Market cap atual

```text
Market Cap Atual =
Último Preço × Ações em Circulação
```

A quantidade de ações atual é obtida preferencialmente do histórico de ações do Yahoo Finance, com fallbacks para campos pontuais quando necessário.

Empresas sem preço ou número de ações válido permanecem com market cap indisponível.

---

## 4.6. Market cap histórico

Para datas históricas, a quantidade de ações utiliza a composição do capital divulgada à CVM.

```text
Market Cap Histórico(t) =
Preço da Ação(t) × Quantidade de Ações(t)
```

O preço é o fechamento da data de referência ou o último pregão anterior.

São preservadas, quando disponíveis:

- data de referência;
- data efetiva do preço;
- quantidade de ações;
- preço;
- market cap.

---

## 4.7. Enterprise Value

```text
Enterprise Value(t) =
Market Cap Histórico(t)
+ Dívida Líquida Padronizada(t)
```

O cálculo não adiciona automaticamente:

- participações minoritárias;
- preferred shares;
- investimentos em coligadas;
- outros ajustes de valuation não explicitamente modelados.

---

## 4.8. EV / EBITDA LTM

```text
EV / EBITDA LTM =
Enterprise Value / EBITDA Contábil LTM
```

O múltiplo somente é calculado quando EV e EBITDA LTM estão disponíveis e o EBITDA LTM é diferente de zero.

O modelo procura alinhar temporalmente market cap, dívida líquida e EBITDA LTM. As datas efetivas dos componentes podem ser preservadas para auditoria.

---

## 4.9. Capital de giro

O indicador mostrado como capital de giro corresponde ao **Capital Circulante Líquido**:

```text
Capital de Giro =
Ativo Circulante - Passivo Circulante
```

Também é calculado:

```text
Capital de Giro / Receita =
Capital de Giro / Receita × 100
```

---

## 4.10. CAGR

O CAGR é calculado para receita e lucro líquido quando os valores inicial e final são positivos:

```text
CAGR =
((Valor Final / Valor Inicial) ^ (1 / anos) - 1) × 100
```

Valores iniciais ou finais menores ou iguais a zero impedem o cálculo convencional.

---

# 5. Ciclo financeiro

O ciclo financeiro mede o tempo entre a formação/compra do estoque, o pagamento aos fornecedores e o recebimento das vendas.

A fórmula geral é:

```text
Ciclo Financeiro = PMR + PME - PMP
```

onde:

```text
PMR = Contas a Receber Médias / Receita × Dias

PME = Estoque Médio / CMV × Dias

Compras Estimadas =
CMV + Estoque Final - Estoque Inicial

PMP = Fornecedores Médios / Compras Estimadas × Dias
```

Os saldos médios usam:

```text
Saldo Médio = (Saldo Inicial + Saldo Final) / 2
```

O modelo não substitui saldo inicial ausente pelo saldo final, pois isso introduziria uma aproximação não sinalizada.

O CMV é utilizado em módulo.

---

## 5.1. Saúde

Na metodologia padrão são consideradas as contas agregadoras:

| Componente | Código CVM |
|---|---|
| Contas a receber | `1.01.03` |
| Estoques | `1.01.04` |
| Fornecedores | `2.01.02` |
| Receita | `3.01` |
| Custo / CMV | `3.02` |

---

## 5.2. Construção Civil

Na Construção Civil, o ciclo operacional pode atravessar o circulante e o não circulante. Por isso, o modelo utiliza uma metodologia ampliada.

### Recebíveis

Incluem:

- contas a receber circulantes;
- recebíveis imobiliários não circulantes;
- contas a receber de clientes não circulantes quando claramente identificadas.

Excluem, entre outros:

- partes relacionadas;
- tributos;
- aplicações financeiras;
- ajustes a valor justo não relacionados ao recebível operacional.

### Estoques

Incluem:

- estoques circulantes;
- imóveis a comercializar;
- imóveis ou unidades em construção;
- terrenos destinados à operação imobiliária.

Excluem:

- propriedades para investimento;
- investimentos financeiros;
- imobilizado;
- intangível;
- tributos.

### Fornecedores e obrigações operacionais

Incluem:

- fornecedores circulantes;
- terrenos a pagar;
- obrigações por aquisição de terrenos ou imóveis claramente operacionais.

Excluem:

- empréstimos;
- financiamentos;
- debêntures;
- provisões;
- tributos;
- partes relacionadas.

Quando uma conta agregadora e suas subcontas aparecem simultaneamente, o modelo evita dupla contagem.

A fórmula de PMR, PME, PMP e ciclo financeiro permanece a mesma; o que muda é a composição das bases patrimoniais.

---

# 6. Variação e retorno de preço

## 6.1. Variação individual

O modelo calcula variações aproximadas de preço para os horizontes atualmente disponíveis:

- 30 dias;
- 360 dias.

```text
Variação de Preço =
(Preço Atual / Preço de Referência - 1) × 100
```

O preço de referência é o último fechamento disponível em ou antes da data-alvo.

---

## 6.2. Retorno setorial

O retorno setorial não é uma média simples dos retornos individuais.

Para cada empresa:

```text
Retorno_i =
Preço Final_i / Preço Inicial_i - 1
```

O peso é determinado pelo market cap no início do intervalo:

```text
Market Cap Inicial_i =
Preço Inicial_i × Quantidade de Ações Inicial_i
```

```text
Peso_i =
Market Cap Inicial_i / Soma dos Market Caps Iniciais
```

```text
Retorno Setorial =
Σ (Peso_i × Retorno_i)
```

A cobertura mínima atual é de **70% das empresas registradas no setor**. Abaixo desse limite, o retorno não é publicado como representativo.

---

# 7. Agregados setoriais

## 7.1. Participação no market cap

Somente entram empresas com market cap atual numérico, válido e positivo.

```text
Participação_i =
Market Cap_i / Soma dos Market Caps Válidos
```

Empresas sem market cap válido são excluídas do denominador e identificadas como indisponíveis; não recebem valor zero.

---

## 7.2. EV / EBITDA agregado

O múltiplo setorial é calculado pela razão entre os valores agregados:

```text
EV / EBITDA Setorial =
Σ Enterprise Value / Σ EBITDA LTM
```

Não é:

- média simples dos múltiplos;
- média ponderada dos múltiplos individuais.

EBITDAs negativos válidos entram na soma. Se o EBITDA LTM agregado for menor ou igual a zero, o múltiplo setorial permanece nulo.

---

# 8. Dados operacionais de Saúde

A camada operacional busca seis famílias de métricas:

- Ticket Médio;
- N. Atendimentos;
- N. Unidades;
- N. Pacientes;
- Receita Bruta;
- Glosa/PCLD.

A divulgação operacional não é padronizada entre companhias. Por isso, a metodologia privilegia a **evidência do rótulo, unidade, contexto e fonte**, e não apenas a presença de uma palavra-chave.

---

## 8.1. Natureza da observação

Cada observação pode ser classificada como:

```text
reported   = explicitamente divulgada
calculated = calculada a partir de componentes divulgados
proxy      = aproximação previamente autorizada
manual     = inserção manual
```

Proxies nunca são tratados como equivalência econômica perfeita.

Exemplos de não equivalência:

```text
Pacientes-dia != pacientes únicos
Procedimentos != atendimentos
Exames != atendimentos
Leitos != unidades
Beneficiários != pacientes
```

---

## 8.2. Confiança

A extração automática utiliza níveis de confiança:

```text
HIGH   = evidência forte e contexto claro
MEDIUM = evidência suficiente, mas com maior necessidade de cautela
LOW    = ambiguidade relevante
NOT_FOUND = informação não localizada
```

Somente observações **HIGH** e **MEDIUM** alimentam automaticamente o valor final.

Observações LOW permanecem como candidatas de auditoria e não devem preencher o dashboard.

---

## 8.3. Proxies permitidos

Proxies são específicos por companhia e devem permanecer identificados como tal.

Exemplos atualmente admitidos incluem:

| Companhia | Métrica-alvo | Proxy possível |
|---|---|---|
| DASA3 | N. Atendimentos | Exames |
| FLRY3 | N. Pacientes | Atendimentos |
| MATD3 | N. Atendimentos / Pacientes | Pacientes-dia |
| ONCO3 | N. Atendimentos / Pacientes | Procedimentos |
| RDOR3 | N. Atendimentos / Pacientes | Pacientes-dia |
| RDOR3 | N. Unidades | Hospitais próprios |

Esses proxies são aproximações operacionais e não alteram a definição conceitual da métrica-alvo.

---

## 8.4. Regras específicas relevantes

### RDOR3

A camada operacional busca preservar o escopo hospitalar/oncológico e excluir contextos de seguros e previdência, como SulAmérica, quando não pertencem à métrica-alvo.

### FLRY3

Quando não existe Ticket Médio explicitamente divulgado, ele pode ser calculado a partir de Receita Bruta e Atendimentos, desde que as unidades sejam compatíveis.

### MATD3

Pacientes-dia não são interpretados como pacientes únicos; quando utilizados, permanecem como proxy.

### DASA3

Escopos como Diagnósticos, Hospitais/Onco e outras divisões são mantidos separados para evitar mistura de bases operacionais distintas.

### ONCO3

Procedimentos ou tratamentos só entram como proxy quando a regra da companhia permitir.

### HAPV3

Receitas e glosas divulgadas em RI não substituem automaticamente a receita contábil CVM. A separação é particularmente relevante devido ao tratamento de IFRS 17.

---

# 9. Entradas manuais

Valores operacionais podem ser inseridos manualmente para uma combinação de:

```text
empresa + métrica + período
```

Uma entrada manual:

- é identificada explicitamente como `MANUAL`;
- permanece separada de dados automáticos;
- continua ativa enquanto não houver observação automática aceita para a mesma chave.

Se posteriormente o extrator encontrar um valor automático de confiança **HIGH** ou **MEDIUM** para a mesma empresa, métrica e período, o valor automático passa a prevalecer.

A entrada manual anterior é preservada no histórico de auditoria como substituída, em vez de ser apagada.

---

# 10. Quadro comparativo

O quadro comparativo utiliza métricas já calculadas nas camadas financeira, de mercado e operacional.

Entre as principais estão:

- CAGR de Receita;
- CAGR de Lucro;
- Ciclo Financeiro;
- Margem Bruta;
- Margem Operacional;
- Margem EBITDA;
- Margem Líquida;
- EV/EBITDA LTM;
- variação de preço;
- N. Unidades, quando aplicável.

Cada métrica pode usar o período válido mais recente correspondente à sua natureza. O comparativo não força uma única data artificial entre dados contábeis, de mercado e operacionais.

A ausência de valor é apresentada como indisponibilidade, não como zero.

---

# 11. Análise horizontal e vertical

## 11.1. Análise horizontal

```text
AH =
(Valor Atual / Valor do Período Anterior - 1) × 100
```

Se o valor anterior for zero ou uma das observações estiver ausente, o resultado fica indisponível.

---

## 11.2. Análise vertical

Para o Balanço Patrimonial:

```text
AV Ativo =
Conta / Ativo Total × 100
```

```text
AV Passivo =
Conta / Passivo Total × 100
```

Para a DRE:

```text
AV DRE =
Conta / Receita de Referência × 100
```

---

# 12. Qualidade, reconciliação e limitações

## 12.1. Status de qualidade

Indicadores derivados podem receber classificações como:

```text
validated
methodology_difference
estimated
incomplete
not_comparable
requires_review
error
```

Esses status indicam a qualidade ou comparabilidade do dado, e não devem ser interpretados automaticamente como erro de cálculo.

---

## 12.2. Reconciliação

Quando uma métrica padronizada calculada pode ser comparada com uma métrica divulgada, a diferença é classificada de forma analítica, por exemplo:

```text
MATCH
IMMATERIAL_DIFFERENCE
METHODOLOGY_DIFFERENCE
MATERIAL_DIFFERENCE
MISSING_DATA
NOT_COMPARABLE
```

O objetivo da reconciliação é explicar diferenças, e não forçar igualdade entre metodologias diferentes.

---

## 12.3. Limitações principais

1. **CVM e RI não têm granularidade uniforme entre companhias.**
2. **Market cap histórico depende da disponibilidade conjunta de preço e quantidade de ações.**
3. **Indicadores LTM exigem quatro trimestres comparáveis.**
4. **Dados operacionais são menos padronizados e têm maior risco de erro semântico.**
5. **Proxies aumentam cobertura, mas reduzem comparabilidade conceitual.**
6. **Construção Civil exige interpretação ampliada do capital operacional, especialmente em contas não circulantes.**
7. **EV é uma aproximação padronizada e não incorpora todos os ajustes possíveis de valuation.**
8. **Ausências de dados permanecem ausências; o modelo evita preenchimentos artificiais.**

---

# 13. Resumo das principais fórmulas

| Indicador | Fórmula |
|---|---|
| Market Cap | Preço × Ações |
| Dívida Líquida | Dívida CP + Dívida LP − Caixa − Aplicações Dedutíveis |
| EV | Market Cap Histórico + Dívida Líquida |
| EBITDA Contábil | EBIT + D&A |
| EBITDA LTM | Soma dos 4 trimestres individuais comparáveis |
| EV/EBITDA LTM | EV / EBITDA LTM |
| Capital de Giro | Ativo Circulante − Passivo Circulante |
| Margem Bruta | Resultado Bruto / Receita |
| Margem Operacional | EBIT / Receita |
| Margem EBITDA | EBITDA / Receita |
| Margem Líquida | Lucro Líquido / Receita |
| PMR | Contas a Receber Médias / Receita × Dias |
| PME | Estoque Médio / CMV × Dias |
| Compras Estimadas | CMV + Estoque Final − Estoque Inicial |
| PMP | Fornecedores Médios / Compras Estimadas × Dias |
| Ciclo Financeiro | PMR + PME − PMP |
| CAGR | (VF / VI)^(1/anos) − 1 |
| Retorno de Preço | Preço Final / Preço Inicial − 1 |
| EV/EBITDA Setorial | ΣEV / ΣEBITDA LTM |
| Retorno Setorial | Σ(Peso por Market Cap Inicial × Retorno) |

---

## Nota de interpretação

O Acompanhador de Mercado deve ser entendido como uma ferramenta de **padronização e apoio analítico**, não como substituto da leitura dos demonstrativos e documentos originais.

Quanto maior a dependência de documentos não estruturados, proxies ou diferenças de escopo, maior a necessidade de validação da fonte antes do uso decisório.

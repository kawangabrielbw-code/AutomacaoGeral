# Registro de Pendências, Divergências e Dúvidas Técnicas — Observatório de Diadema
**Fase:** Fase 1 — Mapeamento Técnico e Diagnóstico  
**Data do Registro:** 15 de Outubro de 2026  
**Status:** Aguardando esclarecimentos e autorização para a Fase 2  

---

## 1. Divergências Metodológicas e Técnicas Identificadas

### 1.1. Emprego Formal: Microdados do Novo CAGED vs. Painel de Informações do MTE
* **Contexto:** Na página [https://observatorio.diadema.sp.gov.br/emprego-formal/](https://observatorio.diadema.sp.gov.br/emprego-formal/), o próprio Observatório inseriu a seguinte nota técnica:
  > *"Obs.: Identificamos que os microdados do Caged divergem um pouco dos dados do BI “Painel de Informações do Novo Caged” disponibilizados pelo MTE. Acreditamos que a divergência se deva à exclusão pelo MTE, no BI, dos registros fora de prazo. Outra possibilidade é que os dados do BI utilizem uma agregação espacial um pouco diferente da utilizada nos microdados..."*
* **Impacto na Automação:** Se a futura automação consumir diretamente os microdados brutos do MTE via FTP, os valores consolidados de saldo e estoque de Diadema poderão apresentar ligeiras diferenças em relação aos cards exibidos no Metabase do Observatório.
* **Situação:** PARCIALMENTE CONFIRMADA. Requer definição com os gestores: se o pipeline deve espelhar os valores processados pelo DTIC/Metabase ou recalcular diretamente a partir dos microdados oficiais com critérios de expurgo de declarações fora de prazo.

---

### 1.2. Inconsistência de Nomenclatura e Período de Referência: BI EMPREGO RAIS (2024 vs. 2025)
* **Contexto:** 
  * Slug da URL do Observatório: `/bi-emprego-rais-2024/`
  * Título da página e cabeçalho do BI: `BI EMPREGO RAIS 2025`
  * Conteúdo da tabela histórica no rodapé da página: exibe dados de 2002 até a competência de 2025.
* **Impacto na Automação:** Pode gerar confusão na rotina de checagem de integridade de links e nomenclatura dos artefatos de dados.
* **Situação:** CONFIRMADA quanto ao conteúdo, PENDENTE de padronização pela equipe do portal.

---

### 1.3. Censo Escolar vs. MIEST (2025 vs. 2026)
* **Contexto:**
  * O portal possui dois painéis educacionais:
    1. `BI CENSO ESCOLAR 2025`: aponta para dados anuais consolidados do Censo Escolar do INEP.
    2. `BI ESCOLAS DE DIADEMA`: apresenta dados de matrículas e classes com competência declarada de **Março de 2026**, oriundos do MIEST (SEDUC-SP).
* **Impacto na Automação:** Trata-se de duas fontes com granularidades e periodicidades distintas que não devem ser mescladas em uma única tabela sem distinção da fonte geradora.
* **Situação:** CONFIRMADA (são fontes complementares, mas com calendários de divulgação distintos).

---

## 2. Limitações de Acesso e Riscos de Infraestrutura

### 2.1. Autenticação Obrigatória em Contas Google para Painéis Looker Studio
* **Evidência:** O portal exibe expressamente em todos os painéis Looker Studio a mensagem:
  > *"Obs.: para visualizar os BIs Google Looker, é necessário estar logado a uma conta Google. Poderá ocorrer algumas instabilidades no momento da consulta."*
* **Impacto:** Robôs automatizados rodando em servidores (como GitHub Actions, Airflow ou AWS Lambda) não possuem sessão interativa de navegador Google, o que ocasiona falha na renderização e bloqueios de segurança (Google OAuth / CAPTCHA).
* **Solução Proposta:** Não realizar scraping de Looker Studio; ingerir diretamente os arquivos das fontes oficiais primárias mapeadas na Onda 3 do Relatório de Viabilidade.
* **Situação:** LIMITAÇÃO CONFIRMADA.

---

### 2.2. Política de Download de Binários Grandes no Google Drive
* **Evidência:** Os links de download da Pesquisa FIPE 2019 e de cartas do Plano Diretor (`oppes-download`) apontam para pastas e arquivos binários ZIP no Google Drive. Testes com `curl -L` revelaram que o Google retorna uma página intermediária de aviso de verificação de vírus (`Google Drive cannot scan this file for viruses`), interrompendo o fluxo de download direto.
* **Impacto:** Scripts simples de `curl` ou `requests.get()` sem tratamento de cookies de confirmação não baixam o arquivo ZIP.
* **Situação:** LIMITAÇÃO CONFIRMADA. Requer módulo específico com tratamento do token `confirm=t` ou uso da Google Drive API com Service Account.

---

### 2.3. Estabilidade do Endpoint da API REST do Metabase
* **Evidência:** As chamadas públicas para `https://analytics.diadema.sp.gov.br/api/public/dashboard/:uuid/dashcard/:dc/card/:c` funcionam perfeitamente sem autenticação. Contudo, trata-se de um recurso não formalizado publicamente como contrato de API externa pela prefeitura.
* **Dúvida Técnica:** Caso o DTIC/SEPLAGE atualize a versão do Metabase ou decida desativar o acesso público anônimo à API, o pipeline de ingestão da Onda 1 seria interrompido.
* **Situação:** PENDENTE de alinhamento institucional com o DTIC da Prefeitura de Diadema para garantir a perenidade dos endpoints.

---

## 3. Informações Classificadas como Pendentes de Confirmação

| Informação / Tópico | Situação Atual | O que impede a confirmação técnica nesta fase | Ação recomendada |
| :--- | :---: | :--- | :--- |
| **Banco de dados de retaguarda do Metabase** | PENDENTE | Não é possível inspecionar o servidor interno do DTIC sem acesso administrativo. | Verificar com a equipe do DTIC se o Metabase lê um PostgreSQL/MySQL interno ou se os cards executam queries diretamente sobre arquivos importados. |
| **Cronograma de atualização dos painéis pela equipe SEPLAGE** | PENDENTE | As periodicidades das fontes oficiais são conhecidas (mensal/anual), mas a data exata do mês em que a SEPLAGE roda seus ETLs internos não é publicada. | Monitorar o campo de metadados `Último Registro` / `Competência` em cada card do Metabase. |
| **Integridade dos Shapefiles das Cartas 6 a 10 do Plano Diretor** | PARCIALMENTE CONFIRMADA | As pastas no Google Drive estão públicas, mas os arquivos individuais dentro de cada subpasta precisam de verificação geométrica (EPSG/SIRGAS 2000). | Validar as geometrias na Onda 4 da Fase 2. |
| **Defasagem do painel de Segurança Pública** | PARCIALMENTE CONFIRMADA | A página exibe gráficos Flourish e Looker Studio da SSP-SP, mas a data da última ocorrência carregada no visualizador requer parsing de canvas. | Coletar os dados mensais diretamente no portal da SSP-SP por meio de script automatizado na Onda 3. |

---

## 4. Pré-Requisitos Mandatórios para a Fase 2

Antes de avançar para a Fase 2 (Construção do Motor de Ingestão e Automação), é estritamente obrigatório:
1. **Aprovação Formal do Usuário:** Nenhuma linha de código de agendamento ou motor de ingestão deve ser executada sem autorização explícita do usuário.
2. **Definição da Camada de Armazenamento:** Alinhar se os dados ingeridos na Fase 2 deverão ser salvos em banco relacional local (ex: PostgreSQL/SQLite), arquivos Parquet/Delta em Data Lake ou planilhas consolidadas.
3. **Decisão sobre a Estratégia dos Painéis Looker Studio:** Confirmar se o cliente autoriza a ingestão direta a partir das fontes primárias de governo (MTE, RFB, INEP, SSP-SP, SEADE) para contornar a fragilidade do Looker Studio.

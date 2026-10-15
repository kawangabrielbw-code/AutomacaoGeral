# Inventário dos Painéis de Business Intelligence (BIs) — Observatório de Diadema
**Portal Auditado:** [https://observatorio.diadema.sp.gov.br/](https://observatorio.diadema.sp.gov.br/)  
**Órgão Responsável:** Secretaria de Planejamento e Gestão Pública (SEPLAGE) / Departamento de Tecnologia da Informação e Comunicação (DTIC) — Prefeitura de Diadema  
**Data da Auditoria Técnica:** 15 de Outubro de 2026  
**Status da Fase:** Fase 1 — Concluída (Somente Diagnóstico e Mapeamento, sem execução de motores)

---

## 1. Visão Geral da Arquitetura de Apresentação

O portal do Observatório de Diadema utiliza uma arquitetura híbrida de visualização de dados, distribuída em quatro mecanismos principais:
1. **Instância Municipal de Metabase (`analytics.diadema.sp.gov.br`):** Dashboards abertos que expõem endpoints de API REST pública para cards individuais, retornando dados estruturados em JSON.
2. **Google Looker Studio (antigo Data Studio):** Relatórios incorporados via iframe que exigem autenticação ativa em conta Google e não possuem API pública direta de exportação.
3. **Planilhas Google Sheets / Repositório Google Drive:** Arquivos de dados tabulares (CSV/XLSX) e espaciais (Shapefile/KML), sendo as planilhas passíveis de exportação direta via HTTP.
4. **Outras Plataformas Integradas:** Microsoft Power BI (link externo para o INEP), Flourish (gráficos interativos de segurança pública) e Google MyMaps (cartografia temática).

---

## 2. Catálogo Detalhado de Painéis de BI

### Grupo A — Painéis Principais ("BI OPPES")

#### 1. BI DIADEMA (Dados Gerais e Censo IBGE 2022)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-diadema/](https://observatorio.diadema.sp.gov.br/bi-diadema/)
* **Tecnologias de BI:**
  1. **Metabase (Prefeitura de Diadema):** `https://analytics.diadema.sp.gov.br/public/dashboard/67503054-df15-421c-b610-297d72b48bb5#theme=night` (Título: *Censo IBGE 2022 Diadema*)
  2. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/811671b0-55f2-40ba-aa45-3f6c096e95a2/page/p_yhlv9pwkkd`
* **Abas / Seções Identificadas:**
  * No Metabase: 26 cards analíticos cobrindo pirâmide etária, raça/cor, renda média domiciliar, condições de domicílios, saneamento, mobilidade pendular de trabalhadores e ocupações.
  * No Looker Studio: 1) População 2022 e Estimativas; 2) Censo 2022 – Diadema; 3) População e Bolsa Família; 4) Sub Territórios; 5) Densidade Demográfica; 6) Registro Civil.
* **Período de Referência Confirmado:** Censo Demográfico 2022 (IBGE) e estimativas municipais 2024.
* **Fonte Oficial Primária:** IBGE (Censo Demográfico 2022 / Amostra e Universo), Ministério do Desenvolvimento Social (MDS - CadÚnico/PBF), Fundação SEADE e Cartórios de Registro Civil (Arpen-Brasil).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 2. BI ECONOMIA DIADEMA (com dados do ABCDM)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-economia-diadema/](https://observatorio.diadema.sp.gov.br/bi-economia-diadema/)
* **Tecnologia de BI:** Google Looker Studio
* **URL do Embed:** `https://lookerstudio.google.com/embed/reporting/9b2f49f5-5fbb-4d21-a21f-c5b665c64199/page/GK4XE`
* **Abas / Seções Identificadas:**
  1. ICMS arrecadado e repassado
  2. IR arrecadado ABCDM
  3. PIB do ABCDM
  4. Composição do PIB
  5. Evolução Composição PIB
  6. Consumo de Energia Elétrica
* **Período de Referência Confirmado:** Séries temporais históricas consolidadas (PIB municipal com defasagem de 2 anos pelo IBGE; ICMS e IR até anos recentes).
* **Fonte Oficial Primária:**
  * ICMS Arrecadado: SEFAZ-SP (Relatório da Receita Tributária).
  * ICMS Repassado: Tribunal de Contas do Estado de São Paulo (TCE/SP).
  * Imposto de Renda: Receita Federal do Brasil / Ministério da Fazenda.
  * PIB Municipal: IBGE (Coordenação de Contas Nacionais / SIDRA).
  * Consumo de Energia: Secretaria de Infraestrutura e Meio Ambiente do Estado de SP (SIMA).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 3. BI CNPJ DIADEMA
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-cnpj-diadema/](https://observatorio.diadema.sp.gov.br/bi-cnpj-diadema/)
* **Tecnologia de BI:** Google Looker Studio
* **URL do Embed:** `https://lookerstudio.google.com/embed/reporting/c391a859-8e85-4a04-8815-1baf741fa975/page/L17dF`
* **Abas / Seções Identificadas:**
  1. Tabela Geral (Razão Social, Nome Fantasia, CNPJ, Situação, CNAE, Endereço, Bairro)
  2. Mapa de Calor (Espacialização dos estabelecimentos ativos)
* **Período de Referência Confirmado:** Base de dados de Julho de 2026.
* **Fonte Oficial Primária:** Receita Federal do Brasil (RFB) — Dados Abertos do CNPJ.
* **Classificação de Evidência:** CONFIRMADA.

---

#### 4. BI ESTABELECIMENTOS DE SAÚDE
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-estabel-saude/](https://observatorio.diadema.sp.gov.br/bi-estabel-saude/)
* **Tecnologia de BI:** Google Looker Studio
* **URL do Embed:** `https://lookerstudio.google.com/embed/reporting/10822373-0814-4cee-b8ad-c83cbd701d16/page/ejmFF`
* **Abas / Seções Identificadas:**
  1. Estabelecimentos de Saúde (UBS, Hospitais, Clínicas, Laboratórios)
  2. Profissionais de Saúde (médicos, enfermeiros, dentistas e outras especialidades)
* **Período de Referência Confirmado:** Março de 2026.
* **Fonte Oficial Primária:** Cadastro Nacional de Estabelecimentos de Saúde (CNES) / DATASUS / Ministério da Saúde.
* **Classificação de Evidência:** CONFIRMADA.

---

#### 5. BI CENSO ESCOLAR 2025
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-censo-escolar-2025/](https://observatorio.diadema.sp.gov.br/bi-censo-escolar-2025/)
* **Tecnologias de BI:**
  1. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/d8893134-93e0-4a3b-813c-69f6dea66a2f/page/p_gct9ug34qd`
  2. **Microsoft Power BI (Painel Oficial INEP):** `https://app.powerbi.com/view?r=eyJrIjoiN2ViNDBjNDEtMTM0OC00ZmFhLWIyZWYtZjI1YjU0NzQzMTJhIiwidCI6IjI2ZjczODk3LWM4YWMtNGIxZS05NzhmLWVhNGMwNzc0MzRiZiJ9`
* **Abas / Seções Identificadas:**
  1. Escolas por Bairro
  2. Matrículas por Escolas
  3. Mapa Escolas
  4. Evolução Matrículas Ed. Infantil
* **Período de Referência Confirmado:** Censo Escolar da Educação Básica 2025.
* **Fonte Oficial Primária:** Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP / MEC).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 6. BI ESCOLAS DE DIADEMA (MIEST SEDUC-SP)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-escolas-de-diadema/](https://observatorio.diadema.sp.gov.br/bi-escolas-de-diadema/)
* **Tecnologias de Apresentação:**
  1. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/6b203d2c-67af-4514-9831-c0409132c80a/page/O4ZeF`
  2. **Tabela HTML Estática Incorporada na Página:** Mais de 100 escolas listadas nominalmente.
* **Abas / Seções Identificadas:**
  1. Dados Gerais
  2. Matrículas Escolas
  * Tabela pública com colunas: `ESCOLA`, `DEPENDÊNCIA`, `TIPO ESCOLA`, `ENDEREÇO`, `BAIRRO`, `E. INF`, `E. FUND`, `ENS MÉD`, `ED COMPL`, `NOVO TEC`, `EJA`, `ED PROF`, `TOTAL`.
* **Período de Referência Confirmado:** Março de 2026.
* **Fonte Oficial Primária:** Secretaria da Educação do Estado de São Paulo (SEDUC-SP) / Movimentação e Informação Escolar de São Paulo (MIEST).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 7. BI VULNERABILIDADE SOCIAL (IPVS)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-vulnerabilidade/](https://observatorio.diadema.sp.gov.br/bi-vulnerabilidade/)
* **Tecnologia de BI:** Google Looker Studio
* **URL do Embed:** `https://lookerstudio.google.com/embed/reporting/98f996da-05f3-4f49-b1b6-d0fd0a82b070/page/jXsqF`
* **Abas / Seções Identificadas:** Classificação por Grupos de Vulnerabilidade (1 a 6) por setores censitários e bairros.
* **Período de Referência Confirmado:** Censo Demográfico 2022 (IBGE) / Metodologia IPVS SEADE.
* **Fonte Oficial Primária:** Fundação Sistema Estadual de Análise de Dados (Fundação SEADE).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 8. BI EMPREGO RAIS 2025
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/bi-emprego-rais-2024/](https://observatorio.diadema.sp.gov.br/bi-emprego-rais-2024/) *(Nota técnica: slug contém 2024, título e conteúdo referenciam 2025)*
* **Tecnologia de BI:** Google Looker Studio
* **URL do Embed:** `https://lookerstudio.google.com/embed/reporting/b601e342-fbdc-4e8d-b0db-6f9cda3f9365/page/gxsdF`
* **Abas / Seções Identificadas:**
  1. Vínculos por Atividade Econômica do Estabelecimento (CNAE)
  2. Vínculos por Perfil Profissional
  * Tabela estática na página com série histórica 2002 a 2025 dividida por Indústria, Construção, Comércio, Serviços e Agro.
* **Período de Referência Confirmado:** Série histórica de 2002 até a base anual de 2025.
* **Fonte Oficial Primária:** Ministério do Trabalho e Emprego (MTE) — Relação Anual de Informações Sociais (RAIS).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 9. ORÇAMENTO 2026 (Execução Orçamentária e Receita/Despesa)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/orcamento-2026/](https://observatorio.diadema.sp.gov.br/orcamento-2026/)
* **Tecnologias de BI:**
  1. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/5c9ef401-f9e9-4268-901f-9294f1b634cb/page/8P6wE`
  2. **Metabase (Prefeitura de Diadema):** `https://analytics.diadema.sp.gov.br/public/dashboard/b28dfb2c-48d3-44bf-afce-05e82ca98294#theme=night` (Título: *BI Execução Orçamentária PPA*)
* **Abas / Seções Identificadas:**
  * No Looker Studio: 1) Quadro Geral das Despesas; 2) Despesa por Elemento de Despesa; 3) Análise da Despesa; 4) Receita Arrecadada.
  * No Metabase: 11 cards ativos com Orçado Inicial, Orçado Atualizado, Empenhado, Liquidado, Despesa por Órgão e Tabela Completa por Programas de Governo.
* **Período de Referência Confirmado:** Exercício financeiro de 2026 (dados atualizados até Setembro/Outubro de 2026).
* **Fonte Oficial Primária:** Tribunal de Contas do Estado de São Paulo (TCE/SP - AUDESP) e Sistema Orçamentário Municipal (SEFIN / Prefeitura de Diadema).
* **Classificação de Evidência:** CONFIRMADA.

---

### Grupo B — Painéis Temáticos Mensais ("OPPES Indicadores")

#### 10. ACIDENTES DE TRÂNSITO (Sinistros)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/acidentes-de-transito/](https://observatorio.diadema.sp.gov.br/acidentes-de-transito/)
* **Tecnologias:**
  1. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/3ec248a2-26e2-4c25-8f5b-60b36e279bdb/page/7E0fF` (Abas: Pessoas Sinistro, Sinistros, Mapa de Calor)
  2. **Google Sheets Pública Direta:** `https://docs.google.com/spreadsheets/d/1IbVP_n2rCMDrLiQArlqixhGcuTUL8jqhsskpUVIr-QY/edit?usp=sharing`
* **Testes de Download Realizados:** Download direto via exportação CSV (`/export?format=csv`) executado com sucesso: **13.294 registros** e 31 colunas estruturadas.
* **Período de Referência Confirmado:** 2019 até 2026.
* **Fonte Oficial Primária:** INFOSIGA-SP (Detran-SP / Programa Respeito à Vida / Governo do Estado de SP).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 11. ASSISTÊNCIA SOCIAL (CadÚnico e Bolsa Família)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/assistencia-social/](https://observatorio.diadema.sp.gov.br/assistencia-social/)
* **Tecnologia de BI:** Metabase (Prefeitura de Diadema)
* **URL do Embed:** `https://analytics.diadema.sp.gov.br/public/dashboard/84393b4a-7570-49a0-8a7b-50ca560aa97c#theme=night&refresh=300` (Título: *BI Assitência Social*)
* **Cards / Estrutura:** 19 cards ativos detalhando famílias inscritas no CadÚnico, beneficiários do PBF, percentual sobre domicílios e comparação com o ABCDM.
* **Período de Referência Confirmado:** Competência de Agosto de 2026 (`08/2026`).
* **Fonte Oficial Primária:** SAGICAD / Ministério do Desenvolvimento e Assistência Social, Família e Combate à Fome (MDS - Plataforma VIS DATA 3 beta).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 12. ATIVIDADE ECONÔMICA (Arrecadação e Repasse de ICMS)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/atividade-economica/](https://observatorio.diadema.sp.gov.br/atividade-economica/)
* **Tecnologia de BI:** Metabase (Prefeitura de Diadema)
* **URL do Embed:** `https://analytics.diadema.sp.gov.br/public/dashboard/b01d1100-309d-4d18-b40d-c71e6416fb77#theme=night&refresh=300` (Título: *BI Atividade Econômica (ICMS)*)
* **Cards / Estrutura:** 12 cards ativos contendo ICMS Arrecadado Nominal, Deflacionado por IPCA, Repassado, comparação ABCDM e séries desde 2009.
* **Período de Referência Confirmado:** Julho de 2026 (`07/2026`).
* **Fonte Oficial Primária:** SEFAZ-SP (Relatório da Receita Tributária) e TCE-SP (Repasses de ICMS/IPVA).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 13. EMPREGO FORMAL (Novo CAGED)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/emprego-formal/](https://observatorio.diadema.sp.gov.br/emprego-formal/)
* **Tecnologia de BI:** Metabase (Prefeitura de Diadema)
* **URL do Embed:** `https://analytics.diadema.sp.gov.br/public/dashboard/38e0c61b-99ee-4711-b76e-3c6b435f5d72#theme=night&refresh=300` (Título: *BI CAGED Diadema*)
* **Cards / Estrutura:** 25 cards com Admissões, Demissões, Saldo, Estoque por Setor, Perfil do Trabalhador, Ocupações (CBO) e Mediana Salarial em 24 meses.
* **Período de Referência Confirmado:** Agosto de 2026 (`2026/08`).
* **Fonte Oficial Primária:** Ministério do Trabalho e Emprego (MTE) — Novo CAGED.
* **Classificação de Evidência:** CONFIRMADA.

---

#### 14. RECEITA E DESPESA (Execução Orçamentária TCESP)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/receita-e-despesa/](https://observatorio.diadema.sp.gov.br/receita-e-despesa/)
* **Tecnologia de BI:** Metabase (Prefeitura de Diadema)
* **URL do Embed:** `https://analytics.diadema.sp.gov.br/public/dashboard/c536c790-6817-4d19-8065-ce1bb797db21#theme=night&refresh=300` (Título: *BI Orçamento TCESP*)
* **Cards / Estrutura:** 17 cards com Receitas Arrecadadas por Rubrica/Fonte, Despesas Liquidadas por Função de Governo/Administração e comparativo em 24 meses.
* **Período de Referência Confirmado:** Agosto de 2026 (`08/2026`).
* **Fonte Oficial Primária:** Tribunal de Contas do Estado de São Paulo (TCE/SP — Sistema AUDESP).
* **Classificação de Evidência:** CONFIRMADA.

---

#### 15. SAÚDE (Atenção Básica e Satisfação)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/saude/](https://observatorio.diadema.sp.gov.br/saude/)
* **Tecnologias:**
  1. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/7b42f29d-b0b7-4c7c-bb4c-a8428ffbd249/page/p_iinx0yu4kd` (Produção e motivos de atendimento da atenção básica)
  2. **Metabase (Prefeitura de Diadema):** `https://analytics.diadema.sp.gov.br/public/dashboard/90a93a5d-d83e-4cc5-ba17-43d6a4c058c7?unidade=#theme=night` (Título: *BI Pesquisa Satisfação Saúde*)
  3. **Planilha Google Sheets Pública:** `https://docs.google.com/spreadsheets/d/1FRXI-muwyjka7FUK-TG47qJ3dPjJlo-8pIsQDL1a2jw/edit?usp=sharing`
* **Testes de Download Realizados:** Exportação CSV da planilha testada com sucesso: 80 competências mensais com 24 colunas de causas clínicas de atendimento primário.
* **Período de Referência Confirmado:** Séries mensais do SISAB e pesquisa com último registro registrado em 15/10/2026.
* **Fonte Oficial Primária:** Sistema de Informação em Saúde para a Atenção Básica (SISAB / SAPS / Ministério da Saúde) e SMS Diadema.
* **Classificação de Evidência:** CONFIRMADA.

---

#### 16. SEGURANÇA PÚBLICA (Estatísticas Criminais)
* **URL no Observatório:** [https://observatorio.diadema.sp.gov.br/seguranca-publica/](https://observatorio.diadema.sp.gov.br/seguranca-publica/)
* **Tecnologias:**
  1. **Flourish:** `https://flo.uri.sh/visualisation/20168000/embed?auto=1` e `https://flo.uri.sh/visualisation/20168971/embed?auto=1` (Visualizações interativas de queda histórica de homicídios)
  2. **Google Looker Studio:** `https://lookerstudio.google.com/embed/reporting/4e3a07e3-88c8-40e5-8c17-11ee67e2d0ca/page/P5BKF` (Abas: Ocorrências/mês, Taxas)
* **Período de Referência Confirmado:** Séries históricas mensais consolidadas.
* **Fonte Oficial Primária:** Secretaria de Segurança Pública do Estado de São Paulo (SSP-SP — Estatísticas Policiais).
* **Classificação de Evidência:** CONFIRMADA.

---

### Grupo C — Painéis Territoriais e Demográficos ("Diadema em Números")

#### 17. BAIRROS OFICIAIS
* **URL:** [https://observatorio.diadema.sp.gov.br/bairros-oficiais/](https://observatorio.diadema.sp.gov.br/bairros-oficiais/)
* **Formato:** Vídeo interativo Google Earth incorporado via YouTube (`f6fQBgGOUp8`) e tabelas textuais de população 2022 e estimativa 2024 para os 11 bairros oficiais de Diadema (Campanário, Taboão, Canhema, Piraporinha, Vila Nogueira, Casa Grande, Centro, Promissão, Conceição, Inamar e Eldorado).
* **Classificação de Evidência:** CONFIRMADA.

#### 18. TERRITÓRIO SEPLAGE 2025
* **URL:** [https://observatorio.diadema.sp.gov.br/territorio-spg-2025/](https://observatorio.diadema.sp.gov.br/territorio-spg-2025/)
* **Formato:** Delimitação de 49 territórios infra-municipais criados pelo OPPES a partir de setores censitários do IBGE no Censo 2022.
* **Classificação de Evidência:** CONFIRMADA.

#### 19. ÁREAS DE PONDERAÇÃO (Censo 2022)
* **URL:** [https://observatorio.diadema.sp.gov.br/areas-de-ponderacao/](https://observatorio.diadema.sp.gov.br/areas-de-ponderacao/)
* **Formato:** Mapeamento e tabela das 27 Áreas de Ponderação (AP) do Censo 2022 da amostra estatística do IBGE.
* **Classificação de Evidência:** CONFIRMADA.

#### 20. SUBDIVISÃO TERRITORIAL
* **URL:** [https://observatorio.diadema.sp.gov.br/subdivisao-territorial/](https://observatorio.diadema.sp.gov.br/subdivisao-territorial/)
* **Formato:** 48 territórios históricos (loteamentos de origem).
* **Classificação de Evidência:** CONFIRMADA.

#### 21. PESQUISA ORIGEM DESTINO FIPE 2019
* **URL:** [https://observatorio.diadema.sp.gov.br/pesquisa-fipe-2019/](https://observatorio.diadema.sp.gov.br/pesquisa-fipe-2019/)
* **Formato:** Tabela pública de 40 Zonas de Tráfego/Origem-Destino com microdados demográficos e link para download no Google Drive (`1YzaMnXJWxy8FDN9xOUAWDkZ-zRn93hk1`).
* **Classificação de Evidência:** CONFIRMADA.

#### 22. DIADEMA EM MAPAS
* **URL:** [https://observatorio.diadema.sp.gov.br/diadema-em-mapas/](https://observatorio.diadema.sp.gov.br/diadema-em-mapas/)
* **Formato:** 4 iframes Google MyMaps e dados eleitorais tabulados por bairro (Eleições 2022 / TSE base 2023).
* **Classificação de Evidência:** CONFIRMADA.

---

### Grupo D — Downloads e Repositórios Documentais

#### 23. OPPES DOWNLOAD (Shapefiles, KML e Pesquisa de Restaurante Popular)
* **URL:** [https://observatorio.diadema.sp.gov.br/oppes-download/](https://observatorio.diadema.sp.gov.br/oppes-download/)
* **Recursos Identificados:**
  * 13 pastas/arquivos no Google Drive contendo shapefiles e KMLs do Plano Diretor de Diadema (PD 2019 - 10 cartas temáticas: Macrozonas, Macroáreas, Subáreas, Áreas de Risco, etc.).
  * 1 Planilha Google Sheets pública com **1.257 respostas da Pesquisa de Satisfação dos Restaurantes Populares** (32 colunas incluindo coordenadas geográficas e perfil de renda).
* **Classificação de Evidência:** CONFIRMADA.

#### 24. DOCUMENTOS (Repositório de Relatórios Técnicos em PDF)
* **URL:** [https://observatorio.diadema.sp.gov.br/documentos/](https://observatorio.diadema.sp.gov.br/documentos/)
* **Recursos Identificados:** 26 arquivos PDF hospedados diretamente no WordPress do portal (`/wp-content/uploads/2025/09/`).
* **Testes de Download Realizados:** Testes com HTTP HEAD/GET confirmaram resposta `HTTP 200 OK` pública e irrestrita.
* **Classificação de Evidência:** CONFIRMADA.

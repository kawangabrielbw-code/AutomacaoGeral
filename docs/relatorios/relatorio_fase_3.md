# Relatório de Execução e Conclusão — Fase 3: Motor de Coleta do Metabase
**Projeto:** Automação de Dados do Observatório de Políticas Públicas de Diadema (OPPES)  
**Data da Execução:** 15 de Outubro de 2026  
**Status:** Concluído com Sucesso e Evidências Reais  

---

## 1. O que foi Implementado na Fase 3

Na Fase 3, foi construído e homologado o motor automatizado de descoberta e coleta para os dashboards municipais do Metabase (`analytics.diadema.sp.gov.br`), sem codificação manual rígida de IDs e com total continuidade em caso de falhas pontuais:

1. **Módulo de Descoberta Dinâmica ([`src/engine/metabase_discovery.py`](file:///c:/Users/kawan.aquino/Downloads/AutomaçãoGeral/src/engine/metabase_discovery.py)):**
   * Classe `MetabaseDashboardDiscovery` que consulta o endpoint `/api/public/dashboard/{uuid}` dos 7 dashboards mapeados.
   * Filtra automaticamente caixas de texto virtuais e banners não-queryáveis, extraindo apenas cards analíticos reais.
   * Normalização de nomes com `slugify` para criação determinística de diretórios e arquivos.

2. **Motor de Coleta e Catálogo ([`src/engine/metabase_harvester.py`](file:///c:/Users/kawan.aquino/Downloads/AutomaçãoGeral/src/engine/metabase_harvester.py)):**
   * Classe `MetabaseHarvester` que orquestra as consultas utilizando o conector `MetabaseCardConnector`.
   * **Escrita Segura e Atômica:** Grava temporariamente em `.tmp_card_{id}.csv` e só substitui o arquivo definitivo caso a requisição e validação tenham sido bem-sucedidas. Preserva arquivos anteriores caso ocorra erro.
   * **Continuidade Total:** Tratamento de exceções por card com logging detalhado; a falha de um card não interrompe os demais.
   * **Rate Limiting Educado:** Intervalo configurável entre requisições (0.2s a 0.3s) para não sobrecarregar o servidor municipal.
   * **Catálogo Consolidado:** Registra e atualiza os metadados de cada card em CSV e JSON, com chave primária composta `dashboard_uuid:card_id`, eliminando duplicações em reexecuções.

3. **Comandos e Utilitários Executáveis:**
   * [`scripts/coletar_metabase.py`](file:///c:/Users/kawan.aquino/Downloads/AutomaçãoGeral/scripts/coletar_metabase.py): Comando único de linha de comando para disparo da descoberta e coleta, aceitando flags como `--delay`, `--timeout`, `--dashboard-uuid` e `--inventory`.
   * [`scripts/atualizar_catalogo.py`](file:///c:/Users/kawan.aquino/Downloads/AutomaçãoGeral/scripts/atualizar_catalogo.py): Comando para sincronização do catálogo a partir dos arquivos locais já coletados em disco.

4. **Testes Automatizados Complementares ([`tests/test_metabase_engine.py`](file:///c:/Users/kawan.aquino/Downloads/AutomaçãoGeral/tests/test_metabase_engine.py)):**
   * 6 novos testes unitários validando filtragem de cards virtuais, escrita segura, continuidade de falha, idempotência do catálogo e atualização a partir do disco.

---

## 2. Estatísticas Reais da Coleta Executada

A coleta real de toda a instância do Metabase foi disparada e finalizada com sucesso pelo comando:
```bash
py scripts/coletar_metabase.py --delay 0.2
```

| Métrica | Valor Observado | Detalhes |
| :--- | :---: | :--- |
| **Dashboards Descobertos** | **7** | Todos os 7 dashboards do inventário foram reconhecidos. |
| **Cards Descobertos Dinamicamente** | **121** | 100% dos cards queryáveis foram mapeados sem hardcode. |
| **Cards Tentados / Consultados** | **121** | Todos os 121 cards foram chamados individualmente. |
| **Cards Concluídos com Sucesso** | **120** | **99,17% de taxa de sucesso**. Dados tabulares extraídos e gravados. |
| **Cards Vazios (Zero Registros)** | **0** | Nenhum card retornou tabela vazia. |
| **Cards com Falha / Timeout** | **1** | Apenas 1 card falhou por timeout de leitura. |
| **Tempo Total de Execução** | **344,97s** | Média de ~2,8 segundos por card (incluindo rate limit e rede). |

---

## 3. Localização dos Dados Coletados e Catálogo

Os dados brutos e o catálogo foram organizados na estrutura:

```
data/raw/metabase/
├── catalogo_metabase.csv                <- Catálogo tabular de todos os cards coletados
├── catalogo_metabase.json               <- Catálogo em JSON estruturado
├── relatorio_coleta_metabase.md         <- Relatório analítico da última execução
├── bi_assitencia_social/                <- 19 arquivos CSV (CadÚnico e Bolsa Família)
├── bi_atividade_economica_icms/         <- 12 arquivos CSV (Séries de ICMS e Repasses)
├── bi_caged_diadema/                    <- 25 arquivos CSV (Admissões, Demissões, Estoque)
├── bi_execucao_orcamentaria_ppa/        <- 11 arquivos CSV (Orçado, Empenhado, Liquidado)
├── bi_orcamento_tcesp/                  <- 17 arquivos CSV (Receitas e Despesas TCESP)
├── bi_pesquisa_satisfacao_saude/        <- 11 arquivos CSV (Indicadores de Ouvidoria e UBS)
└── censo_ibge_2022_diadema/             <- 25 arquivos CSV (População, Bairros, Domicílios)
```

Total de arquivos CSV gerados e validados: **120 arquivos CSV individuais**.

---

## 4. Problemas e Limitações Observadas

1. **Timeout no Card 1118:**
   * *Card:* `Card 1118 — Pessoas de outros Municípios que Trabalham em Diadema` no dashboard *Censo IBGE 2022 Diadema*.
   * *Diagnóstico:* O Metabase excedeu o timeout de leitura de 20s (`Read timed out`). Trata-se de uma consulta SQL pesada que agrega toda a amostra do Censo 2022 para cruzamento de origens metropolitanas.
   * *Comportamento do Motor:* O motor capturou o erro, registrou a falha no catálogo e continuou normalmente para os 97 cards seguintes, comprovando o requisito de resiliência.
2. **Campos com Valores Formatados (ex.: Strings de Percentual):**
   * Alguns cards já chegam do Metabase com formatações visuais (ex.: `"53.44%"`). Essas strings foram preservadas fidedignamente no CSV sem adulteração.

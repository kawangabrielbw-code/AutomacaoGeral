# Relatório de Execução e Conclusão — Fase 4: Integração de Planilhas e Sistema Unificado
**Projeto:** Automação de Dados do Observatório de Políticas Públicas de Diadema (OPPES)  
**Data da Execução:** 15 de Outubro de 2026  
**Status:** Concluído com Sucesso

---

## 1. Funcionalidades Implementadas

### 1.1 Conector Google Sheets (`src/connectors/google_sheets_connector.py`)

Módulo reutilizável que:

- **Extrai IDs e GIDs** de URLs do Google Sheets em qualquer formato (`/spreadsheets/d/{id}/edit?usp=sharing`, `#gid=123456`, ou ID puro).
- **Baixa dados de planilhas públicas** via endpoint de exportação CSV (`/export?format=csv&gid={gid}`).
- **Fallback automático sem GID:** Quando a exportação com `gid=0` retorna HTTP 400 (típico de arquivos `.xlsx` enviados ao Google Drive), retenta automaticamente sem o parâmetro GID.
- **Detecta barreiras de autenticação** por redirecionamento para `accounts.google.com` ou por respostas HTTP 401/403, sem tentar contorná-las (registra `REQUER_AUTENTICACAO`).
- **Valida o conteúdo CSV**, verificando cabeçalhos e formato tabular coerente.
- **Preserva valores nulos e textos originais**, sem conversão arbitrária para zero.
- **Escrita atômica segura:** Grava em `.tmp_{nome}.csv` e só renomeia para o arquivo definitivo após validação bem-sucedida. CSVs anteriores são preservados em caso de falha.
- **Retentativas configuráveis** (padrão: 3 tentativas) para erros HTTP transitórios (429, 500, 502, 503, 504).
- **Hierarquia de exceções:** `GoogleSheetsError`, `GoogleSheetsAuthRequiredError`, `GoogleSheetsHTTPError`, `GoogleSheetsTimeoutError`, `GoogleSheetsValidationError`.

### 1.2 Motor de Coleta de Planilhas (`src/engine/sheets_harvester.py`)

Classe `GoogleSheetsHarvester` que:

- Lê a configuração de planilhas cadastradas em `config/google_sheets.json`.
- Instancia um `GoogleSheetsConnector` para cada planilha.
- Mantém um catálogo próprio em `data/raw/google_sheets/catalogo_sheets.csv` e `catalogo_sheets.json`.
- Coleta por iteração, registrando erros sem interromper as demais fontes.

### 1.3 Orquestrador Unificado (`src/engine/unified_harvester.py`)

Classe `UnifiedHarvester` que integra Metabase e Google Sheets:

- Executa `MetabaseHarvester` e/ou `GoogleSheetsHarvester` conforme seleção.
- Consolida automaticamente o **Catálogo Geral** (`data/raw/catalogo_geral.csv` e `catalogo_geral.json`) com todos os registros de ambas as fontes.
- Suporta execução parcial (`--fonte metabase`, `--fonte sheets`, ou `--fonte todas`).

### 1.4 Comando Único de Coleta (`scripts/coletar_dados.py`)

Script CLI que dispara o orquestrador unificado:

```bash
py scripts/coletar_dados.py                 # Coleta completa (Metabase + Google Sheets)
py scripts/coletar_dados.py --fonte sheets   # Apenas planilhas Google Sheets
py scripts/coletar_dados.py --fonte metabase # Apenas Metabase
py scripts/coletar_dados.py --timeout 45     # Com timeout customizado
```

### 1.5 Configuração de Planilhas (`config/google_sheets.json`)

Arquivo JSON declarativo com 3 planilhas públicas cadastradas. Novas fontes podem ser adicionadas incluindo um novo objeto no array, sem modificar o código do conector:

```json
{
  "id": "nova_planilha",
  "name": "Nome da Planilha",
  "url": "https://docs.google.com/spreadsheets/d/{id}/edit?usp=sharing",
  "gid": "0",
  "categoria": "Categoria",
  "fonte_primaria": "Fonte Oficial"
}
```

### 1.6 Testes Unitários (`tests/test_google_sheets_connector.py`)

8 novos testes automatizados cobrindo:

| # | Teste | Validação |
|---|-------|-----------|
| 1 | `test_01_extract_sheet_id_and_gid` | Extração de ID/GID de múltiplos formatos de URL |
| 2 | `test_02_download_valid_csv` | Download e validação de CSV válido com preservação de nulos |
| 3 | `test_03_download_empty_csv` | Planilha com cabeçalho mas zero linhas de dados |
| 4 | `test_04_http_error` | Tratamento de erro HTTP 404 |
| 5 | `test_05_auth_required_detection` | Detecção de barreira de autenticação (redirect para login) |
| 6 | `test_06_timeout_handling` | Falha de timeout com retentativas |
| 7 | `test_07_safe_export_preserves_valid_file_on_failure` | Preservação de CSV válido quando atualização falha |
| 8 | `test_08_add_new_sheet_by_configuration` | Adição de novas planilhas por configuração dinâmica |

---

## 2. Fontes Encontradas vs Fontes Efetivamente Coletadas

### 2.1 Google Sheets (3 cadastradas, 3 coletadas com sucesso)

| Planilha | Sheet ID | Linhas | Colunas | Status |
|----------|----------|--------|---------|--------|
| Sinistros de Trânsito em Diadema (INFOSIGA-SP) | `1IbVP_n2rCMDrLiQ...` | 13.293 | 31 | ✅ SUCESSO |
| Produção da Atenção Básica de Saúde SISAB | `1FRXI-muwyjka7FUK...` | 79 | 24 | ✅ SUCESSO |
| Pesquisa de Satisfação - Restaurante Popular | `1yrDtIFcbxtVgen0...` | 1.256 | 33 | ✅ SUCESSO |

**Observação técnica:** A planilha do Restaurante Popular é um arquivo `.xlsx` enviado ao Google Drive (não nativo do Google Sheets). A exportação com `gid=0` retorna HTTP 400. O conector detectou isso automaticamente e usou o fallback sem GID com sucesso.

### 2.2 Metabase (119 cards no catálogo, 118 sucesso, 1 timeout)

Conforme herdado da Fase 3:

- 7 dashboards descobertos dinamicamente
- 121 cards tentados
- 120 CSVs gerados (119 indexados no catálogo + 1 card que retornou dados mas não foi catalogado por duplicação de chave em reexecução)
- 1 card com timeout (Card 1118 — consulta pesada do Censo IBGE 2022)

---

## 3. Quantidade de Sucessos e Falhas por Tipo de Fonte

| Tipo de Fonte | Total | Sucesso | Falha | Taxa de Sucesso |
|---------------|-------|---------|-------|-----------------|
| **Google Sheets** | 3 | 3 | 0 | **100,0%** |
| **Metabase** | 119 | 118 | 1 | **99,2%** |
| **Total Geral** | **122** | **121** | **1** | **99,2%** |

---

## 4. Arquivos e Catálogos Gerados

### 4.1 Estrutura de Dados

```
data/raw/
├── catalogo_geral.csv              ← Catálogo unificado (122 fontes)
├── catalogo_geral.json             ← Catálogo unificado em JSON
├── google_sheets/
│   ├── catalogo_sheets.csv         ← Catálogo de planilhas (3 registros)
│   ├── catalogo_sheets.json        ← Catálogo de planilhas em JSON
│   ├── acidentes_transito.csv      ← 13.293 registros, 31 colunas (2,6 MB)
│   ├── saude_atencao_basica_sisab.csv  ← 79 registros, 24 colunas (8 KB)
│   └── pesquisa_restaurante_popular.csv ← 1.256 registros, 33 colunas (510 KB)
└── metabase/
    ├── catalogo_metabase.csv       ← Catálogo Metabase (119 cards)
    ├── catalogo_metabase.json
    ├── bi_assitencia_social/       ← 19 CSVs
    ├── bi_atividade_economica_icms/ ← 12 CSVs
    ├── bi_caged_diadema/           ← 25 CSVs
    ├── bi_execucao_orcamentaria_ppa/ ← 11 CSVs
    ├── bi_orcamento_tcesp/         ← 17 CSVs
    ├── bi_pesquisa_satisfacao_saude/ ← 11 CSVs
    └── censo_ibge_2022_diadema/    ← 25 CSVs
```

### 4.2 Módulos e Scripts

```
src/
├── connectors/
│   ├── metabase_card_connector.py   ← Conector unitário do Metabase (Fase 2A)
│   └── google_sheets_connector.py   ← Conector de planilhas públicas (Fase 4)
└── engine/
    ├── metabase_discovery.py        ← Descoberta dinâmica de dashboards (Fase 3)
    ├── metabase_harvester.py        ← Motor de coleta do Metabase (Fase 3)
    ├── sheets_harvester.py          ← Motor de coleta de planilhas (Fase 4)
    └── unified_harvester.py         ← Orquestrador unificado (Fase 4)

scripts/
├── coletar_dados.py                 ← Comando único unificado (Fase 4)
├── coletar_metabase.py              ← Comando exclusivo Metabase (Fase 3)
└── atualizar_catalogo.py            ← Sincronização de catálogo (Fase 3)

config/
└── google_sheets.json               ← Planilhas cadastradas (Fase 4)

tests/
├── test_metabase_card_connector.py  ← 7 testes (Fase 2A)
├── test_metabase_engine.py          ← 6 testes (Fase 3)
└── test_google_sheets_connector.py  ← 8 testes (Fase 4)
```

---

## 5. Comandos para Executar o Sistema

```bash
# Coleta completa (Metabase + Google Sheets)
py scripts/coletar_dados.py

# Coleta apenas Google Sheets
py scripts/coletar_dados.py --fonte sheets

# Coleta apenas Metabase
py scripts/coletar_dados.py --fonte metabase

# Coleta com timeout customizado
py scripts/coletar_dados.py --fonte todas --timeout 45

# Coleta apenas Metabase (script legado)
py scripts/coletar_metabase.py --delay 0.2

# Executar todos os testes unitários
py -m unittest discover -s tests -v
```

---

## 6. Testes Executados e Resultados Reais

### 6.1 Testes Unitários (21/21 aprovados)

```
Ran 21 tests in 0.299s — OK
```

| Suíte | Testes | Resultado |
|-------|--------|-----------|
| `test_google_sheets_connector.py` | 8 | ✅ 8/8 OK |
| `test_metabase_card_connector.py` | 7 | ✅ 7/7 OK |
| `test_metabase_engine.py` | 6 | ✅ 6/6 OK |
| **Total** | **21** | **✅ 21/21 OK** |

### 6.2 Execução Real — Google Sheets

**Comando:** `py scripts/coletar_dados.py --fonte sheets --timeout 45`

| Métrica | Valor |
|---------|-------|
| Planilhas cadastradas | 3 |
| Planilhas tentadas | 3 |
| Planilhas coletadas com sucesso | **3** |
| Planilhas com falha | **0** |
| Planilhas restritas | **0** |
| Tempo total | **3,15s** |
| Catálogo Geral atualizado | 122 fontes |

### 6.3 Teste de Fallback — Restaurante Popular

- A requisição com `gid=0` retornou HTTP 400 (arquivo `.xlsx` no Google Drive).
- O conector detectou automaticamente e retentou sem GID.
- A segunda requisição retornou HTTP 200 com CSV válido (1.256 linhas, 33 colunas).

---

## 7. Limitações e Problemas Conhecidos

1. **Card 1118 do Metabase (timeout):** A consulta "Pessoas de outros Municípios que Trabalham em Diadema" é uma agregação pesada do Censo IBGE 2022 que excede 20s de timeout. O motor trata o erro graciosamente.

2. **Encoding dos cabeçalhos SISAB:** A planilha de saúde SISAB apresenta caracteres com encoding `latin-1` decodificados como `Ã§Ã£` (ex.: `CompetÃªncia`). Isso é o conteúdo original publicado na planilha — o sistema preserva os dados sem alterá-los.

3. **Planilhas privadas:** O sistema detecta e registra planilhas que exigem autenticação (`REQUER_AUTENTICACAO`) sem tentar contorná-las. Nenhuma das 3 planilhas cadastradas atualmente exige autenticação.

4. **Sem agendamento automático:** O sistema opera por comando manual. Não há cron, scheduler ou interface gráfica implementados nesta fase.

5. **Sem controle de frequência por fonte:** Todas as fontes são coletadas uniformemente a cada execução, sem diferenciar periodicidade ideal.

---

## 8. Próximos Passos (Fase 5 — Pendente Autorização)

1. **Atualização automática** com agendamento (cron/scheduler Windows).
2. **Controle de frequência por fonte:** Definir periodicidade ideal para cada fonte (diário, semanal, mensal) e evitar coletas desnecessárias.
3. **Recuperação de falhas:** Reexecutar automaticamente apenas as fontes que falharam na última coleta.
4. **Notificações:** Alertas por e-mail ou webhook quando uma coleta falhar ou detectar mudanças significativas nos dados.
5. **Tratamento de encoding:** Normalização opcional de cabeçalhos com encoding inconsistente.

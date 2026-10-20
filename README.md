# Automação de dados do Observatório de Diadema

Projeto Python para coletar os CSVs públicos do Metabase municipal e das planilhas Google configuradas. Os arquivos brutos e catálogos ficam em `data/raw`; o histórico de tentativas fica em `data/history/historico.sqlite3` e em JSON/CSV compatíveis.

## Instalação

Requer Python 3.10 ou superior. No Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Coleta

```powershell
py scripts/coletar_dados.py
py scripts/coletar_dados.py --fonte sheets
py scripts/coletar_dados.py --fonte metabase
py scripts/coletar_dados.py --vencidas
py scripts/coletar_dados.py --vencidas-metabase
py scripts/coletar_dados.py --falhas
py scripts/coletar_dados.py --status
```

Novas planilhas públicas podem ser incluídas em `config/google_sheets.json`. Frequências Sheets podem ser definidas em `config/sistema.json`. Para Metabase, defina somente as periodicidades documentadas em `config/metabase_cards.json`, usando como chave `dashboard_uuid:card_id`:

```json
{
  "cards": {
    "UUID_REAL_DO_DASHBOARD:ID_REAL_DO_CARD": {
      "frequencia": "mensal",
      "fonte_periodicidade": "órgão que publica a competência mensal"
    }
  }
}
```

Cards sem configuração são manuais. `--vencidas` considera fontes vencidas de ambos os tipos; `--vencidas-metabase` limita aos cards Metabase configurados. `--falhas` repete apenas os IDs que tiveram falha na última tentativa. `data_coleta_utc` é o momento em que o sistema buscou a fonte; a competência temporal dos dados é mantida no conteúdo original do CSV e não é tratada como data de coleta.

## Interface Web FastAPI

```powershell
py -m pip install -r requirements.txt
$env:OPPES_ADMIN_PASSWORD_HASH = (py scripts/gerar_hash_senha.py)
$env:OPPES_SESSION_SECRET = (py -c "import secrets; print(secrets.token_urlsafe(48))")
py scripts/iniciar_web.py
```

O launcher local escuta somente `127.0.0.1:8000`; acesse `http://127.0.0.1:8000`. Para parar, pressione `Ctrl+C` no terminal do servidor. A aplicação exige senha PBKDF2 (gerada pelo script interativo) e segredo de sessão a cada sessão de terminal; a senha não é gravada em texto puro.

Para acesso de outro computador na mesma rede, configure um certificado HTTPS com SAN para o IPv4 do servidor e a chave privada correspondente, armazenados fora do repositório. Configure `OPPES_TLS_CERT` e `OPPES_TLS_KEY`, mantenha os dois segredos acima e execute o launcher. Ele valida a compatibilidade do certificado e da chave TLS e rejeita arquivos guardados dentro da pasta do projeto.

```powershell
$env:OPPES_TLS_CERT = 'C:\caminho-seguro\oppes-cert.pem'
$env:OPPES_TLS_KEY = 'C:\caminho-seguro\oppes-key.pem'
py scripts/iniciar_web.py --rede
```

Esse modo escuta `0.0.0.0:8000` com TLS. `0.0.0.0` é apenas o endereço de escuta; no navegador, consulte o IPv4 do servidor com `ipconfig` e use `https://IP-DO-COMPUTADOR:8000`. O certificado deve ser confiável pelo computador cliente e conter esse IP no SAN. A aplicação rejeita HTTP vindo de hosts remotos. Ela não abre firewall nem configura roteador. Se o firewall precisar de regra, configure manualmente uma regra de entrada TCP 8000 restrita ao perfil **Privado** e ao escopo `LocalSubnet`.

**Autenticação:** `py scripts/gerar_hash_senha.py` solicita a senha sem eco e imprime somente um hash PBKDF2 salgado. Guarde o valor em `OPPES_ADMIN_PASSWORD_HASH` no ambiente da sessão. Gere `OPPES_SESSION_SECRET` com o comando acima; não o publique. O cookie da sessão é HttpOnly, SameSite Strict, não persistente além de oito horas e Secure nas conexões HTTPS. Operações de alteração exigem token CSRF. A aplicação não tem credenciais padrão.

### Páginas e operação

- **Dashboard:** indicadores e gráfico calculados do catálogo/SQLite, execuções recentes e consulta do Agendador do Windows.
- **Fontes:** busca, filtros, paginação, ordenação na página, detalhes, histórico e coleta individual.
- **Coletas:** coletas em segundo plano, atualização de vencidas, Metabase, Sheets e repetição de falhas. Operações em lote exigem confirmação; lock e histórico existentes continuam em uso.
- **Histórico:** filtros por fonte, tipo, estado e período, operações web e relatórios.
- **Configurações:** periodicidade por fonte, caminhos configurados, consulta e comandos confirmados do Agendador, dry-run e relatórios.

Os endpoints JSON ficam em `/api`. A API não aceita comandos arbitrários nem caminhos locais fornecidos pelo navegador. Operações e execuções ficam no mesmo SQLite `data/history/historico.sqlite3`. Em `logs/coleta.log` ficam os logs do coletor; o terminal exibe logs do servidor web.

O agendador não é criado pela aplicação automaticamente. Na página Configurações, use dry-run para visualizar; instalação, pausa, retomada e remoção pedem confirmação. Confirme o estado pela consulta do Windows. A tarefa executa na sessão do usuário conectado, sem janela de terminal, e requer que o usuário esteja conectado no horário programado.

O painel legado Streamlit continua disponível para compatibilidade com `py -m streamlit run scripts/painel.py`.

## Relatório de qualidade

```powershell
py -c "from src.engine.data_quality import DataQualityChecker; print(DataQualityChecker('reports').generate_quality_report('data/raw'))"
```

## Agendamento

A tarefa permanece inativa até a execução explícita do comando `install` abaixo. O wrapper fixa o diretório do projeto e encaminha resultados ao SQLite e ao log existente.

Comandos operacionais do agendador (somente `install` cria a tarefa):

```powershell
py scripts/agendamento_windows.py install --frequency weekly --time 06:00
py scripts/agendamento_windows.py query
py scripts/agendamento_windows.py pause
py scripts/agendamento_windows.py resume
py scripts/agendamento_windows.py remove
py scripts/agendamento_windows.py install --frequency daily --time 06:00 --dry-run
```

Frequências aceitas: `daily`, `weekly`, `monthly`; horário local `HH:MM`. A ação usa o interpretador Python corrente, caminho absoluto do projeto e um wrapper que fixa o diretório de trabalho; a tarefa executa em segundo plano sem terminal aberto. Ela roda na sessão do usuário atual e requer que ele esteja conectado ao Windows no horário marcado. Confirme a ativação com `py scripts/agendamento_windows.py query` ou `schtasks /Query /TN ObservatorioDiademaColeta /FO LIST /V`. Execuções gravam em SQLite e `logs/coleta.log`; o lock de coleta existente impede concorrência.

## Limitações

- A interface exige configuração do hash administrativo, segredo de sessão e, para a rede, certificado TLS confiável. Certificados e segredos não são gerados ou instalados automaticamente.
- O modo de rede requer IP/SAN compatível, usuário conectado ao Windows e liberação manual do firewall privado caso necessária.
- Cards Metabase sem frequência documentada continuam manuais. Fontes com autenticação são registradas como restritas, sem tentativa de contornar acesso.


## Google Sheets Central (exportacao opcional)

A exportacao envia uma copia dos CSVs locais pela API oficial Google Sheets. O SQLite `data/history/historico.sqlite3` continua como historico operacional e os CSVs permanecem em `data/raw`. Sao necessarios `google-api-python-client`, `google-auth`, `google-auth-httplib2` e `httplib2`, incluidos em `requirements.txt`, alem de uma conta de servico compartilhada como editora. As planilhas originais nunca sao alteradas.

Configure no PowerShell. O JSON da conta de servico deve ficar fora do repositorio e dos diretorios servidos pela aplicacao:

```powershell
$env:OPPES_SHEETS_EXPORT_SPREADSHEET_ID = "ID_DA_PLANILHA_DESTINO"
$env:OPPES_GOOGLE_SERVICE_ACCOUNT_FILE = "C:\caminho-seguro\oppes-service-account.json"
py -m pip install -r requirements.txt
```

No Google Cloud, selecione ou crie um projeto, habilite Google Sheets API, crie a conta de servico e baixe a chave JSON. Compartilhe a planilha de destino com o `client_email` como editora. No painel, abra Google Sheets Central, teste a conexao e exporte fontes escolhidas. Exportar todas exige confirmacao. Nada e exportado ao iniciar o sistema.

Cada fonte recebe uma aba de nome seguro com hash estavel do identificador; cards Metabase usam `dashboard_uuid:card_id`. `Controle_OPPES` registra fonte, aba e resultados. Os dados novos vao primeiro para uma aba temporaria; uma operacao `batchUpdate` troca a aba so depois do preparo. Valores sao enviados em `RAW`, em lotes, e nao executam formulas. O limite e 10 milhoes de celulas por aba; o sistema nao trunca dados. A conexao apenas confirma leitura; permissao de escrita requer uma exportacao real controlada. Sem credenciais, o painel permanece utilizavel e explica como configurar a integracao.


## Catálogo de fontes públicas oficiais (MVP)

O catálogo adicional `config/public_data_sources.json` registra as 15 fontes oficiais/referências solicitadas sem duplicar IPVS ou Receita Tributária. Uma página de apresentação não é tratada automaticamente como arquivo de dados: fontes sem recurso direto permanecem `limited` ou `pending`, até que a URL de exportação/API seja identificada. O painel Power BI é apenas uma referência; não há extração presumida do modelo semântico.

O novo pipeline é aditivo e não substitui o coletor Metabase/Google Sheets nem as rotas web existentes. Usa o histórico SQLite separado `data/history/public_sources.sqlite3`, guarda os downloads em `data/raw/<source_id>/` e CSVs em `data/processed/<source_id>/`. Arquivos originais são preservados; CSVs são escritos atomicamente; ZIPs têm proteção contra caminhos de extração e limite de tamanho configurável.

### Comandos (PowerShell)

```powershell
# Listar fontes e último resultado
py scripts/coletar_fontes_publicas.py list

# Histórico do pipeline público
py scripts/coletar_fontes_publicas.py history --limit 20

# Coletar somente quando já tiver confirmado a URL DIRETA e pública do recurso
py scripts/coletar_fontes_publicas.py collect infosiga_detran_sp --url "https://HOST-OFICIAL/arquivo.csv"

# Limitar download a 200 MiB e timeout de 20 segundos
py scripts/coletar_fontes_publicas.py --timeout 20 --max-download-mb 200 collect ID_DA_FONTE --url "https://HOST-OFICIAL/arquivo.zip"
```

A URL de exemplo acima é ilustrativa e não deve ser executada literalmente. Configure sempre a URL oficial real após confirmar que o recurso é público e permitido. O pipeline não contorna login/CAPTCHA. Dependências principais já existentes no projeto: `requests`, `pandas` e `openpyxl`; formatos XLS/ODS exigem os leitores correspondentes instalados. O pipeline registra sucesso/falha real no próprio SQLite e retorna código diferente de zero em falha.

**Limitações atuais:** descoberta automática de recursos CKAN e API genérica por página ainda não está ativada; para cada fonte, é necessário configurar `resource_url` ou passar `--url` depois de identificar o recurso direto. A lista de catálogo é um inventário inicial, não uma declaração de conectores validados. Arquivos JSON tabulares usam pandas; CSV/TXT preservam campos como texto. A execução em lotes de planilhas gigantes e a integração desse catálogo novo à interface web são etapas posteriores; as rotas atuais não foram alteradas nesta mudança.

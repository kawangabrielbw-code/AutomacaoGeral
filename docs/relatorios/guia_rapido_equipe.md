# Guia rápido da equipe

## Iniciar a interface Web

Instale as dependências uma vez: `py -m pip install -r requirements.txt`. Em PowerShell, prepare autenticação para a sessão atual e inicie localmente:

```powershell
$env:OPPES_ADMIN_PASSWORD_HASH = (py scripts/gerar_hash_senha.py)
$env:OPPES_SESSION_SECRET = (py -c "import secrets; print(secrets.token_urlsafe(48))")
py scripts/iniciar_web.py
```

Abra `http://127.0.0.1:8000`. O servidor local só aceita conexões deste computador; encerre com `Ctrl+C`. O hash é criado por prompt sem eco, não há senha padrão e a senha não é gravada em texto puro.

Para compartilhar na rede local, configure certificado e chave TLS com SAN do IPv4 do servidor e defina `OPPES_TLS_CERT` e `OPPES_TLS_KEY` para arquivos fora do repositório. Execute `py scripts/iniciar_web.py --rede`; o servidor exige TLS para endereços remotos e escuta em `0.0.0.0:8000`. Descubra o IPv4 executando `ipconfig` e acesse `https://IP-DO-COMPUTADOR:8000`. O navegador precisa confiar no certificado. Não abra o roteador; se necessário, peça ao administrador uma regra de firewall TCP 8000 restrita ao perfil Privado e `LocalSubnet`. O usuário Windows deve estar conectado para executar coletas agendadas. O launcher confere o par certificado/chave TLS e exige que ambos estejam fora do repositório.

O segredo da sessão e o hash devem ser definidos em cada nova sessão PowerShell. Não publique esses valores. O painel oferece Dashboard, Fontes, Coletas, Histórico e Configurações. Coletas em lote e alterações no Agendador pedem confirmação; as alterações usam o mesmo SQLite e lock dos comandos CLI. Em caso de falha, veja a mensagem no Histórico e `logs/coleta.log`.

O endpoint de rede requer HTTPS e senha administrativa. A aplicação não ativa tarefa Windows automaticamente.

## Coleta pela linha de comando

1. Ative o ambiente virtual e instale `requirements.txt` conforme o `README.md`.
2. Execute `py scripts/coletar_dados.py --fonte sheets` ou `--fonte metabase`; sem `--fonte`, coleta os dois grupos.
3. Consulte `py scripts/coletar_dados.py --status` para ver o histórico SQLite. `--vencidas` atualiza Sheets e cards Metabase configurados; `--vencidas-metabase` limita a cards.
4. Para repetir tentativas falhas de Sheets, use `py scripts/coletar_dados.py --falhas`.
5. Inicie o painel local com `py -m streamlit run scripts/painel.py`.
6. Configure as frequências reais dos cards em `config/metabase_cards.json` com a chave `dashboard_uuid:card_id`. Sem frequência definida, o card não entra em coleta automática. `data_coleta_utc` representa a consulta feita pelo robô; a competência permanece nos dados da fonte.
7. O agendamento opcional é gerenciado com `py scripts/agendamento_windows.py install --frequency weekly --time 06:00`; consulte, pause, retome ou remova com as ações `query`, `pause`, `resume` e `remove`. Confirme a tarefa no Windows com `py scripts/agendamento_windows.py query`. Ela roda em segundo plano na sessão do usuário atual, que precisa estar conectado; não existe tarefa criada por padrão.

Adicione planilhas públicas em `config/google_sheets.json`; não inclua credenciais nesse arquivo. Consulte `docs/relatorios/relatorio_final_projeto.md` para limitações.

## Validação segura

A autenticação exige hash PBKDF2 e segredo de sessão definidos no ambiente; a aplicação falha no startup se estiverem ausentes ou inválidos. Cookies ficam HttpOnly e SameSite Strict, com Secure em HTTPS; login renova o token CSRF. O launcher local usa apenas `127.0.0.1`; `--rede` exige certificado e chave válidos. Nenhuma tarefa é instalada automaticamente.


## Google Sheets Central

1. No Google Cloud, habilite Google Sheets API e crie uma conta de servico com chave JSON.
2. Compartilhe a planilha central com o `client_email` como editora.
3. Guarde o JSON fora do repositorio e configure no PowerShell:

```powershell
$env:OPPES_SHEETS_EXPORT_SPREADSHEET_ID = "ID_DA_PLANILHA_DESTINO"
$env:OPPES_GOOGLE_SERVICE_ACCOUNT_FILE = "C:\caminho-seguro\oppes-service-account.json"
```

Instale `requirements.txt`, inicie o painel e abra Google Sheets Central. Testar conexao confirma leitura; permissao de edicao precisa ser comprovada por uma exportacao real controlada. Se nao houver configuracao, a pagina explica o que falta. Os CSVs locais e o SQLite permanecem preservados.

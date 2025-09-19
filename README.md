AgRural → SQL Server (Soja)

Coletor simples e robusto que faz web scraping dos preços de Soja do site da AgRural, normaliza a tabela (inclusive com rowspan), e realiza UPSERT no SQL Server com chave composta data + uf + praca.
Inclui wrapper PowerShell e instruções para agendar no Windows (Task Scheduler).

⚠️ Uso responsável: execute no máximo 1–3 vezes por dia. Respeite os termos de uso e a disponibilidade do site-fonte.

✨ Principais recursos

Parser resiliente: expande rowspan, preenche UF herdada e converte números BR (1.234,56 → 1234.56).

Detecção de data junto ao título (“SOJA 18-Sep-25”). Fallback para a data do dia quando necessário.

UPSERT idempotente via MERGE (atualiza sem duplicar).

Somente grava quando houver data nova no site (evita reprocessos).

Compatível com Windows Auth (sem senha) e SQL Auth.

Automação com Task Scheduler + logs.

🧱 Arquitetura
agrural_soja_to_sqlserver_windows.py   # Scrape + transformação + upsert (CLI)
run_soja.ps1                           # Wrapper PowerShell (chama o .py e gera logs)
logs/                                  # Saída de logs (gitignored)


Linguagens e libs: Python 3.11+ (requests, beautifulsoup4, pandas, pyodbc) + PowerShell.

🗃️ Esquema da tabela

O script cria a tabela automaticamente se não existir:

CREATE TABLE dbo.PrecoSoja (
  [data]          date          NOT NULL,
  [uf]            char(2)       NOT NULL,
  [praca]         nvarchar(120) NOT NULL,
  [compra_rs_sc]  decimal(10,2) NOT NULL,
  [var_dia_pct]   decimal(6,2)  NULL,
  [var_sem_pct]   decimal(6,2)  NULL,
  [var_mes_pct]   decimal(6,2)  NULL,
  [fonte]         nvarchar(100) NOT NULL DEFAULT N'AgRural',
  [load_ts]       datetime2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
  CONSTRAINT PK_PrecoSoja PRIMARY KEY ([data],[uf],[praca])
);

⚙️ Requisitos

Python 3.11+

SQL Server (local, Express ou Azure SQL)

ODBC Driver 17/18 for SQL Server

pip install requests beautifulsoup4 pandas pyodbc

🚀 Como executar (manual)
Windows Authentication (sem senha)
# instalar dependências
py -m pip install --upgrade pip
py -m pip install requests beautifulsoup4 pandas pyodbc

# rodar o coletor
py .\agrural_soja_to_sqlserver_windows.py `
  --auth windows `
  --server "NOMEPC\SQLEXPRESS" `
  --database "CotacaoSoja" `
  --driver "ODBC Driver 18 for SQL Server" `
  --encrypt yes --trust yes


Se tiver erro de certificado: use --encrypt no ou troque o driver para "ODBC Driver 17 for SQL Server".

SQL Authentication (com usuário e senha)
py .\agrural_soja_to_sqlserver_windows.py `
  --auth sql --user "etl_user" --password "SUA_SENHA" `
  --server "seu-servidor,1433" --database "CotacaoSoja" `
  --driver "ODBC Driver 18 for SQL Server" --encrypt yes --trust yes

🤖 Automatização (Task Scheduler)

Edite run_soja.ps1 (já incluso) se precisar ajustar servidor/driver:

$SERVER  = "NOMEPC\SQLEXPRESS"
$DB      = "CotacaoSoja"
$DRIVER  = "ODBC Driver 18 for SQL Server"
$ENCRYPT = "yes"
$TRUST   = "yes"


O wrapper usa $PSScriptRoot, então funciona mesmo com caminhos do OneDrive/acentos.

Teste manual:

Set-ExecutionPolicy RemoteSigned -Scope CurrentUser   # 1ª vez
.\run_soja.ps1


Logs em .\logs\soja_YYYYMMDD_HHMMSS.log.

Crie a tarefa (GUI):

Programa/script: powershell.exe

Argumentos:

-NoProfile -ExecutionPolicy Bypass -File "CAMINHO\run_soja.ps1"


Start in (Iniciar em): pasta do projeto (recomendado).

Triggers: ex. 09:30 e 17:30 (seg–sex).

Geral: “Executar com privilégios mais altos” e “Executar somente quando o usuário estiver conectado”.

Configurações: “Executar a tarefa o mais cedo possível após um início perdido”.

🔍 Como o parser funciona

Localiza a tabela de Soja pela âncora do título e/ou cabeçalhos.

Expande rowspan para que cada linha tenha UF + Praça + valores.

Preenche UF faltante herdando da linha anterior (efeito do rowspan na coluna UF).

Converte números no formato BR para float.

Tenta extrair a data próxima ao título; se falhar, usa a data do dia.

Antes de gravar, compara a data do site com MAX(data) do banco:

Se igual ou menor → “Sem novidades…”

Se maior → MERGE (upsert) em dbo.PrecoSoja.

🧪 Consultas úteis
-- Última data e último carregamento
SELECT MAX([data]) AS data_mais_recente,
       MAX(load_ts) AS ultimo_load
FROM dbo.PrecoSoja;

-- View com a data corrente (para BI)
CREATE OR ALTER VIEW dbo.vw_PrecoSoja_Atual AS
SELECT *
FROM dbo.PrecoSoja
WHERE [data] = (SELECT MAX([data]) FROM dbo.PrecoSoja);

🛠️ Solução de problemas

UnicodeEncodeError no console
Remova emojis/acentos dos prints ou no run_soja.ps1 force UTF-8:

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'


“Driver not found / certificado”
Instale o ODBC 17/18 e ajuste --encrypt no ou --driver "ODBC Driver 17 for SQL Server".

py não encontrado no Agendador
No run_soja.ps1, troque:

$PY = "C:\Users\SEU_USUARIO\AppData\Local\Programs\Python\Python313\python.exe"


OneDrive com caminho acentuado
Use o wrapper (ele aceita Unicode). Ative “Sempre manter neste dispositivo”.

SQLEXPRESS (instância nomeada)
Se necessário, habilite TCP/IP e o SQL Server Browser no SQL Server Configuration Manager.

🧭 Roadmap (ideias)

Coleta da tabela de Milho (tabela dbo.PrecoMilho).

Export opcional .csv/.parquet no mesmo job.

GitHub Action (para ambientes com runner on-prem).

📁 .gitignore sugerido
logs/
*.log
*.pyc
__pycache__/
.venv/
.idea/

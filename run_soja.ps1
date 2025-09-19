$ErrorActionPreference = "Continue"   # não pare antes de gravar o log
# Força UTF-8 no PowerShell e no Python
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# === Caminhos ===
$PY     = "py"   # se preferir, coloque o caminho completo do Python aqui
$BASE   = $PSScriptRoot
$SCRIPT = Join-Path $BASE 'agrural_soja_to_sqlserver_windows.py'
$LOGDIR = Join-Path $BASE 'logs'
New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null
$LOG    = Join-Path $LOGDIR ("soja_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

# === Parâmetros SQL ===
$SERVER  = "BS-NOT-BS01Q1\SQLEXPRESS"
$DB      = "CotacaoSoja"
$DRIVER  = "ODBC Driver 18 for SQL Server"  # troque para 17 se precisar
$ENCRYPT = "yes"                             # "no" se der erro de certificado
$TRUST   = "yes"

# === Argumentos como ARRAY (preserva espaços e acentos) ===
$argsList = @(
    $SCRIPT, '--auth','windows',
    '--server', $SERVER,
    '--database', $DB,
    '--driver', $DRIVER,
    '--encrypt', $ENCRYPT,
    '--trust', $TRUST
)

"[INICIO] $(Get-Date)" | Tee-Object -FilePath $LOG -Append
# ...
("CMD: $PY " + ($argsList -join ' ')) | Tee-Object -FilePath $LOG -Append

# >>> ADICIONE ESTAS LINHAS <<<
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# >>>------------------------<<<

try {
    & $PY @argsList *>&1 | Tee-Object -FilePath $LOG -Append
    $rc = $LASTEXITCODE
} catch {
    "EXCEPTION: $($_.Exception.Message)" | Tee-Object -FilePath $LOG -Append
    $rc = 1
}

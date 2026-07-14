param(
    [string]$VenvPath = "venv_akshare",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root $VenvPath
$Python = Join-Path $Venv "Scripts\python.exe"

Set-Location $Root

if ($Recreate -and (Test-Path $Venv)) {
    Remove-Item -Recurse -Force $Venv
}

if (-not (Test-Path $Python)) {
    python -m venv $Venv
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }
& $Python -c "import numpy,pandas,flask,yaml,baostock,akshare; print('environment ok')"
if ($LASTEXITCODE -ne 0) { throw "dependency import check failed" }

Write-Host "Windows environment ready: $Python"

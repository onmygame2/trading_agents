param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsToRun
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Candidates = @(
    Join-Path $Root "venv_akshare\Scripts\python.exe",
    Join-Path $Root ".venv\Scripts\python.exe",
    "python"
)

$Python = $null
foreach ($Candidate in $Candidates) {
    if ($Candidate -eq "python" -or (Test-Path $Candidate)) {
        $Python = $Candidate
        break
    }
}

if (-not $Python) {
    Write-Error "Python executable not found."
    exit 1
}

Set-Location $Root
& $Python @ArgsToRun
exit $LASTEXITCODE

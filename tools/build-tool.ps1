[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }

Push-Location $repoRoot
try {
    & $python -m ruff format --check .
    & $python -m ruff check .
    & $python -m pytest
    & $python -m build
    $wheel = (Get-ChildItem dist\*.whl | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
    & $python -m pip install --force-reinstall --no-deps $wheel
    & $python -m chinaz_top_domains --version
}
finally {
    Pop-Location
}

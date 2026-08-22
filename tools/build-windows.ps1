[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }

Push-Location $repoRoot
try {
    & $python -m PyInstaller --noconfirm --clean chinaz-top-domains.spec
    & .\dist\chinaz-top-domains.exe --version
    & .\dist\chinaz-top-domains.exe --help | Out-Null

    $version = & $python -c "import chinaz_top_domains; print(chinaz_top_domains.__version__)"
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw 'Unable to determine the package version.'
    }
    $archive = "dist\chinaz-top-domains-v$version-windows-x86_64.zip"
    Compress-Archive -Path .\dist\chinaz-top-domains.exe, .\LICENSE, .\README.md -DestinationPath $archive -Force
    Write-Output $archive
}
finally {
    Pop-Location
}

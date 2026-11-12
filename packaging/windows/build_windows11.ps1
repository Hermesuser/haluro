#Requires -Version 5.1
<#
.SYNOPSIS
    Compiles, tests, and packages Haluro natively for Windows 11 (x64).

.DESCRIPTION
    Reproducible Windows 11 build pipeline:
      1. Creates an isolated virtual environment (`.venv`).
      2. Installs pinned runtime + PyInstaller + pytest dependencies.
      3. Runs the automated `pytest` quality gate and `--smoke-test` check.
      4. Resolves the version from `engine/__init__.py` (single source of truth)
         and renders the Inno Setup and PE-metadata templates.
      5. Compiles `dist\Haluro\Haluro.exe` via PyInstaller (`haluro.spec`).
      6. Verifies the frozen `Haluro.exe --smoke-test` binary.
      7. Creates `Haluro-Portable-<version>-Win11-x64.zip` and (when Inno Setup 6
         `ISCC.exe` is installed) `Haluro-Setup-<version>-Win11-x64.exe` + SHA-256 checksums.
#>

[CmdletBinding()]
param(
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RepoRoot

Write-Host "==> [1/7] Preparando entorno virtual aislado en $RepoRoot\.venv ..." -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$PyExe  = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PipExe = Join-Path $RepoRoot ".venv\Scripts\pip.exe"

& $PyExe -m pip install --upgrade pip wheel
& $PipExe install -r requirements-build.txt

if (-not $SkipTests) {
    Write-Host "==> [2/7] Ejecutando suite de pruebas automatizadas (pytest) ..." -ForegroundColor Cyan
    & $PyExe -m pytest -v

    Write-Host "==> [3/7] Verificando arranque de motor y puente nativo (--smoke-test) ..." -ForegroundColor Cyan
    & $PyExe native_app.py --smoke-test
}

# --- Version: single source of truth --------------------------------------
# The version lives in engine/__init__.py. Hardcoding it in this script is
# what previously produced a 2.4.6 release whose Windows artefacts were
# still named 2.4.5.
Write-Host "==> [4/7] Resolviendo versión desde engine/__init__.py ..." -ForegroundColor Cyan
$Version = (& $PyExe -c "import sys; sys.path.insert(0, '.'); from engine import __version__; print(__version__)").Trim()
if (-not $Version) { throw "No se pudo resolver la versión desde engine/__init__.py" }
$VersionParts = $Version.Split(".")
$Major = [int]$VersionParts[0]; $Minor = [int]$VersionParts[1]; $Patch = [int]$VersionParts[2]
Write-Host "    Versión: $Version" -ForegroundColor Green

# Render the Inno Setup script and the Win32 PE metadata from their templates.
$MetaDir = Join-Path $RepoRoot ".pkgmeta"
New-Item -ItemType Directory -Force -Path $MetaDir | Out-Null

$IssPath = Join-Path $MetaDir "haluro_installer.iss"
(Get-Content (Join-Path $RepoRoot "packaging\windows\haluro_installer.iss.in") -Raw) `
    -replace "@@VERSION@@", $Version | Set-Content -Path $IssPath -Encoding UTF8

$VersionInfoPath = Join-Path $RepoRoot "packaging\windows\version_info.txt"
(Get-Content (Join-Path $RepoRoot "packaging\windows\version_info.txt.in") -Raw) `
    -replace "@@VERSION@@", $Version `
    -replace "@@MAJOR@@", $Major `
    -replace "@@MINOR@@", $Minor `
    -replace "@@PATCH@@", $Patch | Set-Content -Path $VersionInfoPath -Encoding UTF8

Write-Host "==> [5/7] Compilando binario nativo Windows 11 (PyInstaller haluro.spec) ..." -ForegroundColor Cyan
if (Test-Path "build") { Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue }
if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue }

& $PyExe -m PyInstaller --noconfirm --clean haluro.spec

$FrozenExe = Join-Path $RepoRoot "dist\Haluro\Haluro.exe"
if (-not (Test-Path $FrozenExe)) {
    throw "No se generó el ejecutable esperado en $FrozenExe"
}

Write-Host "==> [6/7] Validando ejecutable compilado Haluro.exe --smoke-test ..." -ForegroundColor Cyan
$SmokeProc = Start-Process -FilePath $FrozenExe -ArgumentList "--smoke-test" -Wait -PassThru -NoNewWindow
if ($SmokeProc.ExitCode -ne 0) {
    throw "El smoke-test del ejecutable compilado falló con código $($SmokeProc.ExitCode)"
}

Write-Host "==> [7/7] Empaquetando distribución Portable (.zip) e Instalador Windows 11 (.exe) ..." -ForegroundColor Cyan
$PortableZip = Join-Path $RepoRoot "dist\Haluro-Portable-$Version-Win11-x64.zip"
Compress-Archive -Path (Join-Path $RepoRoot "dist\Haluro\*") -DestinationPath $PortableZip -Force

$IsccCandidates = @(
    (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if ($IsccCandidates.Count -gt 0) {
    $IsccExe = $IsccCandidates[0]
    Write-Host "    Compilando instalador moderno con Inno Setup ($IsccExe) ..." -ForegroundColor Green
    & $IsccExe $IssPath
} else {
    Write-Warning "Inno Setup 6 (ISCC.exe) no detectado; se generó el paquete Portable listo para usar: $PortableZip"
}

# Generate SHA-256 integrity manifest
$Artifacts = Get-ChildItem -Path (Join-Path $RepoRoot "dist") -File | Where-Object { $_.Extension -in ".exe", ".zip" }
$HashLines = foreach ($file in $Artifacts) {
    $hash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($file.Name)"
}
$ChecksumPath = Join-Path $RepoRoot "dist\SHA256SUMS-Windows11.txt"
$HashLines | Set-Content -Path $ChecksumPath -Encoding UTF8

Write-Host "`nCompilación Windows 11 finalizada con éxito:" -ForegroundColor Green
Get-ChildItem -Path (Join-Path $RepoRoot "dist") -File | Select-Object Name, Length

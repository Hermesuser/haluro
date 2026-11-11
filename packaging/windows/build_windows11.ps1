#Requires -Version 5.1
<#
.SYNOPSIS
    Compiles, tests, and packages Haluro v2.4.4 natively for Windows 11 (x64).

.DESCRIPTION
    Google-standard reproducible Windows 11 build pipeline:
      1. Creates an isolated virtual environment (`.venv`).
      2. Installs pinned runtime + PyInstaller + pytest dependencies.
      3. Runs the automated `pytest` quality gate and `--smoke-test` check.
      4. Compiles `dist\Haluro\Haluro.exe` via PyInstaller (`haluro.spec`).
      5. Verifies the frozen `Haluro.exe --smoke-test` binary.
      6. Creates `Haluro-Portable-2.4.4-Win11-x64.zip` and (when Inno Setup 6
         `ISCC.exe` is installed) `Haluro-Setup-2.4.4-Win11-x64.exe` + SHA-256 checksums.
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

$Version = "2.4.4"
Write-Host "==> [1/6] Preparando entorno virtual aislado en $RepoRoot\.venv ..." -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$PyExe  = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PipExe = Join-Path $RepoRoot ".venv\Scripts\pip.exe"

& $PyExe -m pip install --upgrade pip wheel
& $PipExe install -r requirements-build.txt

if (-not $SkipTests) {
    Write-Host "==> [2/6] Ejecutando suite de pruebas automatizadas (pytest) ..." -ForegroundColor Cyan
    & $PyExe -m pytest -v

    Write-Host "==> [3/6] Verificando arranque de motor y puente nativo (--smoke-test) ..." -ForegroundColor Cyan
    & $PyExe native_app.py --smoke-test
}

Write-Host "==> [4/6] Compilando binario nativo Windows 11 (PyInstaller haluro.spec) ..." -ForegroundColor Cyan
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" }

& $PyExe -m PyInstaller --noconfirm --clean haluro.spec

$FrozenExe = Join-Path $RepoRoot "dist\Haluro\Haluro.exe"
if (-not (Test-Path $FrozenExe)) {
    throw "No se generó el ejecutable esperado en $FrozenExe"
}

Write-Host "==> [5/6] Validando ejecutable compilado Haluro.exe --smoke-test ..." -ForegroundColor Cyan
$SmokeProc = Start-Process -FilePath $FrozenExe -ArgumentList "--smoke-test" -Wait -PassThru -NoNewWindow
if ($SmokeProc.ExitCode -ne 0) {
    throw "El smoke-test del ejecutable compilado falló con código $($SmokeProc.ExitCode)"
}

Write-Host "==> [6/6] Empaquetando distribución Portable (.zip) e Instalador Windows 11 (.exe) ..." -ForegroundColor Cyan
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
    & $IsccExe (Join-Path $RepoRoot "packaging\windows\haluro_installer.iss")
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

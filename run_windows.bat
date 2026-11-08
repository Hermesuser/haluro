@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Haluro — Laboratorio Analogico Digital (Windows 11)

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ no esta instalado o no figura en el PATH de Windows 11.
    echo Descargalo desde https://www.python.org/downloads/windows/ marcando "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo [Haluro] Configurando entorno local por primera vez en Windows 11...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] No se pudieron instalar las dependencias de Haluro.
        pause
        exit /b 1
    )
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0native_app.py"
exit /b 0

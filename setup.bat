@echo off
title Instalador de Dependencias NovaMusic
color 0A

echo ==========================================
echo      CONFIGURANDO ENTORNO NOVA MUSIC      
echo ==========================================
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    pause
    exit
)
echo [OK] Python detectado.

:: 2. Crear Entorno Virtual
if not exist "venv" (
    echo [INFO] Creando entorno virtual (venv)...
    python -m venv venv
) else (
    echo [INFO] El entorno virtual ya existe.
)

:: 3. Instalar Dependencias de Python
echo [INFO] Instalando librerias desde requirements.txt...
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip install -r requirements.txt

:: 4. Verificar FFmpeg (Crucial para el audio)
echo.
echo [INFO] Verificando FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ALERTA] FFmpeg no detectado en el sistema.
    echo [INFO] Intentando instalar via Winget...
    winget install Gyan.FFmpeg
    echo.
    echo [IMPORTANTE] Si FFmpeg se acaba de instalar, REINICIA VS CODE para que lo detecte.
) else (
    echo [OK] FFmpeg esta instalado y listo.
)

echo.
echo ==========================================
echo      INSTALACION COMPLETA - LISTO!        
echo ==========================================
echo.
echo Para iniciar el bot, usa: start_bot.bat (o activa el venv manual)
pause
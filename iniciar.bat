@echo off
chcp 65001 >nul
title Conversor de Video para Audio
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add Python to PATH".
  pause
  exit /b 1
)

%PY% -c "import imageio_ffmpeg, tkinterdnd2" >nul 2>nul
if errorlevel 1 (
  echo Instalando componentes na primeira vez, aguarde...
  %PY% -m pip install --quiet imageio-ffmpeg tkinterdnd2
)

start "" %PY% conversor.py

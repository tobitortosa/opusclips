@echo off
title Maquina de clips
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Preparando el entorno por primera vez...
  python -m venv .venv --system-site-packages || goto :error
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)
.venv\Scripts\python.exe app.py
if errorlevel 1 goto :error
exit /b 0
:error
echo.
echo Algo fallo. Copiá el mensaje de arriba.
pause

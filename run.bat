@echo off
setlocal
cd /d "%~dp0"
title MR.Robot - Cyber AI Agent
color 0A

REM Find a Python 3.10+ launcher: py first, then python, then python3.
set "PYLAUNCH="

py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYLAUNCH=py -3"
if defined PYLAUNCH goto havepy

python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYLAUNCH=python"
if defined PYLAUNCH goto havepy

python3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYLAUNCH=python3"
if defined PYLAUNCH goto havepy

echo  [!] ERROR: Python 3.10 or newer was not found.
echo      Install Python from python.org and tick the Add to PATH option during setup.
pause
exit /b 1

:havepy
echo  [*] Using Python launcher: %PYLAUNCH%

REM Create the isolated environment on first run only.
if not exist .venv\Scripts\python.exe (
    echo  [*] Creating isolated environment .venv ...
    %PYLAUNCH% -m venv .venv
)
if not exist .venv\Scripts\python.exe (
    echo  [!] ERROR: Failed to create .venv
    pause
    exit /b 1
)

echo  [*] Installing dependencies inside .venv only ...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo  [!] ERROR: Dependency install failed. Check your internet connection.
    pause
    exit /b 1
)

if not exist .env (
    echo  [!] .env is missing.
    echo      Create .env from the .env.example template with your NEW bot token and your Telegram user ID.
    pause
    exit /b 1
)

echo  [*] Starting bot ... Press CTRL+C to stop.
.venv\Scripts\python.exe main.py

echo.
echo  [*] Bot stopped.
pause

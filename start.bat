@echo off
REM ════════════════════════════════════════════════════════════
REM   LinkSift Agent — one-click startup (Windows)
REM ════════════════════════════════════════════════════════════
REM   Double-click this file to start the server.

setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   LinkSift Agent - Startup
echo ============================================
echo.

REM ── 1. Check Python ─────────────────────────────────────────
echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python is not installed or not in PATH.
    echo   Install from https://www.python.org/downloads/ (need 3.10+)
    echo   IMPORTANT: Check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo   OK %%i

REM ── 2. Check Node.js ────────────────────────────────────────
echo Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo X Node.js is not installed or not in PATH.
    echo   The Claude Agent SDK needs Node.js to run.
    echo   Install LTS from https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do echo   OK Node.js %%i

REM ── 3. Virtualenv & deps ────────────────────────────────────
cd backend
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo   OK Dependencies installed

REM ── 4. API key ──────────────────────────────────────────────
if "%ANTHROPIC_API_KEY%"=="" (
    if exist "..\.env" (
        for /f "usebackq tokens=1,* delims==" %%a in ("..\.env") do (
            if /i "%%a"=="ANTHROPIC_API_KEY" set ANTHROPIC_API_KEY=%%b
        )
    )
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo.
    echo Anthropic API key not found.
    echo Get one at: https://console.anthropic.com/settings/keys
    echo.
    set /p ANTHROPIC_API_KEY="Paste your API key (sk-ant-...): "
    echo ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY%> ..\.env
    echo   OK Saved to .env for next time
)

REM ── 5. Start server ─────────────────────────────────────────
echo.
echo ============================================
echo   Server starting at:
echo   ^> http://localhost:8000
echo.
echo   Press Ctrl+C to stop
echo ============================================
echo.

REM Open browser after a short delay
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

uvicorn server:app --host 0.0.0.0 --port 8000

pause

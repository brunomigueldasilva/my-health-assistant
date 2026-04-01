@echo off
:: ──────────────────────────────────────────────────────────────────────────────
:: MyHealthAssistant — Setup script (Windows)
:: Usage: setup.bat
:: ──────────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set VENV_DIR=.venv
set MISSING_KEYS=

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║      MyHealthAssistant — Setup                   ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: ── 1. Check Python ──────────────────────────────────────────────────────────
echo [1/7] Checking Python version...

set PYTHON_BIN=
for %%p in (python3.13 python3.12 python3.11 python3 python) do (
    if "!PYTHON_BIN!"=="" (
        where %%p >nul 2>&1
        if !errorlevel! == 0 (
            for /f "tokens=*" %%v in ('%%p -c "import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")" 2^>nul') do (
                set VER=%%v
            )
            for /f "tokens=1,2 delims=." %%a in ("!VER!") do (
                if %%a geq 3 (
                    if %%b geq 11 (
                        set PYTHON_BIN=%%p
                        echo [OK] Found %%p ^(Python !VER!^)
                    )
                )
            )
        )
    )
)

if "!PYTHON_BIN!"=="" (
    echo [ERROR] Python 3.11+ not found.
    echo         Download from: https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: ── 2. Create virtual environment ────────────────────────────────────────────
echo.
echo [2/7] Creating virtual environment (%VENV_DIR%)...

if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [!]  Virtual environment already exists — skipping creation.
) else (
    !PYTHON_BIN! -m venv %VENV_DIR%
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: ── 3. Activate venv ─────────────────────────────────────────────────────────
call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] Virtual environment activated.

:: ── 4. Upgrade pip ───────────────────────────────────────────────────────────
echo.
echo [3/7] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip upgraded.

:: ── 5. Install dependencies ──────────────────────────────────────────────────
echo.
echo [4/7] Installing Python dependencies...

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found.
    echo         Make sure you are running this script from the project root directory.
    pause
    exit /b 1
)

pip install -r requirements.txt --quiet
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies. Check the output above.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: ── 6. Install Playwright browsers ───────────────────────────────────────────
echo.
echo [5/7] Installing Playwright ^(Chromium^)...
playwright install chromium
echo [OK] Playwright Chromium installed.

:: ── 7. Copy .env ─────────────────────────────────────────────────────────────
echo.
echo [6/7] Configuring environment...

if exist ".env" (
    echo [!]  .env already exists — keeping existing file.
) else (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [OK] .env created from .env.example.
    ) else (
        echo [!]  .env.example not found — skipping .env creation.
    )
)

:: ── 8. Validate .env ─────────────────────────────────────────────────────────
echo.
echo [7/7] Validating .env...

set MISSING_COUNT=0

:: Check LLM_PROVIDER
set LLM_PROVIDER=
for /f "tokens=2 delims==" %%a in ('findstr /i "^LLM_PROVIDER" .env 2^>nul') do set LLM_PROVIDER=%%a
set LLM_PROVIDER=!LLM_PROVIDER: =!

if "!LLM_PROVIDER!"=="" (
    echo [!]  Missing: LLM_PROVIDER
    set /a MISSING_COUNT+=1
) else if "!LLM_PROVIDER!"=="your_provider" (
    echo [!]  Missing: LLM_PROVIDER ^(still set to placeholder^)
    set /a MISSING_COUNT+=1
) else (
    echo [OK] LLM_PROVIDER = !LLM_PROVIDER!
)

:: Check TELEGRAM_BOT_TOKEN
set TG_TOKEN=
for /f "tokens=2 delims==" %%a in ('findstr /i "^TELEGRAM_BOT_TOKEN" .env 2^>nul') do set TG_TOKEN=%%a
set TG_TOKEN=!TG_TOKEN: =!

if "!TG_TOKEN!"=="" (
    echo [!]  Missing: TELEGRAM_BOT_TOKEN
    set /a MISSING_COUNT+=1
) else if "!TG_TOKEN!"=="your_telegram_bot_token" (
    echo [!]  Missing: TELEGRAM_BOT_TOKEN ^(still set to placeholder^)
    set /a MISSING_COUNT+=1
) else (
    set PREVIEW=!TG_TOKEN:~0,10!
    echo [OK] TELEGRAM_BOT_TOKEN = !PREVIEW!...
)

echo.
if !MISSING_COUNT! gtr 0 (
    echo [!]  Some values in .env need to be filled in before running.
    echo      Open .env in a text editor, fill in the missing values,
    echo      then run: python main.py
) else (
    echo [OK] All required .env values are set.
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ════════════════════════════════════════════════════
echo  Setup complete!
echo ════════════════════════════════════════════════════
echo.
echo  To start the assistant:
echo    %VENV_DIR%\Scripts\activate.bat
echo    python main.py
echo.
echo  Interfaces:
echo    - Telegram Bot  : search for your bot in Telegram
echo    - Gradio Web UI : http://localhost:7860
echo.
pause

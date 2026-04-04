@echo off
:: ──────────────────────────────────────────────────────────────────────────────
:: MyHealthAssistant - Setup script (Windows)
:: Usage: scripts\setup.bat   (from the project root)
::        OR:  cd scripts && setup.bat
:: ──────────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

:: Change to the project root regardless of where the script is called from
cd /d "%~dp0.."

set VENV_DIR=.venv
set MISSING_KEYS=

echo.
echo +--------------------------------------------------+
echo ^|      MyHealthAssistant - Setup                   ^|
echo +--------------------------------------------------+
echo.

:: ── 1. Check Python ──────────────────────────────────────────────────────────
echo [1/8] Checking Python version...

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
echo [2/8] Creating virtual environment (%VENV_DIR%)...

if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists - skipping creation.
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
echo [3/8] Upgrading pip...
python -m pip install --upgrade pip
echo [OK] pip upgraded.

:: ── 5. Install dependencies ──────────────────────────────────────────────────
echo.
echo [4/8] Installing Python dependencies...

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found.
    echo         Make sure you are running this script from the project root directory.
    pause
    exit /b 1
)

pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies. Check the output above.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: ── 6. Install Playwright browsers ───────────────────────────────────────────
echo.
echo [5/8] Installing Playwright ^(Chromium^)...
playwright install chromium
echo [OK] Playwright Chromium installed.

:: ── 7. Copy .env ─────────────────────────────────────────────────────────────
echo.
echo [6/8] Configuring environment...

if exist ".env" (
    echo [OK] .env already exists - keeping existing file.
) else (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [OK] .env created from .env.example.
    ) else (
        echo [WARN] .env.example not found - skipping .env creation.
    )
)

:: ── 8. Validate .env ─────────────────────────────────────────────────────────
echo.
echo [7/8] Validating .env...

set MISSING_LLM=0
set MISSING_KEY=0

:: Check LLM_PROVIDER
set LLM_PROVIDER=
for /f "tokens=2 delims==" %%a in ('findstr /i "^LLM_PROVIDER" .env 2^>nul') do set LLM_PROVIDER=%%a
set LLM_PROVIDER=!LLM_PROVIDER: =!

if "!LLM_PROVIDER!"=="" (
    echo [WARN] Missing: LLM_PROVIDER
    set MISSING_LLM=1
) else if "!LLM_PROVIDER!"=="your_provider" (
    echo [WARN] Missing: LLM_PROVIDER ^(still set to placeholder^)
    set MISSING_LLM=1
) else (
    echo [OK] LLM_PROVIDER = !LLM_PROVIDER!
)

:: Check SECRET_KEY
set SECRET_KEY=
for /f "tokens=1* delims==" %%a in ('findstr /i "^SECRET_KEY" .env 2^>nul') do set SECRET_KEY=%%b
set SECRET_KEY=!SECRET_KEY: =!

if "!SECRET_KEY!"=="" (
    echo [INFO] SECRET_KEY not set - generating one automatically...
    for /f "tokens=*" %%k in ('python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"') do set NEW_KEY=%%k
    echo SECRET_KEY=!NEW_KEY!>> .env
    echo [OK] SECRET_KEY generated and added to .env.
) else if "!SECRET_KEY!"=="your_fernet_key_here" (
    echo [INFO] SECRET_KEY is placeholder - generating one automatically...
    for /f "tokens=*" %%k in ('python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"') do set NEW_KEY=%%k
    python -c "content=open('.env').read(); open('.env','w').write(content.replace('SECRET_KEY=your_fernet_key_here','SECRET_KEY=!NEW_KEY!'))"
    echo [OK] SECRET_KEY generated and replaced in .env.
) else (
    echo [OK] SECRET_KEY is set.
)

:: ── 9. Telegram bot token ─────────────────────────────────────────────────────
echo.
echo [8/8] Checking Telegram bot token...

set TG_STATUS=missing
for /f "tokens=*" %%r in ('python scripts\check_telegram.py 2^>nul') do set TG_STATUS=%%r

if "!TG_STATUS!"=="ok" (
    echo [OK] Telegram bot token already configured in the credential store.
) else (
    echo [WARN] Telegram bot token not yet configured.
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ==================================================
echo  Setup complete!
echo ==================================================
echo.
echo  Next steps - activate the virtual environment:
echo    CMD:        .venv\Scripts\activate.bat
echo    PowerShell: .venv\Scripts\Activate.ps1
echo.
echo  NOTE: .venv is in the project root, not in scripts\
echo.

set STEP=1

echo  !STEP!. Confirm your LLM provider in .env:
echo       LLM_PROVIDER=ollama   # or gemini / openai / anthropic / lmstudio
echo.
set /a STEP+=1


if "!TG_STATUS!" neq "ok" (
    echo  !STEP!. Save the Telegram bot token ^(required before starting^):
    echo       python scripts\setup_telegram.py
    echo.
    set /a STEP+=1
)

echo  !STEP!. Start the assistant:
echo       python main.py
set /a STEP+=1
echo.
echo  !STEP!. Send /start to your bot in Telegram to create your profile
echo       Or open http://localhost:7860 and click + Create new account
set /a STEP+=1
echo.
echo  !STEP!. Optional integrations ^(after creating your profile^):
echo       Tanita : python scripts\setup_credentials.py
echo       Garmin : python scripts\garmin_browser_auth.py --user ^<user_id^>
echo.
pause

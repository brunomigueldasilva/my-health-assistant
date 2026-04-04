#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# MyHealthAssistant — Setup script (macOS / Linux)
# Usage: bash scripts/setup.sh   (from the project root)
#        OR:  cd scripts && bash setup.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Change to the project root regardless of where the script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR=".venv"
PYTHON_MIN="3.11"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}[✔]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✘]${NC} $*"; exit 1; }
info() { echo -e "${CYAN}[i]${NC} $*"; }
step() { echo -e "\n${BOLD}$*${NC}"; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║      MyHealthAssistant — Setup                   ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Check Python ───────────────────────────────────────────────────────────
step "1. Checking Python version..."

PYTHON_BIN=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_BIN="$cmd"
            ok "Found $cmd (Python $ver)"
            break
        fi
    fi
done

[ -z "$PYTHON_BIN" ] && err "Python $PYTHON_MIN+ not found. Install it from https://www.python.org/downloads/"

# ── 2. Create virtual environment ─────────────────────────────────────────────
step "2. Creating virtual environment ($VENV_DIR)..."

if [ -d "$VENV_DIR" ]; then
    warn "Virtual environment already exists — skipping creation."
else
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    ok "Virtual environment created."
fi

# ── 3. Activate venv ──────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Virtual environment activated."

# ── 4. Upgrade pip ────────────────────────────────────────────────────────────
step "3. Upgrading pip..."
pip install --upgrade pip --quiet
ok "pip upgraded."

# ── 5. Install dependencies ───────────────────────────────────────────────────
step "4. Installing Python dependencies..."

if [ ! -f "requirements.txt" ]; then
    err "requirements.txt not found. Are you running this from the project root?"
fi

pip install -r requirements.txt --quiet
ok "Dependencies installed."

# ── 6. Install Playwright browsers ───────────────────────────────────────────
step "5. Installing Playwright (Chromium)..."
playwright install chromium --quiet 2>/dev/null || {
    warn "Playwright install may have printed warnings above — this is usually harmless."
}
ok "Playwright Chromium installed."

# ── 7. Copy .env ─────────────────────────────────────────────────────────────
step "6. Configuring environment..."

if [ -f ".env" ]; then
    warn ".env already exists — keeping existing file."
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        ok ".env created from .env.example."
    else
        warn ".env.example not found — skipping .env creation."
    fi
fi

# ── 8. Validate .env ─────────────────────────────────────────────────────────
step "7. Validating .env..."

missing=()

# LLM_PROVIDER
provider=$(grep -E "^LLM_PROVIDER\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
if [ -z "$provider" ] || [ "$provider" = "your_provider" ]; then
    missing+=("LLM_PROVIDER")
else
    ok "LLM_PROVIDER = $provider"
    case "$provider" in
        ollama)
            host=$(grep -E "^OLLAMA_HOST\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
            [ -z "$host" ] && missing+=("OLLAMA_HOST")
            ;;
        gemini)
            key=$(grep -E "^GOOGLE_API_KEY\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
            [ -z "$key" ] || [ "$key" = "your_google_api_key" ] && missing+=("GOOGLE_API_KEY")
            ;;
        openai)
            key=$(grep -E "^OPENAI_API_KEY\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
            [ -z "$key" ] || [ "$key" = "your_openai_api_key" ] && missing+=("OPENAI_API_KEY")
            ;;
        anthropic)
            key=$(grep -E "^ANTHROPIC_API_KEY\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
            [ -z "$key" ] || [ "$key" = "your_anthropic_api_key" ] && missing+=("ANTHROPIC_API_KEY")
            ;;
        lmstudio)
            host=$(grep -E "^LMSTUDIO_HOST\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
            [ -z "$host" ] && missing+=("LMSTUDIO_HOST")
            ;;
    esac
fi

# SECRET_KEY
secret=$(grep -E "^SECRET_KEY\s*=" .env 2>/dev/null | cut -d= -f2 | tr -d ' "' || true)
if [ -z "$secret" ] || [ "$secret" = "your_fernet_key_here" ]; then
    missing+=("SECRET_KEY")
else
    ok "SECRET_KEY is set."
fi

if [ ${#missing[@]} -gt 0 ]; then
    warn "The following values must be set in .env before running:"
    for k in "${missing[@]}"; do
        echo -e "    ${RED}•${NC} $k"
    done
else
    ok "All required .env values are set."
fi

# ── 8. Telegram bot token ─────────────────────────────────────────────────────
step "8. Checking Telegram bot token..."

token_stored=$("$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '.')
try:
    from tools.credential_store import get_telegram_token
    print('ok' if get_telegram_token() else 'missing')
except Exception:
    print('missing')
" 2>/dev/null || echo "missing")

if [ "$token_stored" = "ok" ]; then
    ok "Telegram bot token already configured in the credential store."
else
    warn "Telegram bot token not yet configured."
fi

# ── 9. Done ───────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Setup complete!${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo -e "  ${BOLD}source $VENV_DIR/bin/activate${NC}"
echo ""

step_n=1

# Step 2 (README): LLM provider — only if not configured
if printf '%s\n' "${missing[@]}" | grep -qE "LLM_PROVIDER|API_KEY|HOST"; then
    echo -e "  ${YELLOW}${step_n}.${NC} Set your LLM provider in ${BOLD}.env${NC} (see README step 2):"
    echo -e "     ${BOLD}LLM_PROVIDER=ollama${NC}  # or gemini / openai / anthropic / lmstudio"
    echo ""
    step_n=$((step_n + 1))
fi

# Step 3 (README): SECRET_KEY — only if not set
if printf '%s\n' "${missing[@]}" | grep -q "SECRET_KEY"; then
    echo -e "  ${YELLOW}${step_n}.${NC} Generate the encryption key and add it to ${BOLD}.env${NC} as SECRET_KEY:"
    echo -e '     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    echo ""
    step_n=$((step_n + 1))
fi

# Step 4 (README): Telegram token — only if not configured
if [ "$token_stored" != "ok" ]; then
    echo -e "  ${YELLOW}${step_n}.${NC} Save the Telegram bot token (required before starting):"
    echo -e "     ${BOLD}python scripts/setup_telegram.py${NC}"
    echo ""
    step_n=$((step_n + 1))
fi

# Step 5 (README): Start
echo -e "  ${YELLOW}${step_n}.${NC} Start the assistant:"
echo -e "     ${BOLD}python main.py${NC}"
echo ""
step_n=$((step_n + 1))

# Step 6 (README): Onboarding
echo -e "  ${YELLOW}${step_n}.${NC} Send ${BOLD}/start${NC} to your bot in Telegram to create your profile"
echo -e "     Or open ${BOLD}http://localhost:7860${NC} and click ➕ Create new account"
echo ""
step_n=$((step_n + 1))

# Step 7 (README): Optional integrations
echo -e "  ${YELLOW}${step_n}.${NC} Optional integrations (after creating your profile):"
echo -e "     Tanita:  ${BOLD}python scripts/setup_credentials.py${NC}"
echo -e "     Garmin:  ${BOLD}python scripts/garmin_browser_auth.py --user <user_id>${NC}"
echo ""

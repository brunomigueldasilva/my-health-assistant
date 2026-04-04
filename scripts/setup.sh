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

if [ ${#missing[@]} -gt 0 ]; then
    warn "The following values must be set in .env before running:"
    for k in "${missing[@]}"; do
        echo -e "    ${RED}•${NC} $k"
    done
    echo ""
    warn "Edit .env and re-run: ${BOLD}source $VENV_DIR/bin/activate && python main.py${NC}"
else
    ok "All required .env values are set."
fi

# ── 8. Telegram bot token ─────────────────────────────────────────────────────
step "8. Configurando token do bot Telegram..."

# Check if token already stored in credential store
token_stored=$("$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '.')
try:
    from tools.credential_store import get_telegram_token
    t = get_telegram_token()
    print('ok' if t else 'missing')
except Exception as e:
    print('missing')
" 2>/dev/null || echo "missing")

if [ "$token_stored" = "ok" ]; then
    ok "Token do Telegram já configurado no credential store."
else
    warn "Token do Telegram ainda não configurado."
    echo ""
    info "Obtém o token no @BotFather do Telegram e executa:"
    echo -e "  ${BOLD}source $VENV_DIR/bin/activate && python scripts/setup_telegram.py${NC}"
    echo ""
fi

# ── 9. Done ───────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Setup completo!${NC}"
echo ""
echo -e "${BOLD}Passos seguintes:${NC}"
echo -e "  ${BOLD}source $VENV_DIR/bin/activate${NC}"
echo ""
if [ "$token_stored" != "ok" ]; then
    echo -e "  ${YELLOW}1.${NC} Guarda o token do bot Telegram (necessário antes de iniciar):"
    echo -e "     ${BOLD}python scripts/setup_telegram.py${NC}"
    echo ""
    echo -e "  ${YELLOW}2.${NC} Inicia o assistente:"
    echo -e "     ${BOLD}python main.py${NC}"
    echo ""
    echo -e "  ${YELLOW}3.${NC} Envia ${BOLD}/start${NC} ao teu bot no Telegram para criar o perfil"
    echo ""
    echo -e "  ${YELLOW}4.${NC} Configura serviços opcionais (após criar o perfil):"
    echo -e "     Tanita:  ${BOLD}python scripts/setup_credentials.py${NC}"
    echo -e "     Garmin:  ${BOLD}python scripts/garmin_browser_auth.py --user <id>${NC}"
else
    echo -e "  ${YELLOW}1.${NC} Inicia o assistente:"
    echo -e "     ${BOLD}python main.py${NC}"
    echo ""
    echo -e "  ${YELLOW}2.${NC} Envia ${BOLD}/start${NC} ao teu bot no Telegram para criar o perfil"
    echo ""
    echo -e "  ${YELLOW}3.${NC} Configura serviços opcionais (após criar o perfil):"
    echo -e "     Tanita:  ${BOLD}python scripts/setup_credentials.py${NC}"
    echo -e "     Garmin:  ${BOLD}python scripts/garmin_browser_auth.py --user <id>${NC}"
fi
echo ""
echo -e "Interface web: ${BOLD}http://localhost:7860${NC}"
echo ""

"""
Centralized project configuration.
Loads environment variables and defines constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ╔══════════════════════════════════════════════════════╗
# ║                      PATHS                           ║
# ╚══════════════════════════════════════════════════════╝

BASE_DIR        = Path(__file__).resolve().parent.parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = DATA_DIR / "chromadb"
SQLITE_DB       = DATA_DIR / "user_profiles.db"
SQLITE_SESSIONS = DATA_DIR / "sessions.db"

DATA_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

# ╔══════════════════════════════════════════════════════╗
# ║                   LLM / MODELS                       ║
# ╚══════════════════════════════════════════════════════╝

# Active provider — set LLM_PROVIDER in .env
# Options: ollama | gemini | openai | anthropic | lmstudio
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

# ── Ollama (local) ────────────────────────────────────
# Recommended: qwen2.5:32b (best tool calling — requires 24GB+ VRAM)
# Alternatives: qwen2.5:14b, qwen2.5:7b, qwen3:8b, llama3.1:8b
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
# num_ctx: context window size (smaller = faster, default ~8192)
# num_predict: max output tokens (limits response length)
OLLAMA_NUM_CTX     = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "1024"))

# ── LM Studio (local, OpenAI-compatible) ─────────────
# Enable the local server in LM Studio (default port 1234)
# Set LMSTUDIO_MODEL to the identifier shown in LM Studio
LMSTUDIO_HOST  = os.getenv("LMSTUDIO_HOST", "http://localhost:1234/v1")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "qwen3:8b")

# ── Gemini (Google) ───────────────────────────────────
# Requires GOOGLE_API_KEY in .env
# Recommended: gemini-2.5-flash
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── OpenAI ────────────────────────────────────────────
# Requires OPENAI_API_KEY in .env
# Recommended: gpt-4o | gpt-4o-mini | gpt-4-turbo | gpt-3.5-turbo
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Anthropic (Claude) ────────────────────────────────
# Requires ANTHROPIC_API_KEY in .env
# Recommended: claude-sonnet-4-6 | claude-opus-4-6 | claude-haiku-4-5-20251001
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ╔══════════════════════════════════════════════════════╗
# ║                    TELEGRAM                          ║
# ╚══════════════════════════════════════════════════════╝

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ╔══════════════════════════════════════════════════════╗
# ║              CREDENTIALS / ENCRYPTION               ║
# ╚══════════════════════════════════════════════════════╝

# Master key for Fernet encryption of per-user credentials stored in SQLite.
# Generate once: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SECRET_KEY = os.getenv("SECRET_KEY", "")

# ╔══════════════════════════════════════════════════════╗
# ║                    CHROMADB                          ║
# ╚══════════════════════════════════════════════════════╝

CHROMA_COLLECTION_PREFERENCES = "user_preferences"
CHROMA_COLLECTION_NUTRITION   = "nutrition_knowledge"
CHROMA_COLLECTION_EXERCISES   = "exercise_knowledge"

# ╔══════════════════════════════════════════════════════╗
# ║                  DEBUG / LOGGING                     ║
# ╚══════════════════════════════════════════════════════╝

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")

# ╔══════════════════════════════════════════════════════╗
# ║                   MODEL FACTORY                      ║
# ╚══════════════════════════════════════════════════════╝

def get_model():
    """Return the Agno model instance based on LLM_PROVIDER.

    Supported providers (set LLM_PROVIDER in .env):
      ollama     — local models via Ollama (default)
      gemini     — Google Gemini API
      openai     — OpenAI API (GPT-4o, GPT-4, GPT-3.5, etc.)
      anthropic  — Anthropic API (Claude Sonnet, Opus, Haiku)
      lmstudio   — LM Studio local server (OpenAI-compatible)
    """
    if LLM_PROVIDER == "gemini":
        from agno.models.google import Gemini
        return Gemini(id=GEMINI_MODEL)

    if LLM_PROVIDER == "openai":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=OPENAI_MODEL, api_key=OPENAI_API_KEY)

    if LLM_PROVIDER == "anthropic":
        from agno.models.anthropic import Claude
        return Claude(id=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY)

    if LLM_PROVIDER == "lmstudio":
        # LM Studio exposes an OpenAI-compatible API — no key required
        from agno.models.openai import OpenAIChat
        return OpenAIChat(
            id=LMSTUDIO_MODEL,
            api_key="lm-studio",          # placeholder — LM Studio ignores this
            base_url=LMSTUDIO_HOST,
        )

    # Default: Ollama
    from agno.models.ollama import Ollama
    return Ollama(
        id=OLLAMA_MODEL,
        host=OLLAMA_HOST,
        options={"num_ctx": OLLAMA_NUM_CTX, "num_predict": OLLAMA_NUM_PREDICT},
    )

#!/usr/bin/env python3
"""
Personal Health Assistant — Entry Point

Initializes the knowledge base and starts the Telegram bot + Gradio Web UI.

Usage — set LLM_PROVIDER in .env, then:

    Ollama (local, free):
        ollama pull qwen2.5:32b   # first time only
        python main.py
        
    LM Studio (local, free):
        # Start LM Studio → Local Server → Start Server
        # .env: LLM_PROVIDER=lmstudio  LMSTUDIO_MODEL=<model-id>
        python main.py

    Gemini (Google):
        # .env: LLM_PROVIDER=gemini  GOOGLE_API_KEY=AIza...
        python main.py

    OpenAI:
        # .env: LLM_PROVIDER=openai  OPENAI_API_KEY=sk-...
        python main.py

    Anthropic (Claude):
        # .env: LLM_PROVIDER=anthropic  ANTHROPIC_API_KEY=sk-ant-...
        python main.py
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import gradio as gr
import httpx

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    LLM_PROVIDER,
    LMSTUDIO_HOST,
    LMSTUDIO_MODEL,
    LOG_LEVEL,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from tools.credential_store import get_telegram_token
from knowledge import get_knowledge_base
from knowledge.seed_data import seed_all
from interfaces.telegram_bot import create_telegram_app
from interfaces.gradio.app import demo as gradio_demo, _CSS as gradio_css

# ── Logging constants ───────────────────────────────────
_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "health-assistant.log"
_LOG_FORMAT = "%(asctime)s │ %(name)-24s │ %(levelname)-7s │ %(message)s"
_LOG_DATE_FORMAT = "%H:%M:%S"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3
_NOISY_LOGGERS = ("httpx", "chromadb", "telegram")

logger = logging.getLogger("health-assistant")


# ── Logging setup ───────────────────────────────────────

def _configure_logging() -> None:
    _LOG_DIR.mkdir(exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    # force=True equivalent: clear any handlers already added by imported libs
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("──────────── new run ────────────")


# ── Config validation ───────────────────────────────────

def _validate_config() -> None:
    errors = _validate_telegram()
    validators = {
        "gemini": _validate_gemini,
        "openai": _validate_openai,
        "anthropic": _validate_anthropic,
        "lmstudio": _validate_lmstudio,
    }
    errors += validators.get(LLM_PROVIDER, _validate_ollama)()

    if errors:
        logger.error("═══ Configuration errors ═══")
        for error in errors:
            logger.error("  ✗ %s", error)
        sys.exit(1)

def _validate_telegram() -> list[str]:
    if not get_telegram_token():
        return [
            "Token do Telegram não configurado.\n"
            "  Execute: python scripts/setup_telegram.py"
        ]
    return []


def _validate_gemini() -> list[str]:
    if not GOOGLE_API_KEY:
        return ["GOOGLE_API_KEY not set in .env (required for LLM_PROVIDER=gemini)"]
    logger.info("✅ Gemini API configured with model: %s", GEMINI_MODEL)
    return []


def _validate_openai() -> list[str]:
    if not OPENAI_API_KEY:
        return ["OPENAI_API_KEY not set in .env (required for LLM_PROVIDER=openai)"]
    logger.info("✅ OpenAI API configured with model: %s", OPENAI_MODEL)
    return []


def _validate_anthropic() -> list[str]:
    if not ANTHROPIC_API_KEY:
        return ["ANTHROPIC_API_KEY not set in .env (required for LLM_PROVIDER=anthropic)"]
    logger.info("✅ Anthropic API configured with model: %s", ANTHROPIC_MODEL)
    return []


def _validate_lmstudio() -> list[str]:
    try:
        response = httpx.get(f"{LMSTUDIO_HOST}/models", timeout=5)
        response.raise_for_status()
        logger.info("✅ LM Studio running at %s with model: %s", LMSTUDIO_HOST, LMSTUDIO_MODEL)
        return []
    except httpx.ConnectError:
        return [
            f"Cannot connect to LM Studio at {LMSTUDIO_HOST}. "
            "Make sure LM Studio is running and the local server is enabled."
        ]
    except httpx.HTTPError as exc:
        return [f"Error checking LM Studio: {exc}"]


def _validate_ollama() -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        response.raise_for_status()
        available_models = [m["name"] for m in response.json().get("models", [])]
        model_base = OLLAMA_MODEL.split(":")[0]

        if not any(model_base in m for m in available_models):
            return [
                f"Model '{OLLAMA_MODEL}' not found in Ollama. "
                f"Run: ollama pull {OLLAMA_MODEL}\n"
                f"  Available models: {', '.join(available_models) or 'none'}"
            ]

        logger.info("✅ Ollama running with model: %s", OLLAMA_MODEL)
        return []

    except httpx.ConnectError:
        return [
            f"Cannot connect to Ollama at {OLLAMA_HOST}. "
            "Make sure Ollama is running: ollama serve"
        ]
    except httpx.HTTPError as exc:
        return [f"Error checking Ollama: {exc}"]


# ── Knowledge base ──────────────────────────────────────

def _init_knowledge_base() -> None:
    kb = get_knowledge_base()
    pref_count = kb.preferences.count()
    nutrition_count = kb.nutrition.count()
    exercise_count = kb.exercises.count()

    logger.info(
        "Knowledge Base: %d preferences, %d nutrition, %d exercises",
        pref_count,
        nutrition_count,
        exercise_count,
    )

    if nutrition_count == 0:
        logger.info("Empty KB — running seed...")
        seed_all()
        logger.info("✅ Seed complete.")
    else:
        logger.info("✅ Knowledge Base already populated.")



def _llm_label() -> str:
    labels = {
        "gemini": f"Gemini API ({GEMINI_MODEL})",
        "openai": f"OpenAI API ({OPENAI_MODEL})",
        "anthropic": f"Anthropic API ({ANTHROPIC_MODEL})",
        "lmstudio": f"LM Studio ({LMSTUDIO_MODEL} @ {LMSTUDIO_HOST})",
    }
    return labels.get(LLM_PROVIDER, f"Ollama ({OLLAMA_MODEL})")


# ── Entry point ─────────────────────────────────────────

def main() -> None:
    _configure_logging()

    logger.info("══════════════════════════════════════════")
    logger.info("  Personal Health Assistant")
    logger.info("  Agno + %s + Telegram", _llm_label())
    logger.info("══════════════════════════════════════════")

    _validate_config()
    _init_knowledge_base()

    gradio_demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        prevent_thread_lock=True,
        theme=gr.themes.Soft(primary_hue="emerald", secondary_hue="teal"),
        css=gradio_css,
    )
    logger.info("✅ Gradio UI available at http://localhost:7860")

    app = create_telegram_app()

    logger.info("══════════════════════════════════════════")
    logger.info("  🚀 Bot running! Send /start in Telegram")
    logger.info("  Ctrl+C to stop")
    logger.info("══════════════════════════════════════════")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()

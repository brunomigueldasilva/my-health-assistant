"""
Telegram Bot Interface — connects Telegram to the Agno agent team.

Handles commands, messages, and routes everything to the coordinator.
"""

import asyncio
import logging
import uuid

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from agents.coordinator import create_health_team
from tools.profile_tools import (
    update_user_profile,
    add_food_preference,
    add_health_goal,
    get_user_profile,
    get_weight_history,
)

logger = logging.getLogger(__name__)

# ── Global state ───────────────────────────────────────
_team = None
# Maps user_id → current session_id (persisted in Agno SqliteDb)
_user_sessions: dict[str, str] = {}


def get_team():
    """Lazy init of the agent team."""
    global _team
    if _team is None:
        logger.info("Creating agent team...")
        _team = create_health_team()
        logger.info("✅ Team created successfully.")
    return _team


def _get_session_id(uid: str) -> str:
    """Return the active session_id for this user, creating one if needed."""
    if uid not in _user_sessions:
        _user_sessions[uid] = f"user_{uid}"
    return _user_sessions[uid]


def _reset_session(uid: str) -> str:
    """Generate a new session_id, effectively clearing the conversation context."""
    _user_sessions[uid] = f"user_{uid}_{uuid.uuid4().hex[:8]}"
    return _user_sessions[uid]


def _uid(update: Update) -> str:
    return str(update.effective_user.id)


def _uname(update: Update) -> str:
    u = update.effective_user
    return u.first_name or u.username or "Utilizador"


# ══════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = _uid(update), _uname(update)
    update_user_profile(uid, name=name)

    await update.message.reply_text(
        f"Olá {name}! 👋\n\n"
        f"Sou o teu assistente pessoal de saúde e bem-estar. "
        f"Tenho uma equipa de especialistas:\n\n"
        f"🥗 *Nutricionista* — planos alimentares, calorias, macros\n"
        f"🏋️ *Personal Trainer* — treinos, exercícios, rotinas\n"
        f"👨‍🍳 *Chef* — receitas saudáveis personalizadas\n\n"
        f"Basta enviares uma mensagem!\n\n"
        f"*Comandos:*\n"
        f"/perfil — Ver perfil\n"
        f"/objectivo <texto> — Definir objetivo\n"
        f"/gosto <alimento> — Alimento que gostas\n"
        f"/nao\\_gosto <alimento> — Alimento que não gostas\n"
        f"/peso <kg> — Registar peso\n"
        f"/historico — Histórico de peso\n"
        f"/reset — Limpar conversa",
        parse_mode="Markdown",
    )


async def cmd_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_user_profile(_uid(update)))


async def cmd_objectivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "❓ Exemplo: `/objectivo Perder 5kg em 3 meses`\n_Define o teu objetivo de saúde._",
            parse_mode="Markdown",
        )
        return
    result = add_health_goal(_uid(update), text)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_gosto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food = " ".join(context.args) if context.args else ""
    if not food:
        await update.message.reply_text(
            "❓ Exemplo: `/gosto salmão`", parse_mode="Markdown"
        )
        return
    result = add_food_preference(_uid(update), food, likes=True)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_nao_gosto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food = " ".join(context.args) if context.args else ""
    if not food:
        await update.message.reply_text(
            "❓ Exemplo: `/nao_gosto beterraba`", parse_mode="Markdown"
        )
        return
    result = add_food_preference(_uid(update), food, likes=False)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_peso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❓ Exemplo: `/peso 78.5`", parse_mode="Markdown"
        )
        return
    try:
        weight = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Peso inválido. Usa um número (ex: 78.5)")
        return

    update_user_profile(_uid(update), weight_kg=weight)
    await update.message.reply_text(
        f"⚖️ Peso registado: *{weight} kg*\nUsa /historico para ver evolução.",
        parse_mode="Markdown",
    )


async def cmd_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_weight_history(_uid(update)))


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_session(_uid(update))
    await update.message.reply_text("🔄 Conversa reiniciada.")


# ══════════════════════════════════════════════════════
# MESSAGE HANDLER — routes to the agent team
# ══════════════════════════════════════════════════════


def _infer_specialist_from_tracker(tracker) -> str:
    """Returns the inferred specialist name for log output."""
    called = {tc.name for tc in tracker._tool_calls}
    if called & {"search_exercises", "search_workout_plans", "estimate_calories_burned"}:
        return "Personal Trainer"
    if "calculate_daily_calories" in called:
        return "Nutricionista"
    if called & {"search_food_nutrition", "search_user_food_preferences", "calculate_meal_macros"}:
        return "Chef/Nutricionista"
    if called:
        return "Coordenador (directo)"
    return "(sem ferramentas)"


def _sanitize_response(text: str) -> str:
    """
    Detects error patterns that Agno may embed directly in the response text
    (e.g. when it catches an API error internally and doesn't raise).
    Returns a user-friendly message instead of the raw technical content.
    """
    low = text.lower()
    if any(k in low for k in ("429", "resource_exhausted", "quota", "rate limit", "too many requests")):
        return "⏳ O serviço de IA atingiu o limite de pedidos. Aguarda uns segundos e tenta novamente."
    if any(k in low for k in ("clientresponse", "bound method", "aiohttp", "httpserver")):
        return "❌ Ocorreu um erro inesperado. Tenta novamente ou usa /reset."
    if any(k in low for k in ("timeout", "timed out", "deadline exceeded")):
        return "⏱️ A resposta demorou demasiado. Tenta novamente."
    if any(k in low for k in ("connection error", "network error", "unreachable")):
        return "🌐 Erro de ligação. Verifica a tua rede e tenta novamente."
    return text


def _user_error_message(exc: Exception) -> str:
    """
    Translates an internal exception into a short, user-friendly message.
    Never exposes stack traces or internal API details to the user.
    """
    err = str(exc).lower()
    if any(k in err for k in ("429", "resource_exhausted", "quota", "rate limit", "too many requests")):
        return (
            "⏳ O serviço de IA atingiu o limite de pedidos. "
            "Aguarda uns segundos e tenta novamente."
        )
    if any(k in err for k in ("timeout", "timed out", "deadline")):
        return "⏱️ A resposta demorou demasiado. Tenta novamente."
    if any(k in err for k in ("connection", "network", "unreachable", "socket")):
        return "🌐 Erro de ligação. Verifica a tua rede e tenta novamente."
    # Fallback genérico — sem detalhes técnicos
    return "❌ Ocorreu um erro inesperado. Tenta novamente ou usa /reset."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler for text messages. Routes to Agno team."""
    from xai import get_tracker
    uid = _uid(update)
    name = _uname(update)
    msg = update.message.text

    if not msg:
        return

    tracker = get_tracker()
    tracker.reset(msg)

    logger.info("[%s] %s: %s", uid, name, msg[:80])

    # Include user identity so agents can call tools with the correct user_id
    enriched = f"[User: {name}, ID: {uid}]\n{msg}"

    try:
        team = get_team()
        session_id = _get_session_id(uid)

        # Keep typing indicator alive while the LLM runs (it expires every 5s)
        async def _keep_typing():
            while True:
                await update.message.chat.send_action("typing")
                await asyncio.sleep(4)

        typing_task = asyncio.create_task(_keep_typing())

        try:
            response = await team.arun(enriched, session_id=session_id, user_id=uid)
        finally:
            typing_task.cancel()

        response_text = _extract_text(response)

        if not response_text:
            response_text = "Desculpa, não consegui processar. Tenta reformular. 🤔"
        else:
            response_text = _sanitize_response(response_text)

        # ── XAI summary ──────────────────────────────────
        specialist = _infer_specialist_from_tracker(tracker)
        tools_called = [tc.name for tc in tracker._tool_calls]
        rag_hits = [(rq.collection, rq.query, rq.hits) for rq in tracker._rag_queries]
        logger.info("[XAI] specialist=%-25s tools=%s", specialist, tools_called)
        if rag_hits:
            for col, q, hits in rag_hits:
                logger.info("[XAI] rag_summary  collection=%-20s hits=%-3d query=%r", col, hits, q[:40])

        await _send_long(update, response_text)

    except Exception as e:
        logger.error("Error processing message: %s", e, exc_info=True)
        await update.message.reply_text(_user_error_message(e))


def _extract_text(response) -> str:
    """Extract text from Agno Team/Run response."""
    if response is None:
        return ""
    if hasattr(response, "content"):
        if isinstance(response.content, str):
            return response.content
        if isinstance(response.content, list):
            parts = []
            for item in response.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                elif isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
            return "\n".join(parts)
    if hasattr(response, "messages"):
        for msg in reversed(response.messages):
            if hasattr(msg, "content") and msg.role == "assistant":
                return msg.content
    return str(response)


async def _send_long(update: Update, text: str, max_len: int = 4000):
    """Send long messages split for Telegram's 4096 char limit."""
    if len(text) <= max_len:
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(text)
        return

    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = text.rfind(". ", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[: cut + 1])
        text = text[cut + 1 :]

    for part in parts:
        try:
            await update.message.reply_text(part.strip(), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(part.strip())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Bot error: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ Erro inesperado. Tenta novamente.")


def create_telegram_app() -> Application:
    """Create and configure the Telegram Application with all handlers."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("perfil", cmd_perfil))
    app.add_handler(CommandHandler("objectivo", cmd_objectivo))
    app.add_handler(CommandHandler("gosto", cmd_gosto))
    app.add_handler(CommandHandler("nao_gosto", cmd_nao_gosto))
    app.add_handler(CommandHandler("peso", cmd_peso))
    app.add_handler(CommandHandler("historico", cmd_historico))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("✅ Telegram app configured with %d handlers.", len(app.handlers[0]))
    return app

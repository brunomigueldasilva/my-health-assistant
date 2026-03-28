"""
Telegram Bot Interface — connects Telegram to the Agno agent team.

Handles commands, messages, and routes everything to the coordinator.
Includes a guided onboarding ConversationHandler for new users.
"""

import asyncio
import logging
import sqlite3
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, SQLITE_DB
from agents.coordinator import create_health_team
from tools.profile_tools import (
    update_user_profile,
    add_food_preference,
    add_health_goal,
    add_allergy,
    get_user_profile,
    get_weight_history,
)

logger = logging.getLogger(__name__)

# ── Global state ───────────────────────────────────────
_team = None
_user_sessions: dict[str, str] = {}

# ── Onboarding conversation states ────────────────────
(WELCOME, GENDER, AGE, HEIGHT, WEIGHT, ACTIVITY, GOAL, ALLERGIES) = range(8)

# ── Onboarding display labels ─────────────────────────
_ACTIVITY_OPTIONS = [
    ("sedentary",  "🛋️ Sedentário"),
    ("light",      "🚶 Ligeiro"),
    ("moderate",   "🏃 Moderado"),
    ("active",     "💪 Activo"),
    ("very_active","🔥 Muito Activo"),
]
_ACTIVITY_LABEL = {k: v for k, v in _ACTIVITY_OPTIONS}

_GOAL_OPTIONS = [
    ("lose_weight",    "⬇️ Perder peso"),
    ("gain_muscle",    "💪 Ganhar massa muscular"),
    ("maintain",       "⚖️ Manter peso"),
    ("improve_health", "❤️ Melhorar saúde geral"),
]
_GOAL_LABEL = {k: v for k, v in _GOAL_OPTIONS}

_ALLERGY_OPTIONS = ["Glúten", "Lactose", "Frutos secos", "Marisco", "Ovos", "Amendoins"]

_AGE_OPTIONS = ["18-25", "26-35", "36-45", "46-55", "56+"]


# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def get_team():
    """Lazy init of the agent team."""
    global _team
    if _team is None:
        logger.info("Creating agent team...")
        _team = create_health_team()
        logger.info("✅ Team created successfully.")
    return _team


def _get_session_id(uid: str) -> str:
    if uid not in _user_sessions:
        _user_sessions[uid] = f"user_{uid}"
    return _user_sessions[uid]


def _reset_session(uid: str) -> str:
    _user_sessions[uid] = f"user_{uid}_{uuid.uuid4().hex[:8]}"
    return _user_sessions[uid]


def _uid(update: Update) -> str:
    return str(update.effective_user.id)


def _uname(update: Update) -> str:
    u = update.effective_user
    return u.first_name or u.username or "Utilizador"


def _is_profile_complete(uid: str) -> bool:
    """Returns True if the user has filled in the core profile fields."""
    conn = sqlite3.connect(str(SQLITE_DB))
    row = conn.execute(
        "SELECT age, gender, weight_kg FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()
    return bool(row and row[0] and row[1] and row[2])


def _allergy_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Build the toggle-style allergy selection keyboard."""
    rows = []
    for i in range(0, len(_ALLERGY_OPTIONS), 2):
        row = []
        for opt in _ALLERGY_OPTIONS[i:i + 2]:
            label = f"✅ {opt}" if opt in selected else opt
            row.append(InlineKeyboardButton(label, callback_data=f"ob_allergy:{opt}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton(
            "✅ Nenhuma" if "nenhuma" in selected else "Nenhuma alergia",
            callback_data="ob_allergy:nenhuma",
        )
    ])
    rows.append([InlineKeyboardButton("➡️ Continuar", callback_data="ob_allergy_done")])
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════
# ONBOARDING — STEP HANDLERS
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: show welcome for existing users, start onboarding for new ones."""
    uid, name = _uid(update), _uname(update)
    update_user_profile(uid, name=name)

    if _is_profile_complete(uid):
        # Returning user — skip onboarding
        await update.message.reply_text(
            f"Bem-vindo de volta, *{name}*! 👋\n\n"
            f"A tua equipa de saúde está pronta:\n"
            f"🥗 *Nutricionista* · 🏋️ *Trainer* · 👨‍🍳 *Chef*\n\n"
            f"Basta enviares uma mensagem ou usar:\n"
            f"/perfil — Ver perfil · /peso — Registar peso\n"
            f"/objectivo — Definir objetivo · /reset — Nova conversa",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🚀 Criar o meu perfil", callback_data="ob_start")],
        [InlineKeyboardButton("⏭️ Saltar por agora", callback_data="ob_skip")],
    ]
    await update.message.reply_text(
        f"Olá *{name}*! 👋\n\n"
        f"Sou o teu assistente pessoal de saúde, com uma equipa de especialistas:\n"
        f"🥗 *Nutricionista* · 🏋️ *Personal Trainer* · 👨‍🍳 *Chef*\n\n"
        f"Para receber conselhos personalizados, preciso de conhecer-te melhor.\n"
        f"São apenas *4 passos rápidos* — menos de 1 minuto! ⚡",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return WELCOME


async def onb_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Criar perfil' or 'Saltar' from welcome screen."""
    query = update.callback_query
    await query.answer()

    if query.data == "ob_skip":
        await query.edit_message_text(
            "Tudo bem! Podes começar a conversar quando quiseres. 💬\n\n"
            "Usa /start a qualquer altura para configurar o teu perfil.",
        )
        return ConversationHandler.END

    # ob_start → ask gender
    context.user_data["onb"] = {}
    keyboard = [[
        InlineKeyboardButton("👨 Masculino", callback_data="ob_gender:M"),
        InlineKeyboardButton("👩 Feminino",  callback_data="ob_gender:F"),
    ]]
    await query.edit_message_text(
        "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
        "Qual é o teu género?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return GENDER


async def onb_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    gender = query.data.split(":")[1]  # M or F
    context.user_data["onb"]["gender"] = "male" if gender == "M" else "female"

    # Build age range buttons (2 per row)
    age_buttons = [
        InlineKeyboardButton(age, callback_data=f"ob_age:{age}")
        for age in _AGE_OPTIONS
    ]
    rows = [age_buttons[:3], age_buttons[3:]]
    await query.edit_message_text(
        "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
        "Qual é a tua faixa etária?",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )
    return AGE


async def onb_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    age_range = query.data.split(":")[1]
    # Store midpoint as integer age
    midpoints = {"18-25": 22, "26-35": 30, "36-45": 40, "46-55": 50, "56+": 60}
    context.user_data["onb"]["age"] = midpoints.get(age_range, 35)
    context.user_data["onb"]["age_label"] = age_range

    keyboard = [[InlineKeyboardButton("⏭️ Saltar", callback_data="ob_height_skip")]]
    await query.edit_message_text(
        "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
        "Qual é a tua altura? _(em cm, ex: 175)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return HEIGHT


async def onb_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        height = float(text)
        if not (100 <= height <= 250):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Altura inválida. Insere um valor entre 100 e 250 cm (ex: *175*).",
            parse_mode="Markdown",
        )
        return HEIGHT

    context.user_data["onb"]["height_cm"] = height
    await _ask_weight(update.message)
    return WEIGHT


async def onb_height_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
        "Qual é o teu peso actual? _(em kg, ex: 78.5)_",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭️ Saltar", callback_data="ob_weight_skip")
        ]]),
        parse_mode="Markdown",
    )
    return WEIGHT


async def _ask_weight(message):
    keyboard = [[InlineKeyboardButton("⏭️ Saltar", callback_data="ob_weight_skip")]]
    await message.reply_text(
        "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
        "Qual é o teu peso actual? _(em kg, ex: 78.5)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def onb_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        weight = float(text)
        if not (30 <= weight <= 300):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Peso inválido. Insere um valor entre 30 e 300 kg (ex: *78.5*).",
            parse_mode="Markdown",
        )
        return WEIGHT

    context.user_data["onb"]["weight_kg"] = weight
    await _ask_activity(update.message)
    return ACTIVITY


async def onb_weight_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = [
        [InlineKeyboardButton(label, callback_data=f"ob_activity:{key}")]
        for key, label in _ACTIVITY_OPTIONS
    ]
    await query.edit_message_text(
        "*Passo 2 de 4 — Estilo de vida* 🏃\n\n"
        "Qual é o teu nível de actividade física habitual?",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )
    return ACTIVITY


async def _ask_activity(message):
    rows = [
        [InlineKeyboardButton(label, callback_data=f"ob_activity:{key}")]
        for key, label in _ACTIVITY_OPTIONS
    ]
    await message.reply_text(
        "*Passo 2 de 4 — Estilo de vida* 🏃\n\n"
        "Qual é o teu nível de actividade física habitual?",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )


async def onb_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    activity = query.data.split(":")[1]
    context.user_data["onb"]["activity_level"] = activity

    rows = []
    for i in range(0, len(_GOAL_OPTIONS), 2):
        row = [
            InlineKeyboardButton(label, callback_data=f"ob_goal:{key}")
            for key, label in _GOAL_OPTIONS[i:i + 2]
        ]
        rows.append(row)

    await query.edit_message_text(
        "*Passo 3 de 4 — Objectivo* 🎯\n\n"
        "Qual é o teu principal objectivo de saúde?",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )
    return GOAL


async def onb_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    goal_key = query.data.split(":")[1]
    goal_label = _GOAL_LABEL.get(goal_key, goal_key)
    context.user_data["onb"]["goal"] = goal_label

    context.user_data["onb"]["allergies"] = set()
    await query.edit_message_text(
        "*Passo 4 de 4 — Alergias e intolerâncias* ⚠️\n\n"
        "Tens alguma alergia ou intolerância alimentar?\n"
        "_(Selecciona todas as que se aplicam)_",
        reply_markup=_allergy_keyboard(set()),
        parse_mode="Markdown",
    )
    return ALLERGIES


async def onb_allergy_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle an allergy on/off or select 'none'."""
    query = update.callback_query
    await query.answer()

    item = query.data.split(":")[1]
    selected: set = context.user_data["onb"].get("allergies", set())

    if item == "nenhuma":
        selected = {"nenhuma"} if "nenhuma" not in selected else set()
    else:
        selected.discard("nenhuma")
        if item in selected:
            selected.discard(item)
        else:
            selected.add(item)

    context.user_data["onb"]["allergies"] = selected

    await query.edit_message_text(
        "*Passo 4 de 4 — Alergias e intolerâncias* ⚠️\n\n"
        "Tens alguma alergia ou intolerância alimentar?\n"
        "_(Selecciona todas as que se aplicam)_",
        reply_markup=_allergy_keyboard(selected),
        parse_mode="Markdown",
    )
    return ALLERGIES


async def onb_allergy_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save everything and finish onboarding."""
    query = update.callback_query
    await query.answer()

    uid = _uid(update)
    data = context.user_data.get("onb", {})

    # Save profile to DB
    update_user_profile(
        uid,
        age=data.get("age"),
        gender=data.get("gender"),
        height_cm=data.get("height_cm"),
        weight_kg=data.get("weight_kg"),
        activity_level=data.get("activity_level"),
        goal=data.get("goal"),
    )

    # Save allergies to ChromaDB
    allergies = data.get("allergies", set())
    allergy_list = [a for a in allergies if a != "nenhuma"]
    for allergy in allergy_list:
        add_allergy(uid, allergy)

    # Also register goal in ChromaDB
    if data.get("goal"):
        add_health_goal(uid, data["goal"])

    # Build summary
    gender_icon = "👨" if data.get("gender") == "male" else "👩"
    activity_label = _ACTIVITY_LABEL.get(data.get("activity_level", ""), "—")
    height_str = f"{data['height_cm']:.0f} cm" if data.get("height_cm") else "—"
    weight_str = f"{data['weight_kg']:.1f} kg" if data.get("weight_kg") else "—"
    allergy_str = ", ".join(allergy_list) if allergy_list else "Nenhuma"

    summary = (
        f"✅ *Perfil criado com sucesso!*\n\n"
        f"{gender_icon} Género: {'Masculino' if data.get('gender') == 'male' else 'Feminino'}\n"
        f"🎂 Idade: {data.get('age_label', '—')}\n"
        f"📏 Altura: {height_str}\n"
        f"⚖️ Peso: {weight_str}\n"
        f"🏃 Actividade: {activity_label}\n"
        f"🎯 Objectivo: {data.get('goal', '—')}\n"
        f"⚠️ Alergias: {allergy_str}\n\n"
        f"A tua equipa já conhece o teu perfil! Começa a conversar 💬\n"
        f"_Podes ver o teu perfil completo com_ /perfil"
    )

    await query.edit_message_text(summary, parse_mode="Markdown")
    context.user_data.pop("onb", None)
    return ConversationHandler.END


async def onb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel onboarding at any step."""
    context.user_data.pop("onb", None)
    await update.message.reply_text(
        "Onboarding cancelado. Podes reiniciá-lo a qualquer altura com /start.",
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
# REGULAR COMMAND HANDLERS
# ══════════════════════════════════════════════════════

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
    err = str(exc).lower()
    if any(k in err for k in ("429", "resource_exhausted", "quota", "rate limit", "too many requests")):
        return "⏳ O serviço de IA atingiu o limite de pedidos. Aguarda uns segundos e tenta novamente."
    if any(k in err for k in ("timeout", "timed out", "deadline")):
        return "⏱️ A resposta demorou demasiado. Tenta novamente."
    if any(k in err for k in ("connection", "network", "unreachable", "socket")):
        return "🌐 Erro de ligação. Verifica a tua rede e tenta novamente."
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

    enriched = f"[User: {name}, ID: {uid}]\n{msg}"

    try:
        team = get_team()
        session_id = _get_session_id(uid)

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


# ══════════════════════════════════════════════════════
# APP FACTORY
# ══════════════════════════════════════════════════════

def create_telegram_app() -> Application:
    """Create and configure the Telegram Application with all handlers."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Onboarding ConversationHandler ────────────────
    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            WELCOME: [
                CallbackQueryHandler(onb_welcome, pattern="^ob_(start|skip)$"),
            ],
            GENDER: [
                CallbackQueryHandler(onb_gender, pattern="^ob_gender:"),
            ],
            AGE: [
                CallbackQueryHandler(onb_age, pattern="^ob_age:"),
            ],
            HEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onb_height),
                CallbackQueryHandler(onb_height_skip, pattern="^ob_height_skip$"),
            ],
            WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onb_weight),
                CallbackQueryHandler(onb_weight_skip, pattern="^ob_weight_skip$"),
            ],
            ACTIVITY: [
                CallbackQueryHandler(onb_activity, pattern="^ob_activity:"),
            ],
            GOAL: [
                CallbackQueryHandler(onb_goal, pattern="^ob_goal:"),
            ],
            ALLERGIES: [
                CallbackQueryHandler(onb_allergy_toggle, pattern="^ob_allergy:"),
                CallbackQueryHandler(onb_allergy_done, pattern="^ob_allergy_done$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", onb_cancel)],
        allow_reentry=True,
    )

    app.add_handler(onboarding)

    # ── Regular command handlers ───────────────────────
    app.add_handler(CommandHandler("perfil",    cmd_perfil))
    app.add_handler(CommandHandler("objectivo", cmd_objectivo))
    app.add_handler(CommandHandler("gosto",     cmd_gosto))
    app.add_handler(CommandHandler("nao_gosto", cmd_nao_gosto))
    app.add_handler(CommandHandler("peso",      cmd_peso))
    app.add_handler(CommandHandler("historico", cmd_historico))
    app.add_handler(CommandHandler("reset",     cmd_reset))

    # ── Free-text message handler ──────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    logger.info("✅ Telegram app configured with onboarding flow.")
    return app

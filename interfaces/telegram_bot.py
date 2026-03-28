"""
Telegram Bot Interface — connects Telegram to the Agno agent team.

Handles commands, messages, and routes everything to the coordinator.
Includes a guided onboarding flow for new users via inline keyboards.
State is tracked in context.user_data to avoid ConversationHandler
state-persistence pitfalls.
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

# ── Onboarding step keys (stored in context.user_data) ─
_ONB_STEP   = "onb_step"   # current step name
_ONB_DATA   = "onb_data"   # collected values dict

# Step names
_STEP_WELCOME  = "welcome"
_STEP_GENDER   = "gender"
_STEP_AGE      = "age"
_STEP_HEIGHT   = "height"
_STEP_WEIGHT   = "weight"
_STEP_ACTIVITY = "activity"
_STEP_GOAL     = "goal"
_STEP_ALLERGIES = "allergies"

# ── Onboarding option labels ───────────────────────────
_ACTIVITY_OPTIONS = [
    ("sedentary",   "🛋️ Sedentário"),
    ("light",       "🚶 Ligeiro"),
    ("moderate",    "🏃 Moderado"),
    ("active",      "💪 Activo"),
    ("very_active", "🔥 Muito Activo"),
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

_AGE_MIDPOINTS = {"18-25": 22, "26-35": 30, "36-45": 40, "46-55": 50, "56+": 60}


# ══════════════════════════════════════════════════════
# CORE HELPERS
# ══════════════════════════════════════════════════════

def get_team():
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
    """True if core profile fields (age, gender, weight) are filled."""
    try:
        conn = sqlite3.connect(str(SQLITE_DB))
        row = conn.execute(
            "SELECT age, gender, weight_kg FROM user_profiles WHERE user_id = ?",
            (uid,),
        ).fetchone()
        conn.close()
        return bool(row and row[0] and row[1] and row[2])
    except Exception:
        return False


def _onb_step(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get(_ONB_STEP)


def _onb_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    if _ONB_DATA not in context.user_data:
        context.user_data[_ONB_DATA] = {}
    return context.user_data[_ONB_DATA]


def _onb_clear(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(_ONB_STEP, None)
    context.user_data.pop(_ONB_DATA, None)


# ══════════════════════════════════════════════════════
# ONBOARDING — KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════

def _gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👨 Masculino", callback_data="ob_gender:M"),
        InlineKeyboardButton("👩 Feminino",  callback_data="ob_gender:F"),
    ]])


def _age_keyboard() -> InlineKeyboardMarkup:
    ages = list(_AGE_MIDPOINTS.keys())
    rows = [
        [InlineKeyboardButton(a, callback_data=f"ob_age:{a}") for a in ages[:3]],
        [InlineKeyboardButton(a, callback_data=f"ob_age:{a}") for a in ages[3:]],
    ]
    return InlineKeyboardMarkup(rows)


def _skip_keyboard(cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭️ Saltar", callback_data=cb),
    ]])


def _activity_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"ob_activity:{key}")]
        for key, label in _ACTIVITY_OPTIONS
    ]
    return InlineKeyboardMarkup(rows)


def _goal_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(_GOAL_OPTIONS), 2):
        rows.append([
            InlineKeyboardButton(label, callback_data=f"ob_goal:{key}")
            for key, label in _GOAL_OPTIONS[i:i + 2]
        ])
    return InlineKeyboardMarkup(rows)


def _allergy_keyboard(selected: set) -> InlineKeyboardMarkup:
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
# ONBOARDING — ENTRY POINT  (/start)
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = _uid(update), _uname(update)

    try:
        update_user_profile(uid, name=name)
    except Exception as exc:
        logger.warning("cmd_start: could not upsert profile for %s: %s", uid, exc)

    if _is_profile_complete(uid):
        _onb_clear(context)
        await update.message.reply_text(
            f"Bem-vindo de volta, *{name}*! 👋\n\n"
            f"A tua equipa de saúde está pronta:\n"
            f"🥗 *Nutricionista* · 🏋️ *Trainer* · 👨‍🍳 *Chef*\n\n"
            f"Basta enviares uma mensagem ou usar:\n"
            f"/perfil — Ver perfil · /peso — Registar peso\n"
            f"/objectivo — Definir objetivo · /reset — Nova conversa",
            parse_mode="Markdown",
        )
        return

    # New / incomplete profile → start onboarding
    context.user_data[_ONB_STEP] = _STEP_WELCOME
    context.user_data[_ONB_DATA] = {}

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Criar o meu perfil", callback_data="ob_start")],
        [InlineKeyboardButton("⏭️ Saltar por agora",   callback_data="ob_skip")],
    ])
    await update.message.reply_text(
        f"Olá *{name}*! 👋\n\n"
        f"Sou o teu assistente pessoal de saúde, com uma equipa de especialistas:\n"
        f"🥗 *Nutricionista* · 🏋️ *Personal Trainer* · 👨‍🍳 *Chef*\n\n"
        f"Para receber conselhos personalizados, preciso de conhecer-te melhor.\n"
        f"São apenas *4 passos rápidos* — menos de 1 minuto! ⚡",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════
# ONBOARDING — CALLBACK DISPATCHER
# ══════════════════════════════════════════════════════

async def handle_onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single handler for all ob_* callback queries — dispatches by step + data."""
    query = update.callback_query
    await query.answer()

    data = query.data
    step = _onb_step(context)

    logger.debug("onboarding callback: step=%s data=%s", step, data)

    # ── ob_skip: abandon onboarding at any point ──────
    if data == "ob_skip":
        _onb_clear(context)
        await query.edit_message_text(
            "Tudo bem! Podes começar a conversar quando quiseres. 💬\n"
            "Usa /start a qualquer altura para configurar o teu perfil.",
        )
        return

    # ── ob_start: welcome → gender ────────────────────
    if data == "ob_start":
        context.user_data[_ONB_STEP] = _STEP_GENDER
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\nQual é o teu género?",
            reply_markup=_gender_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── ob_gender:* ───────────────────────────────────
    if data.startswith("ob_gender:") and step == _STEP_GENDER:
        gender = "male" if data.endswith(":M") else "female"
        _onb_data(context)["gender"] = gender
        context.user_data[_ONB_STEP] = _STEP_AGE
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\nQual é a tua faixa etária?",
            reply_markup=_age_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── ob_age:* ──────────────────────────────────────
    if data.startswith("ob_age:") and step == _STEP_AGE:
        age_range = data.split(":", 1)[1]
        _onb_data(context)["age"] = _AGE_MIDPOINTS.get(age_range, 35)
        _onb_data(context)["age_label"] = age_range
        context.user_data[_ONB_STEP] = _STEP_HEIGHT
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é a tua altura? _(em cm, ex: 175)_",
            reply_markup=_skip_keyboard("ob_height_skip"),
            parse_mode="Markdown",
        )
        return

    # ── ob_height_skip ────────────────────────────────
    if data == "ob_height_skip":
        context.user_data[_ONB_STEP] = _STEP_WEIGHT
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é o teu peso actual? _(em kg, ex: 78.5)_",
            reply_markup=_skip_keyboard("ob_weight_skip"),
            parse_mode="Markdown",
        )
        return

    # ── ob_weight_skip ────────────────────────────────
    if data == "ob_weight_skip":
        context.user_data[_ONB_STEP] = _STEP_ACTIVITY
        await query.edit_message_text(
            "*Passo 2 de 4 — Estilo de vida* 🏃\n\n"
            "Qual é o teu nível de actividade física habitual?",
            reply_markup=_activity_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── ob_activity:* ─────────────────────────────────
    if data.startswith("ob_activity:") and step == _STEP_ACTIVITY:
        activity = data.split(":", 1)[1]
        _onb_data(context)["activity_level"] = activity
        context.user_data[_ONB_STEP] = _STEP_GOAL
        await query.edit_message_text(
            "*Passo 3 de 4 — Objectivo* 🎯\n\n"
            "Qual é o teu principal objectivo de saúde?",
            reply_markup=_goal_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── ob_goal:* ─────────────────────────────────────
    if data.startswith("ob_goal:") and step == _STEP_GOAL:
        goal_key = data.split(":", 1)[1]
        _onb_data(context)["goal"] = _GOAL_LABEL.get(goal_key, goal_key)
        context.user_data[_ONB_STEP] = _STEP_ALLERGIES
        _onb_data(context).setdefault("allergies", set())
        await query.edit_message_text(
            "*Passo 4 de 4 — Alergias e intolerâncias* ⚠️\n\n"
            "Tens alguma alergia ou intolerância alimentar?\n"
            "_(Selecciona todas as que se aplicam)_",
            reply_markup=_allergy_keyboard(set()),
            parse_mode="Markdown",
        )
        return

    # ── ob_allergy:* (toggle) ─────────────────────────
    if data.startswith("ob_allergy:") and step == _STEP_ALLERGIES:
        item = data.split(":", 1)[1]
        selected: set = _onb_data(context).get("allergies", set())
        if item == "nenhuma":
            selected = {"nenhuma"} if "nenhuma" not in selected else set()
        else:
            selected.discard("nenhuma")
            selected.discard(item) if item in selected else selected.add(item)
        _onb_data(context)["allergies"] = selected
        await query.edit_message_text(
            "*Passo 4 de 4 — Alergias e intolerâncias* ⚠️\n\n"
            "Tens alguma alergia ou intolerância alimentar?\n"
            "_(Selecciona todas as que se aplicam)_",
            reply_markup=_allergy_keyboard(selected),
            parse_mode="Markdown",
        )
        return

    # ── ob_allergy_done ───────────────────────────────
    if data == "ob_allergy_done" and step == _STEP_ALLERGIES:
        await _finish_onboarding(query, update, context)
        return

    # Stale or out-of-order callback — silently ignore
    logger.debug("Ignored stale onboarding callback: step=%s data=%s", step, data)


async def _finish_onboarding(query, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save all collected onboarding data and show the summary."""
    uid = _uid(update)
    d = _onb_data(context)

    try:
        update_user_profile(
            uid,
            age=d.get("age"),
            gender=d.get("gender"),
            height_cm=d.get("height_cm"),
            weight_kg=d.get("weight_kg"),
            activity_level=d.get("activity_level"),
            goal=d.get("goal"),
        )
    except Exception as exc:
        logger.error("finish_onboarding: could not save profile for %s: %s", uid, exc)

    allergies = {a for a in d.get("allergies", set()) if a != "nenhuma"}
    for allergy in allergies:
        try:
            add_allergy(uid, allergy)
        except Exception as exc:
            logger.warning("finish_onboarding: could not save allergy %s: %s", allergy, exc)

    if d.get("goal"):
        try:
            add_health_goal(uid, d["goal"])
        except Exception as exc:
            logger.warning("finish_onboarding: could not save goal: %s", exc)

    # Summary
    gender_icon = "👨" if d.get("gender") == "male" else "👩"
    gender_label = "Masculino" if d.get("gender") == "male" else "Feminino"
    height_str = f"{d['height_cm']:.0f} cm" if d.get("height_cm") else "—"
    weight_str = f"{d['weight_kg']:.1f} kg" if d.get("weight_kg") else "—"
    allergy_str = ", ".join(sorted(allergies)) if allergies else "Nenhuma"
    activity_label = _ACTIVITY_LABEL.get(d.get("activity_level", ""), "—")

    summary = (
        f"✅ *Perfil criado com sucesso!*\n\n"
        f"{gender_icon} Género: {gender_label}\n"
        f"🎂 Idade: {d.get('age_label', '—')}\n"
        f"📏 Altura: {height_str}\n"
        f"⚖️ Peso: {weight_str}\n"
        f"🏃 Actividade: {activity_label}\n"
        f"🎯 Objectivo: {d.get('goal', '—')}\n"
        f"⚠️ Alergias: {allergy_str}\n\n"
        f"A tua equipa já conhece o teu perfil! Começa a conversar 💬\n"
        f"_Podes ver o teu perfil completo com_ /perfil"
    )

    _onb_clear(context)
    await query.edit_message_text(summary, parse_mode="Markdown")


# ══════════════════════════════════════════════════════
# ONBOARDING — TEXT INPUT HANDLER (height / weight)
# ══════════════════════════════════════════════════════

async def _handle_onboarding_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle text input for height/weight steps.
    Returns True if the message was consumed by onboarding, False otherwise.
    """
    step = _onb_step(context)

    if step == _STEP_HEIGHT:
        text = update.message.text.strip().replace(",", ".")
        try:
            height = float(text)
            if not (100 <= height <= 250):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Altura inválida. Insere um valor entre 100 e 250 cm _(ex: 175)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True

        _onb_data(context)["height_cm"] = height
        context.user_data[_ONB_STEP] = _STEP_WEIGHT
        await update.message.reply_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é o teu peso actual? _(em kg, ex: 78.5)_",
            reply_markup=_skip_keyboard("ob_weight_skip"),
            parse_mode="Markdown",
        )
        return True

    if step == _STEP_WEIGHT:
        text = update.message.text.strip().replace(",", ".")
        try:
            weight = float(text)
            if not (30 <= weight <= 300):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Peso inválido. Insere um valor entre 30 e 300 kg _(ex: 78.5)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True

        _onb_data(context)["weight_kg"] = weight
        context.user_data[_ONB_STEP] = _STEP_ACTIVITY
        await update.message.reply_text(
            "*Passo 2 de 4 — Estilo de vida* 🏃\n\n"
            "Qual é o teu nível de actividade física habitual?",
            reply_markup=_activity_keyboard(),
            parse_mode="Markdown",
        )
        return True

    return False


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
    """Main handler for text messages. Checks onboarding state first."""
    from xai import get_tracker

    # Let onboarding consume height/weight text input if applicable
    if await _handle_onboarding_text(update, context):
        return

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
        text = text[cut + 1:]

    for part in parts:
        try:
            await update.message.reply_text(part.strip(), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(part.strip())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Bot error: %s", context.error, exc_info=context.error)
    if not isinstance(update, Update):
        return
    msg = "❌ Erro inesperado. Tenta novamente."
    if update.callback_query:
        try:
            await update.callback_query.answer(msg, show_alert=True)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(msg)


# ══════════════════════════════════════════════════════
# APP FACTORY
# ══════════════════════════════════════════════════════

def create_telegram_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Onboarding inline-keyboard handler (highest priority) ──
    app.add_handler(CallbackQueryHandler(handle_onboarding_callback, pattern="^ob_"))

    # ── Command handlers ───────────────────────────────
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("perfil",     cmd_perfil))
    app.add_handler(CommandHandler("objectivo",  cmd_objectivo))
    app.add_handler(CommandHandler("gosto",      cmd_gosto))
    app.add_handler(CommandHandler("nao_gosto",  cmd_nao_gosto))
    app.add_handler(CommandHandler("peso",       cmd_peso))
    app.add_handler(CommandHandler("historico",  cmd_historico))
    app.add_handler(CommandHandler("reset",      cmd_reset))

    # ── Free-text message handler ──────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    logger.info("✅ Telegram app configured.")
    return app

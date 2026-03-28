"""
Telegram Bot Interface — connects Telegram to the Agno agent team.

Onboarding and Preferences menus use inline keyboards with state stored
in context.user_data (no ConversationHandler dependency).
"""

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime

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
from knowledge import get_knowledge_base
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

# ══════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════

# ── Onboarding step keys (stored in context.user_data) ─
_ONB_STEP = "onb_step"
_ONB_DATA = "onb_data"

_STEP_WELCOME     = "welcome"
_STEP_GENDER      = "gender"
_STEP_AGE         = "age"
_STEP_HEIGHT      = "height"
_STEP_WEIGHT      = "weight"
_STEP_ACTIVITY    = "activity"
_STEP_GOAL        = "goal"
_STEP_GOAL_WEIGHT = "goal_weight"
_STEP_ALLERGIES   = "allergies"

_ACTIVITY_OPTIONS = [
    ("sedentary",   "🛋️ Sedentário"),
    ("light",       "🚶 Ligeiro"),
    ("moderate",    "🏃 Moderado"),
    ("active",      "💪 Activo"),
    ("very_active", "🔥 Muito Activo"),
]
_ACTIVITY_LABEL = {k: v for k, v in _ACTIVITY_OPTIONS}

_GOAL_OPTIONS = [
    ("lose_visceral",   "🔥 Perder gordura visceral"),
    ("lose_weight",     "⬇️ Perder peso"),
    ("target_weight",   "🎯 Atingir peso específico"),
    ("gain_muscle",     "💪 Ganhar massa muscular"),
    ("maintain",        "⚖️ Manter peso actual"),
    ("improve_fitness", "🏃 Melhorar condição física"),
    ("improve_health",  "❤️ Melhorar saúde geral"),
    ("better_diet",     "🍽️ Melhores hábitos alimentares"),
]
_GOAL_LABEL = {k: v for k, v in _GOAL_OPTIONS}

_ALLERGY_OPTIONS = ["Glúten", "Lactose", "Frutos secos", "Marisco", "Ovos", "Amendoins"]

# ── Preferences menu ───────────────────────────────────
_PREF_CATEGORIES = [
    ("food_likes",   "👍 Gostos alimentares"),
    ("food_dislikes","👎 Não gostos"),
    ("allergies",    "⚠️ Alergias e intolerâncias"),
    ("restrictions", "🚫 Restrições alimentares"),
    ("goals",        "🎯 Objectivos de saúde"),
]
_PREF_LABEL = {k: v for k, v in _PREF_CATEGORIES}

_PREFS_STATE = "prefs_state"
_PREFS_ITEMS = "prefs_items"
_PREFS_SEL   = "prefs_selected"


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
    try:
        conn = sqlite3.connect(str(SQLITE_DB))
        row = conn.execute(
            "SELECT age, gender, weight_kg FROM user_profiles WHERE user_id = ?", (uid,)
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


def _skip_keyboard(cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭️ Saltar", callback_data=cb),
    ]])


def _activity_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"ob_activity:{key}")]
        for key, label in _ACTIVITY_OPTIONS
    ])


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
# PREFERENCES — DATA HELPERS
# ══════════════════════════════════════════════════════

def _load_prefs_items(uid: str, cat: str) -> list[dict]:
    """Load items for a preference category from ChromaDB."""
    kb = get_knowledge_base()
    try:
        data = kb.preferences.get(
            where={"$and": [{"user_id": uid}, {"category": cat}]}
        )
        if data and data.get("ids"):
            return [
                {"id": data["ids"][i], "text": data["documents"][i]}
                for i in range(len(data["ids"]))
            ]
    except Exception as exc:
        logger.warning("_load_prefs_items uid=%s cat=%s: %s", uid, cat, exc)
    return []


def _delete_prefs_by_ids(ids: list[str]) -> int:
    kb = get_knowledge_base()
    try:
        kb.preferences.delete(ids=ids)
        return len(ids)
    except Exception as exc:
        logger.warning("_delete_prefs_by_ids: %s", exc)
        return 0


def _add_pref_item(uid: str, cat: str, text: str):
    """Add an item to the appropriate preference category."""
    if cat == "food_likes":
        add_food_preference(uid, text, likes=True)
    elif cat == "food_dislikes":
        add_food_preference(uid, text, likes=False)
    elif cat == "allergies":
        add_allergy(uid, text)
    elif cat == "goals":
        add_health_goal(uid, text)
    else:
        kb = get_knowledge_base()
        kb.add_preference(uid, cat, text, {"created": datetime.now().isoformat()})


def _format_pref_items(items: list, cat_label: str) -> str:
    if not items:
        return f"*{cat_label}*\n\n_Nenhum item registado._"
    n = len(items)
    lines = [f"*{cat_label}* ({n} item{'s' if n != 1 else ''})\n"]
    lines += [f"• {item['text']}" for item in items]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# PREFERENCES — KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════

def _prefs_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"prefs_cat:{cat}")]
        for cat, label in _PREF_CATEGORIES
    ]
    return InlineKeyboardMarkup(rows)


def _prefs_view_keyboard(cat: str, has_items: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Adicionar", callback_data=f"prefs_add:{cat}")]]
    if has_items:
        rows.append([InlineKeyboardButton("🗑️ Remover itens", callback_data=f"prefs_remove_mode:{cat}")])
    rows.append([InlineKeyboardButton("◀️ Voltar", callback_data="prefs_back")])
    return InlineKeyboardMarkup(rows)


def _prefs_remove_keyboard(items: list, selected: set, cat: str) -> InlineKeyboardMarkup:
    rows = []
    for i, item in enumerate(items):
        label = f"✅ {item['text'][:38]}" if i in selected else item['text'][:38]
        rows.append([InlineKeyboardButton(label, callback_data=f"prefs_toggle:{i}")])
    action_row = []
    if selected:
        action_row.append(InlineKeyboardButton(
            f"🗑️ Remover ({len(selected)})",
            callback_data=f"prefs_confirm_remove:{cat}",
        ))
    action_row.append(InlineKeyboardButton("❌ Cancelar", callback_data=f"prefs_cat:{cat}"))
    rows.append(action_row)
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════
# ONBOARDING — ENTRY POINT  (/start)
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = _uid(update), _uname(update)
    try:
        update_user_profile(uid, name=name)
    except Exception as exc:
        logger.warning("cmd_start: upsert failed for %s: %s", uid, exc)

    if _is_profile_complete(uid):
        _onb_clear(context)
        await update.message.reply_text(
            f"Bem-vindo de volta, *{name}*! 👋\n\n"
            f"A tua equipa de saúde está pronta:\n"
            f"🥗 *Nutricionista* · 🏋️ *Trainer* · 👨‍🍳 *Chef*\n\n"
            f"Basta enviares uma mensagem ou usar:\n"
            f"/perfil · /peso · /objectivo · /preferencias · /reset",
            parse_mode="Markdown",
        )
        return

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
    """Single handler for all ob_* callback queries."""
    query = update.callback_query
    await query.answer()
    data  = query.data
    step  = _onb_step(context)

    # ── ob_skip ───────────────────────────────────────
    if data == "ob_skip":
        _onb_clear(context)
        await query.edit_message_text(
            "Tudo bem! Podes começar a conversar quando quiseres. 💬\n"
            "Usa /start a qualquer altura para configurar o teu perfil.",
        )
        return

    # ── ob_start ──────────────────────────────────────
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
        _onb_data(context)["gender"] = "male" if data.endswith(":M") else "female"
        context.user_data[_ONB_STEP] = _STEP_AGE
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é a tua idade? _(em anos, ex: 35)_",
            reply_markup=_skip_keyboard("ob_age_skip"),
            parse_mode="Markdown",
        )
        return

    # ── ob_age_skip ───────────────────────────────────
    if data == "ob_age_skip":
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
        _onb_data(context)["activity_level"] = data.split(":", 1)[1]
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
        if goal_key == "target_weight":
            context.user_data[_ONB_STEP] = _STEP_GOAL_WEIGHT
            await query.edit_message_text(
                "*Passo 3 de 4 — Objectivo* 🎯\n\n"
                "Qual é o teu peso alvo? _(em kg, ex: 75)_",
                reply_markup=_skip_keyboard("ob_goal_weight_skip"),
                parse_mode="Markdown",
            )
            return
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

    # ── ob_goal_weight_skip ───────────────────────────
    if data == "ob_goal_weight_skip":
        _onb_data(context)["goal"] = "Atingir peso específico"
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
        item     = data.split(":", 1)[1]
        selected = _onb_data(context).get("allergies", set())
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


async def _finish_onboarding(query, update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _uid(update)
    d   = _onb_data(context)

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
        logger.error("finish_onboarding: profile save failed for %s: %s", uid, exc)

    allergies = {a for a in d.get("allergies", set()) if a != "nenhuma"}
    for allergy in allergies:
        try:
            add_allergy(uid, allergy)
        except Exception as exc:
            logger.warning("finish_onboarding: allergy save failed: %s", exc)

    if d.get("goal"):
        try:
            add_health_goal(uid, d["goal"])
        except Exception as exc:
            logger.warning("finish_onboarding: goal save failed: %s", exc)

    gender_icon  = "👨" if d.get("gender") == "male" else "👩"
    gender_label = "Masculino" if d.get("gender") == "male" else "Feminino"
    height_str   = f"{d['height_cm']:.0f} cm" if d.get("height_cm") else "—"
    weight_str   = f"{d['weight_kg']:.1f} kg"  if d.get("weight_kg") else "—"
    allergy_str  = ", ".join(sorted(allergies)) if allergies else "Nenhuma"
    activity_label = _ACTIVITY_LABEL.get(d.get("activity_level", ""), "—")

    summary = (
        f"✅ *Perfil criado com sucesso!*\n\n"
        f"{gender_icon} Género: {gender_label}\n"
        f"🎂 Idade: {d.get('age', '—')}\n"
        f"📏 Altura: {height_str}\n"
        f"⚖️ Peso: {weight_str}\n"
        f"🏃 Actividade: {activity_label}\n"
        f"🎯 Objectivo: {d.get('goal', '—')}\n"
        f"⚠️ Alergias: {allergy_str}\n\n"
        f"A tua equipa já conhece o teu perfil! Começa a conversar 💬\n"
        f"_Edita preferências a qualquer altura com_ /preferencias"
    )
    _onb_clear(context)
    await query.edit_message_text(summary, parse_mode="Markdown")


# ══════════════════════════════════════════════════════
# ONBOARDING — TEXT INPUT HANDLER (age / height / weight / goal_weight)
# ══════════════════════════════════════════════════════

async def _handle_onboarding_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume height/weight/age text during onboarding. Returns True if consumed."""
    step = _onb_step(context)

    if step == _STEP_AGE:
        text = update.message.text.strip()
        try:
            age = int(float(text.replace(",", ".")))
            if not (10 <= age <= 120):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Idade inválida. Insere um número entre 10 e 120 _(ex: 35)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context)["age"] = age
        context.user_data[_ONB_STEP] = _STEP_HEIGHT
        await update.message.reply_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é a tua altura? _(em cm, ex: 175)_",
            reply_markup=_skip_keyboard("ob_height_skip"),
            parse_mode="Markdown",
        )
        return True

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

    if step == _STEP_GOAL_WEIGHT:
        text = update.message.text.strip().replace(",", ".")
        try:
            target = float(text)
            if not (30 <= target <= 300):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Peso inválido. Insere um valor entre 30 e 300 kg _(ex: 75)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context)["goal"] = f"Atingir {target:.1f} kg"
        context.user_data[_ONB_STEP] = _STEP_ALLERGIES
        _onb_data(context).setdefault("allergies", set())
        await update.message.reply_text(
            "*Passo 4 de 4 — Alergias e intolerâncias* ⚠️\n\n"
            "Tens alguma alergia ou intolerância alimentar?\n"
            "_(Selecciona todas as que se aplicam)_",
            reply_markup=_allergy_keyboard(set()),
            parse_mode="Markdown",
        )
        return True

    return False


# ══════════════════════════════════════════════════════
# PREFERENCES MENU — /preferencias
# ══════════════════════════════════════════════════════

async def cmd_preferencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the preferences category menu."""
    context.user_data.pop(_PREFS_STATE, None)
    context.user_data.pop(_PREFS_ITEMS, None)
    context.user_data.pop(_PREFS_SEL, None)
    await update.message.reply_text(
        "⚙️ *Preferências e objectivos*\n\nEscolhe uma categoria para editar:",
        reply_markup=_prefs_main_keyboard(),
        parse_mode="Markdown",
    )


async def handle_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single handler for all prefs_* callback queries."""
    query = update.callback_query
    await query.answer()
    data = query.data
    uid  = _uid(update)

    # ── prefs_back → main menu ────────────────────────
    if data == "prefs_back":
        context.user_data.pop(_PREFS_STATE, None)
        context.user_data.pop(_PREFS_ITEMS, None)
        context.user_data.pop(_PREFS_SEL, None)
        await query.edit_message_text(
            "⚙️ *Preferências e objectivos*\n\nEscolhe uma categoria para editar:",
            reply_markup=_prefs_main_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── prefs_cat:{cat} → view category ──────────────
    if data.startswith("prefs_cat:"):
        cat   = data.split(":", 1)[1]
        items = _load_prefs_items(uid, cat)
        context.user_data[_PREFS_STATE] = f"view:{cat}"
        context.user_data[_PREFS_ITEMS] = items
        context.user_data[_PREFS_SEL]   = set()
        cat_label = _PREF_LABEL.get(cat, cat)
        await query.edit_message_text(
            _format_pref_items(items, cat_label),
            reply_markup=_prefs_view_keyboard(cat, bool(items)),
            parse_mode="Markdown",
        )
        return

    # ── prefs_add:{cat} → prompt for text ────────────
    if data.startswith("prefs_add:"):
        cat       = data.split(":", 1)[1]
        cat_label = _PREF_LABEL.get(cat, cat)
        context.user_data[_PREFS_STATE] = f"adding:{cat}"
        await query.edit_message_text(
            f"*{cat_label}* — Adicionar\n\nEscreve o item a adicionar:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancelar", callback_data=f"prefs_cat:{cat}"),
            ]]),
            parse_mode="Markdown",
        )
        return

    # ── prefs_remove_mode:{cat} → toggle keyboard ────
    if data.startswith("prefs_remove_mode:"):
        cat   = data.split(":", 1)[1]
        items = _load_prefs_items(uid, cat)
        context.user_data[_PREFS_ITEMS] = items
        context.user_data[_PREFS_SEL]   = set()
        context.user_data[_PREFS_STATE] = f"removing:{cat}"
        cat_label = _PREF_LABEL.get(cat, cat)
        await query.edit_message_text(
            f"*{cat_label}* — Selecciona os itens a remover:",
            reply_markup=_prefs_remove_keyboard(items, set(), cat),
            parse_mode="Markdown",
        )
        return

    # ── prefs_toggle:{index} → toggle selection ──────
    if data.startswith("prefs_toggle:"):
        idx      = int(data.split(":", 1)[1])
        selected = context.user_data.get(_PREFS_SEL, set())
        items    = context.user_data.get(_PREFS_ITEMS, [])
        state    = context.user_data.get(_PREFS_STATE, "")
        cat      = state.split(":", 1)[1] if ":" in state else ""
        selected.discard(idx) if idx in selected else selected.add(idx)
        context.user_data[_PREFS_SEL] = selected
        cat_label = _PREF_LABEL.get(cat, cat)
        await query.edit_message_text(
            f"*{cat_label}* — Selecciona os itens a remover:",
            reply_markup=_prefs_remove_keyboard(items, selected, cat),
            parse_mode="Markdown",
        )
        return

    # ── prefs_confirm_remove:{cat} → delete selected ─
    if data.startswith("prefs_confirm_remove:"):
        cat      = data.split(":", 1)[1]
        selected = context.user_data.get(_PREFS_SEL, set())
        items    = context.user_data.get(_PREFS_ITEMS, [])
        ids_to_delete = [items[i]["id"] for i in sorted(selected) if i < len(items)]
        n_deleted = _delete_prefs_by_ids(ids_to_delete)
        # Reload and show updated list
        updated  = _load_prefs_items(uid, cat)
        context.user_data[_PREFS_ITEMS] = updated
        context.user_data[_PREFS_SEL]   = set()
        context.user_data[_PREFS_STATE] = f"view:{cat}"
        cat_label = _PREF_LABEL.get(cat, cat)
        await query.edit_message_text(
            f"✅ {n_deleted} item(s) removido(s).\n\n"
            + _format_pref_items(updated, cat_label),
            reply_markup=_prefs_view_keyboard(cat, bool(updated)),
            parse_mode="Markdown",
        )
        return


async def _handle_prefs_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input when in prefs 'adding' state. Returns True if consumed."""
    state = context.user_data.get(_PREFS_STATE, "")
    if not state.startswith("adding:"):
        return False

    cat       = state.split(":", 1)[1]
    cat_label = _PREF_LABEL.get(cat, cat)
    text      = update.message.text.strip()
    uid       = _uid(update)

    if not text:
        return True

    try:
        _add_pref_item(uid, cat, text)
    except Exception as exc:
        logger.error("_handle_prefs_text: add failed: %s", exc)
        await update.message.reply_text("❌ Erro ao adicionar. Tenta novamente.")
        return True

    items = _load_prefs_items(uid, cat)
    context.user_data[_PREFS_STATE] = f"view:{cat}"
    context.user_data[_PREFS_ITEMS] = items
    context.user_data[_PREFS_SEL]   = set()

    await update.message.reply_text(
        f"✅ _{text}_ adicionado a *{cat_label}*.\n\n"
        + _format_pref_items(items, cat_label),
        reply_markup=_prefs_view_keyboard(cat, bool(items)),
        parse_mode="Markdown",
    )
    return True


# ══════════════════════════════════════════════════════
# REGULAR COMMAND HANDLERS
# ══════════════════════════════════════════════════════

async def cmd_perfil(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_user_profile(_uid(update)))


async def cmd_objectivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "❓ Exemplo: `/objectivo Perder 5kg em 3 meses`",
            parse_mode="Markdown",
        )
        return
    result = add_health_goal(_uid(update), text)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_gosto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food = " ".join(context.args) if context.args else ""
    if not food:
        await update.message.reply_text("❓ Exemplo: `/gosto salmão`", parse_mode="Markdown")
        return
    result = add_food_preference(_uid(update), food, likes=True)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_nao_gosto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food = " ".join(context.args) if context.args else ""
    if not food:
        await update.message.reply_text("❓ Exemplo: `/nao_gosto beterraba`", parse_mode="Markdown")
        return
    result = add_food_preference(_uid(update), food, likes=False)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_peso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ Exemplo: `/peso 78.5`", parse_mode="Markdown")
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


async def cmd_historico(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_weight_history(_uid(update)))


async def cmd_reset(update: Update, _: ContextTypes.DEFAULT_TYPE):
    _reset_session(_uid(update))
    await update.message.reply_text("🔄 Conversa reiniciada.")


# ══════════════════════════════════════════════════════
# MESSAGE HANDLER
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
    """Routes text messages: onboarding → prefs → agent team."""
    from xai import get_tracker

    if await _handle_onboarding_text(update, context):
        return
    if await _handle_prefs_text(update, context):
        return

    uid  = _uid(update)
    name = _uname(update)
    msg  = update.message.text
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

        specialist   = _infer_specialist_from_tracker(tracker)
        tools_called = [tc.name for tc in tracker._tool_calls]
        rag_hits     = [(rq.collection, rq.query, rq.hits) for rq in tracker._rag_queries]
        logger.info("[XAI] specialist=%-25s tools=%s", specialist, tools_called)
        for col, q, hits in rag_hits:
            logger.info("[XAI] rag  collection=%-20s hits=%-3d query=%r", col, hits, q[:40])

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

    # Inline keyboard callbacks (highest priority)
    app.add_handler(CallbackQueryHandler(handle_onboarding_callback, pattern="^ob_"))
    app.add_handler(CallbackQueryHandler(handle_prefs_callback,      pattern="^prefs_"))

    # Commands
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("perfil",        cmd_perfil))
    app.add_handler(CommandHandler("preferencias",  cmd_preferencias))
    app.add_handler(CommandHandler("objectivo",     cmd_objectivo))
    app.add_handler(CommandHandler("gosto",         cmd_gosto))
    app.add_handler(CommandHandler("nao_gosto",     cmd_nao_gosto))
    app.add_handler(CommandHandler("peso",          cmd_peso))
    app.add_handler(CommandHandler("historico",     cmd_historico))
    app.add_handler(CommandHandler("reset",         cmd_reset))

    # Free-text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)
    logger.info("✅ Telegram app configured.")
    return app

"""
Telegram Bot Interface — connects Telegram to the Agno agent team.

Onboarding and Preferences menus use inline keyboards with state stored
in context.user_data (no ConversationHandler dependency).
"""

import asyncio
import logging
import re
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

from config import SQLITE_DB
from tools.credential_store import get_telegram_token
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
_STEP_BIRTH_DATE  = "birth_date"
_STEP_HEIGHT      = "height"
_STEP_WEIGHT      = "weight"
_STEP_ACTIVITY    = "activity"
_STEP_GOAL              = "goal"           # kept for edit flow
_STEP_GOALS             = "goals"          # onboarding multi-select
_STEP_GOAL_WEIGHT       = "goal_weight"
_STEP_GOAL_MUSCLE       = "goal_muscle"
_STEP_GOAL_BODY_FAT     = "goal_body_fat"
_STEP_GOAL_VISCERAL_FAT = "goal_visceral_fat"
_STEP_ALLERGIES         = "allergies"
_MAX_GOALS              = 3

_ACTIVITY_OPTIONS = [
    ("sedentary",   "🛋️ Sedentário"),
    ("light",       "🚶 Ligeiro (1-2x/semana)"),
    ("moderate",    "🏃 Moderado (3-5x/semana)"),
    ("active",      "💪 Activo (6-7x/semana)"),
    ("very_active", "🔥 Muito Activo (2x/dia)"),
]
_ACTIVITY_LABEL = {k: v for k, v in _ACTIVITY_OPTIONS}

_GOAL_OPTIONS = [
    ("lose_weight",          "⬇️ Perder peso"),
    ("gain_muscle",          "💪 Ganhar massa muscular"),
    ("lose_fat",             "🔥 Perder massa gorda"),
    ("lose_visceral",        "🫀 Perder gordura visceral"),
    ("maintain",             "⚖️ Manter peso actual"),
    ("improve_fitness",      "🏃 Melhorar condição física"),
    ("improve_health",       "❤️ Melhorar saúde em geral"),
    ("better_diet",          "🍽️ Melhores hábitos alimentares"),
    ("target_weight",        "🎯 Atingir peso específico (ex: 75 kg)"),
    ("target_muscle",        "💪 Atingir massa muscular específica (ex: 65 kg ou 60%)"),
    ("target_body_fat",      "📊 Atingir gordura corporal específica (ex: 15%)"),
    ("target_visceral_fat",  "🔬 Atingir gordura visceral específica (ex: 6 kg)"),
    ("define_abs",           "💎 Definir os abdominais"),
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

_PREF_EXAMPLES = {
    "food_likes":   "Ex: salmão, frango, bróculos, azeite…",
    "food_dislikes": "Ex: beterraba, fígado, coentros…",
    "allergies":    "Ex: lactose, glúten, amendoim…",
    "restrictions": "Ex: vegetariano, low-carb, sem açúcar…",
    "goals":        "Ex: perder 5 kg, correr 5 km, reduzir gordura visceral…",
}

_PREFS_STATE = "prefs_state"
_PREFS_ITEMS = "prefs_items"
_PREFS_SEL   = "prefs_selected"
_EDIT_STEP = "edit_step"


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
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT birth_date, gender, weight_kg FROM user_profiles WHERE user_id = ?", (uid,)
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
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👨 Masculino", callback_data="ob_gender:M"),
            InlineKeyboardButton("👩 Feminino",  callback_data="ob_gender:F"),
        ],
        [
            InlineKeyboardButton("🧑 Outro / Prefiro não dizer", callback_data="ob_gender:O"),
        ],
    ])


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
    rows = [
        [InlineKeyboardButton(label, callback_data=f"ob_goal:{key}")]
        for key, label in _GOAL_OPTIONS
    ]
    return InlineKeyboardMarkup(rows)


def _goals_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Multi-select goals keyboard — toggle up to _MAX_GOALS items."""
    rows = []
    for key, label in _GOAL_OPTIONS:
        prefix = "✅ " if key in selected else ""
        rows.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"ob_goals_toggle:{key}")])
    confirm_label = f"➡️ Confirmar ({len(selected)}/{_MAX_GOALS})" if selected else "➡️ Confirmar (sem objectivo)"
    rows.append([InlineKeyboardButton(confirm_label, callback_data="ob_goals_confirm")])
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


def _format_pref_items(items: list, cat_label: str, cat: str = "") -> str:
    example = _PREF_EXAMPLES.get(cat, "")
    hint = f"_{example}_\n\n" if example else ""
    if not items:
        return f"*{cat_label}*\n\n{hint}_Nenhum item registado._"
    n = len(items)
    lines = [f"*{cat_label}* ({n} item{'s' if n != 1 else ''})\n", hint]
    lines += [f"• {item['text']}" for item in items]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# PREFERENCES — KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════

def _edit_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Nome",                callback_data="edit_field:name")],
        [InlineKeyboardButton("🎂 Data de nascimento",  callback_data="edit_field:birth_date")],
        [InlineKeyboardButton("👤 Género",              callback_data="edit_field:gender")],
        [InlineKeyboardButton("📏 Altura",              callback_data="edit_field:height")],
        [InlineKeyboardButton("⚖️ Peso",                callback_data="edit_field:weight")],
        [InlineKeyboardButton("🏃 Nível de actividade", callback_data="edit_field:activity")],
        [InlineKeyboardButton("🎯 Objectivo",           callback_data="edit_field:goal")],
    ])


def _edit_gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👨 Masculino", callback_data="edit_gender:M"),
            InlineKeyboardButton("👩 Feminino",  callback_data="edit_gender:F"),
        ],
        [InlineKeyboardButton("🧑 Outro / Prefiro não dizer", callback_data="edit_gender:O")],
        [InlineKeyboardButton("◀️ Voltar", callback_data="edit_back")],
    ])


def _edit_activity_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"edit_activity:{key}")]
        for key, label in _ACTIVITY_OPTIONS
    ]
    rows.append([InlineKeyboardButton("◀️ Voltar", callback_data="edit_back")])
    return InlineKeyboardMarkup(rows)


def _edit_goals_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Multi-select goals keyboard for edit flow — toggle up to _MAX_GOALS items."""
    rows = []
    for key, label in _GOAL_OPTIONS:
        prefix = "✅ " if key in selected else ""
        rows.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"edit_goals_toggle:{key}")])
    confirm_label = f"➡️ Confirmar ({len(selected)}/{_MAX_GOALS})" if selected else "➡️ Confirmar (sem objectivo)"
    rows.append([InlineKeyboardButton(confirm_label, callback_data="edit_goals_confirm")])
    rows.append([InlineKeyboardButton("◀️ Voltar", callback_data="edit_back")])
    return InlineKeyboardMarkup(rows)


def _edit_goal_skip_cancel_keyboard(skip_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ Saltar", callback_data=skip_cb)],
        [InlineKeyboardButton("❌ Cancelar", callback_data="edit_back")],
    ])


def _edit_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="edit_back")]])


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
            f"/help · /profile · /edit · /weight · /preferences · /reset",
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
        f"🥗 *Nutricionista*\n"
        f"🏋️ *Personal Trainer*\n"
        f"👨‍🍳 *Chef*\n"
        f"📊 *Analista de Composição Corporal*\n"
        f"🏃 *Analista de Atividade*\n\n"
        f"Para receber conselhos personalizados, preciso de conhecer-te melhor.\n"
        f"São apenas *4 passos rápidos* — menos de 1 minuto! ⚡",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponíveis:\n\n"
        "/start - Iniciar o bot e configurar perfil\n"
        "/profile - Ver o teu perfil\n"
        "/edit - Corrigir dados do perfil (nome, data de nascimento, etc.)\n"
        "/preferences - Gerir preferências (gostos, alergias, etc.)\n"
        "/weight - Registar peso actual\n"
        "/history - Ver histórico de pesos\n"
        "/reset - Reiniciar sessão\n"
        "/help - Mostrar esta ajuda",
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
        gender_map = {":M": "male", ":F": "female", ":O": "other"}
        _onb_data(context)["gender"] = gender_map.get(data[-2:], "other")
        context.user_data[_ONB_STEP] = _STEP_BIRTH_DATE
        await query.edit_message_text(
            "*Passo 1 de 4 — Dados pessoais* 👤\n\n"
            "Qual é a tua data de nascimento? _(formato DD/MM/AAAA, ex: 15/03/1985)_",
            reply_markup=_skip_keyboard("ob_birth_date_skip"),
            parse_mode="Markdown",
        )
        return

    # ── ob_birth_date_skip ────────────────────────────
    if data == "ob_birth_date_skip":
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
        _onb_data(context)["goals_selected"] = set()
        context.user_data[_ONB_STEP] = _STEP_GOALS
        await query.edit_message_text(
            f"*Passo 3 de 4 — Objectivos* 🎯\n\n"
            f"Quais são os teus objectivos de saúde?\n"
            f"_(Podes seleccionar até {_MAX_GOALS})_",
            reply_markup=_goals_keyboard(set()),
            parse_mode="Markdown",
        )
        return

    # ── ob_goals_toggle:* (multi-select) ──────────────
    if data.startswith("ob_goals_toggle:") and step == _STEP_GOALS:
        key      = data.split(":", 1)[1]
        selected = _onb_data(context).get("goals_selected", set())
        if key in selected:
            selected.discard(key)
        elif len(selected) < _MAX_GOALS:
            selected.add(key)
        else:
            await query.answer(f"Máximo de {_MAX_GOALS} objectivos atingido.", show_alert=False)
            return
        _onb_data(context)["goals_selected"] = selected
        await query.edit_message_text(
            f"*Passo 3 de 4 — Objectivos* 🎯\n\n"
            f"Quais são os teus objectivos de saúde?\n"
            f"_(Podes seleccionar até {_MAX_GOALS})_",
            reply_markup=_goals_keyboard(selected),
            parse_mode="Markdown",
        )
        return

    # ── ob_goals_confirm ──────────────────────────────
    if data == "ob_goals_confirm" and step == _STEP_GOALS:
        selected = _onb_data(context).get("goals_selected", set())
        _TARGET_STEPS = {
            "target_weight":       _STEP_GOAL_WEIGHT,
            "target_muscle":       _STEP_GOAL_MUSCLE,
            "target_body_fat":     _STEP_GOAL_BODY_FAT,
            "target_visceral_fat": _STEP_GOAL_VISCERAL_FAT,
        }
        _TARGET_PROMPTS = {
            "target_weight":       "Qual é o teu peso alvo? _(em kg, ex: 75)_",
            "target_muscle":       "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
            "target_body_fat":     "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
            "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
        }
        # Split into simple goals (stored immediately) and target goals (need input)
        simple_goals    = [_GOAL_LABEL[k] for k in selected if k not in _TARGET_STEPS]
        pending_targets = [k for k in selected if k in _TARGET_STEPS]
        _onb_data(context)["goals_confirmed"] = simple_goals
        _onb_data(context)["goals_pending"]   = pending_targets

        if not selected:
            # No goals chosen — go straight to allergies
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

        if pending_targets:
            next_key = pending_targets[0]
            context.user_data[_ONB_STEP] = _TARGET_STEPS[next_key]
            await query.edit_message_text(
                f"*Passo 3 de 4 — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS[next_key]}",
                reply_markup=_skip_keyboard(f"ob_goal_{next_key.replace('target_', '')}_skip"),
                parse_mode="Markdown",
            )
        else:
            # Only simple goals — go to allergies
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
        if goal_key == "target_muscle":
            context.user_data[_ONB_STEP] = _STEP_GOAL_MUSCLE
            await query.edit_message_text(
                "*Passo 3 de 4 — Objectivo* 🎯\n\n"
                "Qual é a tua percentagem de massa muscular alvo? _(em %, ex: 40)_",
                reply_markup=_skip_keyboard("ob_goal_muscle_skip"),
                parse_mode="Markdown",
            )
            return
        if goal_key == "target_body_fat":
            context.user_data[_ONB_STEP] = _STEP_GOAL_BODY_FAT
            await query.edit_message_text(
                "*Passo 3 de 4 — Objectivo* 🎯\n\n"
                "Qual é a tua percentagem de gordura corporal alvo? _(em %, ex: 15)_",
                reply_markup=_skip_keyboard("ob_goal_body_fat_skip"),
                parse_mode="Markdown",
            )
            return
        if goal_key == "target_visceral_fat":
            context.user_data[_ONB_STEP] = _STEP_GOAL_VISCERAL_FAT
            await query.edit_message_text(
                "*Passo 3 de 4 — Objectivo* 🎯\n\n"
                "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
                reply_markup=_skip_keyboard("ob_goal_visceral_fat_skip"),
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

    # ── ob_goal_*_skip ────────────────────────────────
    _GOAL_SKIP_LABELS = {
        "ob_goal_weight_skip":      "Atingir peso específico",
        "ob_goal_muscle_skip":      "Atingir massa muscular específica",
        "ob_goal_body_fat_skip":    "Atingir gordura corporal específica",
        "ob_goal_visceral_fat_skip":"Atingir gordura visceral específica",
    }
    if data in _GOAL_SKIP_LABELS:
        label = _GOAL_SKIP_LABELS[data]
        # Multi-goal flow: append to list and advance pending queue
        if "goals_pending" in _onb_data(context):
            _onb_data(context).setdefault("goals_confirmed", []).append(label)
            pending = _onb_data(context).get("goals_pending", [])
            if pending:
                pending.pop(0)
            if pending:
                _TARGET_STEPS = {
                    "target_weight": _STEP_GOAL_WEIGHT, "target_muscle": _STEP_GOAL_MUSCLE,
                    "target_body_fat": _STEP_GOAL_BODY_FAT, "target_visceral_fat": _STEP_GOAL_VISCERAL_FAT,
                }
                _TARGET_PROMPTS = {
                    "target_weight": "Qual é o teu peso alvo? _(em kg, ex: 75)_",
                    "target_muscle": "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
                    "target_body_fat": "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
                    "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
                }
                next_key = pending[0]
                context.user_data[_ONB_STEP] = _TARGET_STEPS[next_key]
                await query.edit_message_text(
                    f"*Passo 3 de 4 — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS[next_key]}",
                    reply_markup=_skip_keyboard(f"ob_goal_{next_key.replace('target_', '')}_skip"),
                    parse_mode="Markdown",
                )
                return
        else:
            # Single-goal (edit) flow
            _onb_data(context)["goal"] = label
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
            birth_date=d.get("birth_date"),
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

    for goal_str in d.get("goals_confirmed", []):
        try:
            add_health_goal(uid, goal_str)
        except Exception as exc:
            logger.warning("finish_onboarding: goal save failed (%s): %s", goal_str, exc)
    # Backward compat: single-goal flow (edit path)
    if not d.get("goals_confirmed") and d.get("goal"):
        try:
            add_health_goal(uid, d["goal"])
        except Exception as exc:
            logger.warning("finish_onboarding: goal save failed: %s", exc)

    _gender_display = {"male": ("👨", "Masculino"), "female": ("👩", "Feminino"), "other": ("🧑", "Outro")}
    gender_icon, gender_label = _gender_display.get(d.get("gender", ""), ("🧑", "Outro"))
    height_str   = f"{d['height_cm']:.0f} cm" if d.get("height_cm") else "—"
    weight_str   = f"{d['weight_kg']:.1f} kg"  if d.get("weight_kg") else "—"
    allergy_str  = ", ".join(sorted(allergies)) if allergies else "Nenhuma"
    activity_label = _ACTIVITY_LABEL.get(d.get("activity_level", ""), "—")

    birth_date_display = d.get("birth_date") or "—"
    summary = (
        f"✅ *Perfil criado com sucesso!*\n\n"
        f"{gender_icon} Género: {gender_label}\n"
        f"🎂 Data de nascimento: {birth_date_display}\n"
        f"📏 Altura: {height_str}\n"
        f"⚖️ Peso: {weight_str}\n"
        f"🏃 Actividade: {activity_label}\n"
        f"🎯 Objectivos: {', '.join(d.get('goals_confirmed', [])) or d.get('goal', '—')}\n"
        f"⚠️ Alergias: {allergy_str}\n\n"
        f"A tua equipa já conhece o teu perfil! Começa a conversar 💬\n"
        f"_Edita preferências a qualquer altura com_ /preferences"
    )
    _onb_clear(context)
    await query.edit_message_text(summary, parse_mode="Markdown")


async def _advance_pending_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Pop next pending target goal and ask for its value, or transition to allergies."""
    _TARGET_STEPS = {
        "target_weight":       _STEP_GOAL_WEIGHT,
        "target_muscle":       _STEP_GOAL_MUSCLE,
        "target_body_fat":     _STEP_GOAL_BODY_FAT,
        "target_visceral_fat": _STEP_GOAL_VISCERAL_FAT,
    }
    _TARGET_PROMPTS = {
        "target_weight":       "Qual é o teu peso alvo? _(em kg, ex: 75)_",
        "target_muscle":       "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
        "target_body_fat":     "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
        "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
    }
    _SKIP_KEYS = {
        "target_weight":       "ob_goal_weight_skip",
        "target_muscle":       "ob_goal_muscle_skip",
        "target_body_fat":     "ob_goal_body_fat_skip",
        "target_visceral_fat": "ob_goal_visceral_fat_skip",
    }
    pending = _onb_data(context).get("goals_pending", [])
    # Remove the one we just processed (it was at the front)
    if pending:
        pending.pop(0)

    if pending:
        next_key = pending[0]
        context.user_data[_ONB_STEP] = _TARGET_STEPS[next_key]
        await update.message.reply_text(
            f"*Passo 3 de 4 — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS[next_key]}",
            reply_markup=_skip_keyboard(_SKIP_KEYS[next_key]),
            parse_mode="Markdown",
        )
    else:
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


# ══════════════════════════════════════════════════════
# ONBOARDING — TEXT INPUT HANDLER (birth_date / height / weight / goal_weight)
# ══════════════════════════════════════════════════════

async def _handle_onboarding_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume birth_date/height/weight text during onboarding. Returns True if consumed."""
    step = _onb_step(context)

    if step == _STEP_BIRTH_DATE:
        text = update.message.text.strip()
        birth_date_iso = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                from datetime import datetime as _dt
                birth_date_iso = _dt.strptime(text, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if not birth_date_iso:
            await update.message.reply_text(
                "❌ Data inválida. Insere no formato DD/MM/AAAA _(ex: 15/03/1985)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context)["birth_date"] = birth_date_iso
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
        _onb_data(context).setdefault("goals_confirmed", []).append(f"Atingir {target:.1f} kg")
        return await _advance_pending_goals(update, context)

    if step == _STEP_GOAL_MUSCLE:
        text = update.message.text.strip().replace(",", ".")
        try:
            target = float(text)
            if not (10 <= target <= 120):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Valor inválido. Insere um valor entre 10 e 120 kg _(ex: 65)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context).setdefault("goals_confirmed", []).append(f"Atingir {target:.1f} kg de massa muscular")
        return await _advance_pending_goals(update, context)

    if step == _STEP_GOAL_BODY_FAT:
        text = update.message.text.strip().replace(",", ".")
        try:
            target = float(text)
            if not (1 <= target <= 60):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Valor inválido. Insere uma percentagem entre 1 e 60 _(ex: 15)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context).setdefault("goals_confirmed", []).append(f"Atingir {target:.1f}% de gordura corporal")
        return await _advance_pending_goals(update, context)

    if step == _STEP_GOAL_VISCERAL_FAT:
        text = update.message.text.strip().replace(",", ".")
        try:
            target = float(text)
            if not (1 <= target <= 30):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Valor inválido. Insere um nível entre 1 e 30 _(ex: 6)_.\n"
                "Ou usa o botão *Saltar* na mensagem acima.",
                parse_mode="Markdown",
            )
            return True
        _onb_data(context).setdefault("goals_confirmed", []).append(f"Atingir nível {target:.1f} de gordura visceral")
        return await _advance_pending_goals(update, context)

    return False


# ══════════════════════════════════════════════════════
# PREFERENCES MENU — /preferencias
# ══════════════════════════════════════════════════════

async def cmd_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            _format_pref_items(items, cat_label, cat),
            reply_markup=_prefs_view_keyboard(cat, bool(items)),
            parse_mode="Markdown",
        )
        return

    # ── prefs_add:{cat} → prompt for text ────────────
    if data.startswith("prefs_add:"):
        cat       = data.split(":", 1)[1]
        cat_label = _PREF_LABEL.get(cat, cat)
        context.user_data[_PREFS_STATE] = f"adding:{cat}"
        example = _PREF_EXAMPLES.get(cat, "")
        hint = f"\n_{example}_" if example else ""
        await query.edit_message_text(
            f"*{cat_label}* — Adicionar\n\nEscreve o item a adicionar:{hint}",
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
            + _format_pref_items(updated, cat_label, cat),
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
        + _format_pref_items(items, cat_label, cat),
        reply_markup=_prefs_view_keyboard(cat, bool(items)),
        parse_mode="Markdown",
    )
    return True


# ══════════════════════════════════════════════════════
# EDIT PROFILE — /editar
# ══════════════════════════════════════════════════════

async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(_EDIT_STEP, None)
    await update.message.reply_text(
        "✏️ *Editar perfil*\n\nQual campo queres actualizar?",
        reply_markup=_edit_main_keyboard(),
        parse_mode="Markdown",
    )


async def _edit_finish_goals(query_or_msg, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear existing goals, save newly confirmed goals, return to edit menu."""
    uid = _uid(update)
    confirmed = context.user_data.pop("edit_goals_confirmed", [])
    context.user_data.pop("edit_goals_pending", None)
    context.user_data.pop("edit_goals_selected", None)
    context.user_data.pop(_EDIT_STEP, None)

    try:
        existing = _load_prefs_items(uid, "goals")
        if existing:
            _delete_prefs_by_ids([i["id"] for i in existing])
    except Exception as exc:
        logger.warning("_edit_finish_goals: clear failed: %s", exc)

    for goal_str in confirmed:
        try:
            add_health_goal(uid, goal_str)
        except Exception as exc:
            logger.warning("_edit_finish_goals: save goal failed (%s): %s", goal_str, exc)

    goals_display = ", ".join(confirmed) if confirmed else "_(nenhum)_"
    text = (
        f"✅ *Objectivos actualizados:* {goals_display}\n\n"
        "✏️ *Editar perfil*\n\nQual campo queres actualizar?"
    )
    if hasattr(query_or_msg, "edit_message_text"):
        await query_or_msg.edit_message_text(text, reply_markup=_edit_main_keyboard(), parse_mode="Markdown")
    else:
        await query_or_msg.reply_text(text, reply_markup=_edit_main_keyboard(), parse_mode="Markdown")


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single handler for all edit_* callback queries."""
    query = update.callback_query
    await query.answer()
    data = query.data
    uid  = _uid(update)

    _BACK_TEXT = "✏️ *Editar perfil*\n\nQual campo queres actualizar?"

    # ── edit_back → main menu ─────────────────────────
    if data == "edit_back":
        context.user_data.pop(_EDIT_STEP, None)
        context.user_data.pop("edit_goals_selected", None)
        context.user_data.pop("edit_goals_confirmed", None)
        context.user_data.pop("edit_goals_pending", None)
        await query.edit_message_text(
            _BACK_TEXT,
            reply_markup=_edit_main_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── edit_field:{field} → prompt for value ─────────
    if data.startswith("edit_field:"):
        field = data.split(":", 1)[1]
        if field == "gender":
            context.user_data.pop(_EDIT_STEP, None)
            await query.edit_message_text(
                "✏️ *Editar perfil — Género* 👤\n\nQual é o teu género?",
                reply_markup=_edit_gender_keyboard(),
                parse_mode="Markdown",
            )
        elif field == "activity":
            context.user_data.pop(_EDIT_STEP, None)
            await query.edit_message_text(
                "✏️ *Editar perfil — Nível de actividade* 🏃\n\n"
                "Qual é o teu nível de actividade física habitual?",
                reply_markup=_edit_activity_keyboard(),
                parse_mode="Markdown",
            )
        elif field == "goal":
            context.user_data.pop(_EDIT_STEP, None)
            context.user_data["edit_goals_selected"] = set()
            await query.edit_message_text(
                f"✏️ *Editar perfil — Objectivos* 🎯\n\n"
                f"Quais são os teus objectivos de saúde?\n"
                f"_(Podes seleccionar até {_MAX_GOALS}. Os actuais serão substituídos.)_",
                reply_markup=_edit_goals_keyboard(set()),
                parse_mode="Markdown",
            )
        elif field == "name":
            context.user_data[_EDIT_STEP] = "name"
            await query.edit_message_text(
                "✏️ *Editar perfil — Nome* 📝\n\nEscreve o teu novo nome:",
                reply_markup=_edit_cancel_keyboard(),
                parse_mode="Markdown",
            )
        elif field == "birth_date":
            context.user_data[_EDIT_STEP] = "birth_date"
            await query.edit_message_text(
                "✏️ *Editar perfil — Data de nascimento* 🎂\n\n"
                "Escreve a tua data de nascimento _(formato DD/MM/AAAA, ex: 15/03/1985)_:",
                reply_markup=_edit_cancel_keyboard(),
                parse_mode="Markdown",
            )
        elif field == "height":
            context.user_data[_EDIT_STEP] = "height"
            await query.edit_message_text(
                "✏️ *Editar perfil — Altura* 📏\n\nEscreve a tua altura _(em cm, ex: 175)_:",
                reply_markup=_edit_cancel_keyboard(),
                parse_mode="Markdown",
            )
        elif field == "weight":
            context.user_data[_EDIT_STEP] = "weight"
            await query.edit_message_text(
                "✏️ *Editar perfil — Peso* ⚖️\n\nEscreve o teu peso actual _(em kg, ex: 78.5)_:",
                reply_markup=_edit_cancel_keyboard(),
                parse_mode="Markdown",
            )
        return

    # ── edit_gender:* ─────────────────────────────────
    if data.startswith("edit_gender:"):
        gender_map = {":M": "male", ":F": "female", ":O": "other"}
        gender_label = {"male": "Masculino", "female": "Feminino", "other": "Outro"}
        gender = gender_map.get(data[-2:], "other")
        try:
            update_user_profile(uid, gender=gender)
        except Exception as exc:
            logger.error("edit_gender: save failed for %s: %s", uid, exc)
            await query.edit_message_text("❌ Erro ao guardar. Tenta novamente.")
            return
        await query.edit_message_text(
            f"✅ *Género actualizado:* {gender_label.get(gender, gender)}\n\n" + _BACK_TEXT,
            reply_markup=_edit_main_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── edit_activity:* ───────────────────────────────
    if data.startswith("edit_activity:"):
        level = data.split(":", 1)[1]
        label = _ACTIVITY_LABEL.get(level, level)
        try:
            update_user_profile(uid, activity_level=level)
        except Exception as exc:
            logger.error("edit_activity: save failed for %s: %s", uid, exc)
            await query.edit_message_text("❌ Erro ao guardar. Tenta novamente.")
            return
        await query.edit_message_text(
            f"✅ *Nível de actividade actualizado:* {label}\n\n" + _BACK_TEXT,
            reply_markup=_edit_main_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── edit_goals_toggle:* ───────────────────────────
    if data.startswith("edit_goals_toggle:"):
        key = data.split(":", 1)[1]
        selected = context.user_data.get("edit_goals_selected", set())
        if key in selected:
            selected.discard(key)
        elif len(selected) < _MAX_GOALS:
            selected.add(key)
        else:
            await query.answer(f"Máximo de {_MAX_GOALS} objectivos atingido.", show_alert=False)
            return
        context.user_data["edit_goals_selected"] = selected
        await query.edit_message_text(
            f"✏️ *Editar perfil — Objectivos* 🎯\n\n"
            f"Quais são os teus objectivos de saúde?\n"
            f"_(Podes seleccionar até {_MAX_GOALS}. Os actuais serão substituídos.)_",
            reply_markup=_edit_goals_keyboard(selected),
            parse_mode="Markdown",
        )
        return

    # ── edit_goals_confirm ────────────────────────────
    if data == "edit_goals_confirm":
        selected = context.user_data.get("edit_goals_selected", set())
        _TARGET_STEPS_EDIT = {
            "target_weight":       "goal_weight",
            "target_muscle":       "goal_muscle",
            "target_body_fat":     "goal_body_fat",
            "target_visceral_fat": "goal_visceral_fat",
        }
        _TARGET_PROMPTS_EDIT = {
            "target_weight":       "Qual é o teu peso alvo? _(em kg, ex: 75)_",
            "target_muscle":       "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
            "target_body_fat":     "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
            "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
        }
        _TARGET_SKIP_CBS = {
            "target_weight":       "edit_goal_weight_skip",
            "target_muscle":       "edit_goal_muscle_skip",
            "target_body_fat":     "edit_goal_body_fat_skip",
            "target_visceral_fat": "edit_goal_visceral_fat_skip",
        }
        simple_goals    = [_GOAL_LABEL[k] for k in selected if k not in _TARGET_STEPS_EDIT]
        pending_targets = [k for k in selected if k in _TARGET_STEPS_EDIT]
        context.user_data["edit_goals_confirmed"] = simple_goals
        context.user_data["edit_goals_pending"]   = pending_targets
        if pending_targets:
            next_key = pending_targets[0]
            context.user_data[_EDIT_STEP] = _TARGET_STEPS_EDIT[next_key]
            await query.edit_message_text(
                f"✏️ *Editar perfil — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS_EDIT[next_key]}",
                reply_markup=_edit_goal_skip_cancel_keyboard(_TARGET_SKIP_CBS[next_key]),
                parse_mode="Markdown",
            )
            return
        await _edit_finish_goals(query, update, context)
        return

    # ── edit_goal_*_skip ──────────────────────────────
    _EDIT_GOAL_SKIP_LABELS = {
        "edit_goal_weight_skip":       _GOAL_LABEL["target_weight"],
        "edit_goal_muscle_skip":       _GOAL_LABEL["target_muscle"],
        "edit_goal_body_fat_skip":     _GOAL_LABEL["target_body_fat"],
        "edit_goal_visceral_fat_skip": _GOAL_LABEL["target_visceral_fat"],
    }
    _EDIT_GOAL_SKIP_NEXT = {
        "edit_goal_weight_skip":       "target_weight",
        "edit_goal_muscle_skip":       "target_muscle",
        "edit_goal_body_fat_skip":     "target_body_fat",
        "edit_goal_visceral_fat_skip": "target_visceral_fat",
    }
    if data in _EDIT_GOAL_SKIP_LABELS:
        label = _EDIT_GOAL_SKIP_LABELS[data]
        context.user_data.setdefault("edit_goals_confirmed", []).append(label)
        pending = context.user_data.get("edit_goals_pending", [])
        skipped_key = _EDIT_GOAL_SKIP_NEXT[data]
        if skipped_key in pending:
            pending.remove(skipped_key)
        context.user_data.pop(_EDIT_STEP, None)
        _TARGET_STEPS_EDIT = {
            "target_weight":       "goal_weight",
            "target_muscle":       "goal_muscle",
            "target_body_fat":     "goal_body_fat",
            "target_visceral_fat": "goal_visceral_fat",
        }
        _TARGET_PROMPTS_EDIT = {
            "target_weight":       "Qual é o teu peso alvo? _(em kg, ex: 75)_",
            "target_muscle":       "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
            "target_body_fat":     "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
            "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
        }
        _TARGET_SKIP_CBS = {
            "target_weight":       "edit_goal_weight_skip",
            "target_muscle":       "edit_goal_muscle_skip",
            "target_body_fat":     "edit_goal_body_fat_skip",
            "target_visceral_fat": "edit_goal_visceral_fat_skip",
        }
        if pending:
            next_key = pending[0]
            context.user_data[_EDIT_STEP] = _TARGET_STEPS_EDIT[next_key]
            await query.edit_message_text(
                f"✏️ *Editar perfil — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS_EDIT[next_key]}",
                reply_markup=_edit_goal_skip_cancel_keyboard(_TARGET_SKIP_CBS[next_key]),
                parse_mode="Markdown",
            )
            return
        await _edit_finish_goals(query, update, context)
        return


async def _handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during edit flow. Returns True if consumed."""
    step = context.user_data.get(_EDIT_STEP)
    if not step:
        return False

    uid  = _uid(update)
    text = update.message.text.strip()

    async def _save_and_confirm(field_label: str, **kwargs):
        try:
            update_user_profile(uid, **kwargs)
        except Exception as exc:
            logger.error("_handle_edit_text: save failed for %s: %s", uid, exc)
            await update.message.reply_text("❌ Erro ao guardar. Tenta novamente.")
            return
        context.user_data.pop(_EDIT_STEP, None)
        await update.message.reply_text(
            f"✅ *{field_label} actualizado(a).*\n\nQual campo queres actualizar a seguir?",
            reply_markup=_edit_main_keyboard(),
            parse_mode="Markdown",
        )

    if step == "name":
        if not text:
            await update.message.reply_text("❌ Nome inválido. Tenta novamente.")
            return True
        await _save_and_confirm("Nome", name=text)
        return True

    if step == "birth_date":
        birth_date_iso = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                birth_date_iso = datetime.strptime(text, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if not birth_date_iso:
            await update.message.reply_text(
                "❌ Data inválida. Insere no formato DD/MM/AAAA _(ex: 15/03/1985)_.",
                parse_mode="Markdown",
            )
            return True
        await _save_and_confirm("Data de nascimento", birth_date=birth_date_iso)
        return True

    if step == "height":
        try:
            height = float(text.replace(",", "."))
            if not (100 <= height <= 250):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Altura inválida. Insere um valor entre 100 e 250 cm _(ex: 175)_.",
                parse_mode="Markdown",
            )
            return True
        await _save_and_confirm("Altura", height_cm=height)
        return True

    if step == "weight":
        try:
            weight = float(text.replace(",", "."))
            if not (30 <= weight <= 300):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Peso inválido. Insere um valor entre 30 e 300 kg _(ex: 78.5)_.",
                parse_mode="Markdown",
            )
            return True
        await _save_and_confirm("Peso", weight_kg=weight)
        return True

    _GOAL_STEP_CONFIG = {
        "goal_weight":       (30,  300, lambda t: f"Atingir {t:.1f} kg",                       "❌ Peso inválido. Insere um valor entre 30 e 300 kg _(ex: 75)_."),
        "goal_muscle":       (1,   80,  lambda t: f"Atingir {t:.1f}% de massa muscular",        "❌ Valor inválido. Insere uma percentagem entre 1 e 80 _(ex: 40)_."),
        "goal_body_fat":     (1,   60,  lambda t: f"Atingir {t:.1f}% de gordura corporal",      "❌ Valor inválido. Insere uma percentagem entre 1 e 60 _(ex: 15)_."),
        "goal_visceral_fat": (1,   30,  lambda t: f"Atingir nível {t:.1f} de gordura visceral", "❌ Valor inválido. Insere um nível entre 1 e 30 _(ex: 6)_."),
    }
    if step in _GOAL_STEP_CONFIG:
        lo, hi, fmt, err_msg = _GOAL_STEP_CONFIG[step]
        try:
            target = float(text.replace(",", "."))
            if not (lo <= target <= hi):
                raise ValueError
        except ValueError:
            await update.message.reply_text(err_msg, parse_mode="Markdown")
            return True
        goal_text = fmt(target)
        context.user_data.setdefault("edit_goals_confirmed", []).append(goal_text)
        pending = context.user_data.get("edit_goals_pending", [])
        _TARGET_STEPS_EDIT = {
            "target_weight":       "goal_weight",
            "target_muscle":       "goal_muscle",
            "target_body_fat":     "goal_body_fat",
            "target_visceral_fat": "goal_visceral_fat",
        }
        _TARGET_PROMPTS_EDIT = {
            "target_weight":       "Qual é o teu peso alvo? _(em kg, ex: 75)_",
            "target_muscle":       "Qual é a tua massa muscular alvo? _(em kg, ex: 65)_",
            "target_body_fat":     "Qual é a tua % de gordura corporal alvo? _(ex: 15)_",
            "target_visceral_fat": "Qual é o teu nível de gordura visceral alvo? _(ex: 6)_",
        }
        _TARGET_SKIP_CBS = {
            "target_weight":       "edit_goal_weight_skip",
            "target_muscle":       "edit_goal_muscle_skip",
            "target_body_fat":     "edit_goal_body_fat_skip",
            "target_visceral_fat": "edit_goal_visceral_fat_skip",
        }
        # Pop the current pending target (first element matches current step)
        step_to_key = {v: k for k, v in _TARGET_STEPS_EDIT.items()}
        done_key = step_to_key.get(step)
        if done_key in pending:
            pending.remove(done_key)
        context.user_data[_EDIT_STEP] = None
        if pending:
            next_key = pending[0]
            context.user_data[_EDIT_STEP] = _TARGET_STEPS_EDIT[next_key]
            await update.message.reply_text(
                f"✏️ *Editar perfil — Objectivo específico* 🎯\n\n{_TARGET_PROMPTS_EDIT[next_key]}",
                reply_markup=_edit_goal_skip_cancel_keyboard(_TARGET_SKIP_CBS[next_key]),
                parse_mode="Markdown",
            )
            return True
        await _edit_finish_goals(update.message, update, context)
        return True

    return False


# ══════════════════════════════════════════════════════
# REGULAR COMMAND HANDLERS
# ══════════════════════════════════════════════════════

async def cmd_profile(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_user_profile(_uid(update)))



async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ Exemplo: `/weight 78.5`", parse_mode="Markdown")
        return
    try:
        weight = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Peso inválido. Usa um número (ex: 78.5)")
        return
    update_user_profile(_uid(update), weight_kg=weight)
    await update.message.reply_text(
        f"⚖️ Peso registado: *{weight} kg*\nUsa /history para ver evolução.",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, _: ContextTypes.DEFAULT_TYPE):
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


_METADATA_PREFIX_RE = re.compile(
    r"\[Data de hoje:[^\]]*\]\s*\[ID do utilizador:[^\]]*\]\s*\n?",
    re.IGNORECASE,
)


def _sanitize_response(text: str) -> str:
    # Strip any metadata prefix the model leaked into its reply.
    text = _METADATA_PREFIX_RE.sub("", text).lstrip()
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
    if await _handle_edit_text(update, context):
        return

    uid  = _uid(update)
    name = _uname(update)
    msg  = update.message.text
    if not msg:
        return

    tracker = get_tracker()
    tracker.reset(msg)
    logger.info("[%s] %s: %s", uid, name, msg[:80])

    today = datetime.now().strftime("%d/%m/%Y")
    enriched = f"[Data de hoje: {today}] [ID do utilizador: {uid}]\n{msg}"

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
    token = get_telegram_token()
    if not token:
        raise ValueError(
            "Token do Telegram não configurado.\n"
            "  Execute: python scripts/setup_telegram.py"
        )

    app = Application.builder().token(token).build()

    # Inline keyboard callbacks (highest priority)
    app.add_handler(CallbackQueryHandler(handle_onboarding_callback, pattern="^ob_"))
    app.add_handler(CallbackQueryHandler(handle_prefs_callback,      pattern="^prefs_"))
    app.add_handler(CallbackQueryHandler(handle_edit_callback,       pattern="^edit_"))

    # Commands
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("profile",       cmd_profile))
    app.add_handler(CommandHandler("edit",          cmd_edit))
    app.add_handler(CommandHandler("preferences",   cmd_preferences))
    app.add_handler(CommandHandler("weight",        cmd_weight))
    app.add_handler(CommandHandler("history",       cmd_history))
    app.add_handler(CommandHandler("reset",         cmd_reset))

    # Free-text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)
    logger.info("✅ Telegram app configured.")
    return app

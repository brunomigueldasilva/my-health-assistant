"""
Tab: 🥗 Nutrição e Gostos

Business logic and UI builder for the nutrition and preferences tab.
Covers: food likes/dislikes, allergies, restrictions, health data, goals.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import gradio as gr

# Path setup
_root = Path(__file__).resolve().parent.parent.parent.parent
_iface = Path(__file__).resolve().parent.parent
for _p in (_root, _iface):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from knowledge import get_knowledge_base
from tools.profile_tools import add_food_preference, add_health_goal

_PREF_CATS = ["food_likes", "food_dislikes", "allergies", "goals", "restrictions", "health_data"]


def _load_category_list(uid: str, category: str) -> list[str]:
    uid = uid.strip()
    if not uid:
        return []
    kb = get_knowledge_base()
    try:
        data = kb.preferences.get(
            where={"$and": [{"user_id": uid}, {"category": category}]}
        )
        if data and data.get("documents"):
            return sorted(data["documents"])
    except Exception:
        pass
    return []


def _delete_pref_exact(uid: str, doc_text: str) -> bool:
    """Delete an exact preference document, searching all categories."""
    kb = get_knowledge_base()
    for cat in _PREF_CATS:
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": uid}, {"category": cat}]}
            )
            if data and data.get("ids"):
                for i, doc in enumerate(data["documents"]):
                    if doc == doc_text:
                        kb.preferences.delete(ids=[data["ids"][i]])
                        return True
        except Exception:
            pass
    return False


def load_all_prefs(uid):
    """Returns a gr.update for each of the 6 preference CheckboxGroups."""
    uid = (uid or "").strip()
    return tuple(
        gr.update(choices=_load_category_list(uid, cat), value=[])
        for cat in _PREF_CATS
    )


# ── Food likes ───────────────────────────────────────────

def add_like_fn(uid: str, food: str):
    uid = uid.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento.", gr.update(), ""
    add_food_preference(uid, food.strip(), likes=True)
    return (
        f"✅ '{food.strip()}' adicionado aos gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        "",
    )


def remove_likes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
    )


def move_to_dislikes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona itens para mover.", gr.update(), gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
        add_food_preference(uid, item, likes=False)
    return (
        f"✅ {len(selected)} item(s) movido(s) para Não Gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


# ── Food dislikes ────────────────────────────────────────

def add_dislike_fn(uid: str, food: str):
    uid = uid.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento.", gr.update(), ""
    add_food_preference(uid, food.strip(), likes=False)
    return (
        f"✅ '{food.strip()}' adicionado aos não gostos.",
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
        "",
    )


def remove_dislikes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


def move_to_likes_fn(uid: str, selected: list):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona itens para mover.", gr.update(), gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
        add_food_preference(uid, item, likes=True)
    return (
        f"✅ {len(selected)} item(s) movido(s) para Gostos.",
        gr.update(choices=_load_category_list(uid, "food_likes"), value=[]),
        gr.update(choices=_load_category_list(uid, "food_dislikes"), value=[]),
    )


# ── Generic category (allergies, restrictions, health_data) ─

def add_cat_item_fn(uid: str, text: str, category: str):
    uid = uid.strip()
    if not uid or not text.strip():
        return "❌ Preenche o User ID e o texto.", gr.update(), ""
    kb = get_knowledge_base()
    kb.add_preference(uid, category, text.strip(), {"created": datetime.now().isoformat()})
    return (
        "✅ Adicionado.",
        gr.update(choices=_load_category_list(uid, category), value=[]),
        "",
    )


def remove_cat_items_fn(uid: str, selected: list, category: str):
    uid = uid.strip()
    if not uid or not selected:
        return "❌ Seleciona pelo menos um item.", gr.update()
    for item in selected:
        _delete_pref_exact(uid, item)
    return (
        f"✅ {len(selected)} item(s) removido(s).",
        gr.update(choices=_load_category_list(uid, category), value=[]),
    )


# ── Goals ────────────────────────────────────────────────

def add_goal_and_refresh(uid: str, goal: str):
    uid = uid.strip()
    if not uid or not goal.strip():
        return "❌ Preenche o User ID e o objetivo.", gr.update(), ""
    add_health_goal(uid, goal.strip())
    return (
        "✅ Objetivo adicionado.",
        gr.update(choices=_load_category_list(uid, "goals"), value=[]),
        "",
    )


def apply_seed_fn(user_id: str):
    uid = user_id.strip()
    _empty = tuple(gr.update() for _ in _PREF_CATS)
    if not uid:
        return ("❌ Introduz um User ID.", *_empty)
    try:
        from knowledge.seed_data import seed_user_preferences
        seed_user_preferences(uid, force=True)
        updates = load_all_prefs(uid)
        return (f"✅ Preferências padrão aplicadas a '{uid}'.", *updates)
    except Exception as e:
        return (f"❌ Erro: {e}", *_empty)


# ── UI builder ───────────────────────────────────────────

def build_nutrition_tab() -> SimpleNamespace:
    """Create the nutrition tab UI. Must be called inside a gr.Blocks() context."""
    with gr.Row():
        load_prefs_btn = gr.Button("🔄 Carregar Preferências", variant="primary")
        apply_seed_btn = gr.Button("🌱 Aplicar Padrão", variant="secondary")
        prefs_status = gr.Markdown()

    with gr.Accordion("🥦 Alimentos — Gostos e Não Gostos", open=True):
        with gr.Row(equal_height=False):
            # ── Lista GOSTO ──────────────────────────────
            with gr.Column(scale=5):
                likes_check = gr.CheckboxGroup(
                    label="✅ Gosto",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_like_input = gr.Textbox(
                        placeholder="Ex: salmão, frango, bróculos…",
                        show_label=False,
                        scale=5,
                    )
                    add_like_btn = gr.Button("➕", variant="primary", scale=1, min_width=56)
                remove_likes_btn = gr.Button("🗑️ Remover selecionados", variant="stop", size="sm")

            # ── Setas de transferência ───────────────────
            with gr.Column(scale=1, min_width=90):
                gr.HTML("<div style='height:120px'></div>")
                move_to_dislikes_btn = gr.Button("→", variant="secondary", size="lg")
                gr.HTML("<div style='height:8px'></div>")
                move_to_likes_btn = gr.Button("←", variant="secondary", size="lg")

            # ── Lista NÃO GOSTO ──────────────────────────
            with gr.Column(scale=5):
                dislikes_check = gr.CheckboxGroup(
                    label="❌ Não Gosto",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_dislike_input = gr.Textbox(
                        placeholder="Ex: beterraba, fígado…",
                        show_label=False,
                        scale=5,
                    )
                    add_dislike_btn = gr.Button("➕", variant="stop", scale=1, min_width=56)
                remove_dislikes_btn = gr.Button("🗑️ Remover selecionados", variant="stop", size="sm")

        food_status = gr.Markdown()

    with gr.Accordion("🚫 Alergias e Restrições", open=False):
        with gr.Row():
            with gr.Column():
                allergies_check = gr.CheckboxGroup(
                    label="🚫 Alergias",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_allergy_input = gr.Textbox(
                        placeholder="Ex: lactose, amendoim…",
                        show_label=False,
                        scale=5,
                    )
                    add_allergy_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                remove_allergies_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

            with gr.Column():
                restrictions_check = gr.CheckboxGroup(
                    label="⚠️ Restrições",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_restriction_input = gr.Textbox(
                        placeholder="Ex: vegetariano, low-carb…",
                        show_label=False,
                        scale=5,
                    )
                    add_restriction_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                remove_restrictions_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

            with gr.Column():
                health_check = gr.CheckboxGroup(
                    label="🏥 Dados de Saúde",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_health_input = gr.Textbox(
                        placeholder="Ex: diabetes, hipertensão…",
                        show_label=False,
                        scale=5,
                    )
                    add_health_btn = gr.Button("➕", variant="primary", scale=1, min_width=60)
                remove_health_btn = gr.Button("🗑️ Remover selecionados", variant="stop")

        restrictions_status = gr.Markdown()

    return SimpleNamespace(
        load_prefs_btn=load_prefs_btn,
        apply_seed_btn=apply_seed_btn,
        prefs_status=prefs_status,
        likes_check=likes_check,
        new_like_input=new_like_input,
        add_like_btn=add_like_btn,
        remove_likes_btn=remove_likes_btn,
        move_to_dislikes_btn=move_to_dislikes_btn,
        move_to_likes_btn=move_to_likes_btn,
        dislikes_check=dislikes_check,
        new_dislike_input=new_dislike_input,
        add_dislike_btn=add_dislike_btn,
        remove_dislikes_btn=remove_dislikes_btn,
        food_status=food_status,
        allergies_check=allergies_check,
        new_allergy_input=new_allergy_input,
        add_allergy_btn=add_allergy_btn,
        remove_allergies_btn=remove_allergies_btn,
        restrictions_check=restrictions_check,
        new_restriction_input=new_restriction_input,
        add_restriction_btn=add_restriction_btn,
        remove_restrictions_btn=remove_restrictions_btn,
        health_check=health_check,
        new_health_input=new_health_input,
        add_health_btn=add_health_btn,
        remove_health_btn=remove_health_btn,
        restrictions_status=restrictions_status,
    )

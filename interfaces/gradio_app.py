"""
Health Assistant — Gradio UI
=============================
Full web interface for interacting with agents and managing all user data.

Run from the project root:
    python interfaces/gradio_app.py
    # or with auto-reload:
    gradio interfaces/gradio_app.py
"""

import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR, SQLITE_DB, SQLITE_SESSIONS
from knowledge import get_knowledge_base
from tools.profile_tools import (
    add_food_preference,
    add_health_goal,
    update_user_profile,
)

# ── Agent team (lazy init) ───────────────────────────────
_team = None
_user_sessions: dict[str, str] = {}


def _get_team():
    global _team
    if _team is None:
        from agents.coordinator import create_health_team
        _team = create_health_team()
    return _team


def _get_session(uid: str) -> str:
    if uid not in _user_sessions:
        _user_sessions[uid] = f"ui_{uid}"
    return _user_sessions[uid]


def _reset_session(uid: str) -> str:
    _user_sessions[uid] = f"ui_{uid}_{uuid.uuid4().hex[:6]}"
    return _user_sessions[uid]


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


def _db_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════
# USER LIST & STATUS
# ═══════════════════════════════════════════════════════

def list_users():
    """Returns the list of registered users for the dropdown."""
    try:
        conn = _db_conn(SQLITE_DB)
        rows = conn.execute(
            "SELECT user_id, name FROM user_profiles ORDER BY name, user_id"
        ).fetchall()
        conn.close()
        choices = []
        for r in rows:
            label = f"{r['name']} ({r['user_id']})" if r["name"] else str(r["user_id"])
            choices.append((label, r["user_id"]))
        return choices
    except Exception:
        return []


def check_user_status(uid: str) -> str:
    uid = uid.strip()
    if not uid:
        return ""
    try:
        conn = _db_conn(SQLITE_DB)
        row = conn.execute(
            "SELECT name FROM user_profiles WHERE user_id = ?", (uid,)
        ).fetchone()
        conn.close()
        if row:
            name = row["name"] or uid
            return f"✅ **{name}**"
        return "🆕 Utilizador novo — preenche o teu perfil!"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════
# TAB 1 — CONVERSA
# ═══════════════════════════════════════════════════════

async def chat_fn(message: str, history: list, user_id: str):
    """Sends a message to the agent team and returns the response."""
    from xai import get_tracker
    tracker = get_tracker()
    tracker.reset(message)

    user_msg = {"role": "user", "content": message}

    if not user_id.strip():
        yield history + [
            user_msg,
            {"role": "assistant", "content": "❌ Introduz um User ID primeiro."},
        ], tracker.generate_markdown(), ""
        return

    # Clear input and show user message + loading indicator immediately
    yield history + [user_msg, {"role": "assistant", "content": "⏳ A processar…"}], tracker.generate_markdown(), ""

    uid = user_id.strip()
    enriched = f"[User: User, ID: {uid}]\n{message}"
    session_id = _get_session(uid)

    try:
        team = _get_team()
        response = await team.arun(enriched, session_id=session_id, user_id=uid)
        reply = _extract_text(response)
        if not reply:
            reply = "Desculpa, não consegui processar. Tenta reformular. 🤔"
    except Exception as e:
        reply = f"❌ Erro: {str(e)[:300]}"

    yield history + [
        user_msg,
        {"role": "assistant", "content": reply},
    ], tracker.generate_markdown(), ""


def reset_chat(user_id: str):
    if user_id.strip():
        _reset_session(user_id.strip())
    return [], "Nova sessão iniciada. Conversa limpa."


# ═══════════════════════════════════════════════════════
# TAB 2 — PERFIL
# ═══════════════════════════════════════════════════════

def load_profile(user_id: str):
    uid = user_id.strip()
    if not uid:
        return ("", None, "", None, None, "", "")
    conn = _db_conn(SQLITE_DB)
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()
    if not row:
        return ("", None, "", None, None, "", "")
    return (
        row["name"] or "",
        row["age"],
        row["gender"] or "",
        row["height_cm"],
        row["weight_kg"],
        row["activity_level"] or "",
        row["goal"] or "",
    )


def save_profile(user_id, name, age, gender, height_cm, weight_kg, activity_level, goal):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID."
    try:
        update_user_profile(
            uid,
            name=name or None,
            age=int(age) if age else None,
            gender=gender or None,
            height_cm=float(height_cm) if height_cm else None,
            weight_kg=float(weight_kg) if weight_kg else None,
            activity_level=activity_level or None,
            goal=goal or None,
        )
        return "✅ Perfil guardado com sucesso!"
    except Exception as e:
        return f"❌ Erro: {e}"


def load_weight_chart(user_id: str):
    uid = user_id.strip()
    if not uid:
        return None
    conn = _db_conn(SQLITE_DB)
    rows = conn.execute(
        """SELECT recorded_at, weight_kg FROM weight_history
           WHERE user_id = ? ORDER BY recorded_at ASC LIMIT 50""",
        (uid,),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    import pandas as pd
    df = pd.DataFrame(
        [(r["recorded_at"][:10], r["weight_kg"]) for r in rows],
        columns=["Data", "Peso (kg)"],
    )
    return df


def gdpr_export_fn(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID.", gr.update(visible=False, value="")
    try:
        from tools.profile_tools import export_user_data
        data_json = export_user_data(uid)
        return "✅ Dados exportados com sucesso.", gr.update(visible=True, value=data_json)
    except Exception as e:
        return f"❌ Erro: {e}", gr.update(visible=False, value="")


def gdpr_delete_fn(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID."
    try:
        from tools.profile_tools import delete_all_user_data
        return delete_all_user_data(uid)
    except Exception as e:
        return f"❌ Erro: {e}"


def add_weight_entry(user_id: str, weight: float):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID.", None
    try:
        update_user_profile(uid, weight_kg=weight)
        return f"✅ Peso {weight} kg registado!", load_weight_chart(uid)
    except Exception as e:
        return f"❌ Erro: {e}", None


# ═══════════════════════════════════════════════════════
# TAB 3 — PREFERÊNCIAS
# ═══════════════════════════════════════════════════════

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


def load_all_prefs(uid: str):
    """Returns a gr.update for each of the 6 preference CheckboxGroups."""
    uid = uid.strip()
    return tuple(
        gr.update(choices=_load_category_list(uid, cat), value=[])
        for cat in _PREF_CATS
    )


# Food likes
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


# Food dislikes
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


# Generic category (allergies, restrictions, health_data)
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


# Goals
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


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Sessões)
# ═══════════════════════════════════════════════════════

def load_sessions(user_id_filter: str = ""):
    conn = _db_conn(SQLITE_SESSIONS)
    if user_id_filter.strip():
        rows = conn.execute(
            """SELECT session_id, session_type, team_id, user_id,
                      created_at, updated_at, runs
               FROM agno_sessions WHERE user_id = ?
               ORDER BY updated_at DESC LIMIT 100""",
            (user_id_filter.strip(),),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT session_id, session_type, team_id, user_id,
                      created_at, updated_at, runs
               FROM agno_sessions ORDER BY updated_at DESC LIMIT 100"""
        ).fetchall()
    conn.close()

    data = []
    for r in rows:
        runs = r["runs"]
        if isinstance(runs, str):
            try:
                runs = json.loads(runs)
            except Exception:
                runs = []
        run_count = len(runs) if isinstance(runs, list) else 0
        ts_updated = r["updated_at"]
        if isinstance(ts_updated, int):
            ts_updated = datetime.fromtimestamp(ts_updated / 1000).strftime("%Y-%m-%d %H:%M")
        data.append([
            r["session_id"][:20] + "…" if len(r["session_id"]) > 20 else r["session_id"],
            r["user_id"] or "",
            r["session_type"] or "",
            run_count,
            ts_updated,
        ])
    return data


def view_session_messages(session_id_partial: str):
    if not session_id_partial.strip():
        return "Seleciona uma sessão."
    conn = _db_conn(SQLITE_SESSIONS)
    row = conn.execute(
        "SELECT * FROM agno_sessions WHERE session_id LIKE ?",
        (session_id_partial.strip().replace("…", "") + "%",),
    ).fetchone()
    conn.close()

    if not row:
        return "Sessão não encontrada."

    runs = row["runs"]
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except Exception:
            return "Não foi possível ler as mensagens."

    if not runs:
        return "Sem mensagens nesta sessão."

    lines = [f"**Sessão:** {row['session_id']}\n**User:** {row['user_id']}\n\n---\n"]
    for i, run in enumerate(runs if isinstance(runs, list) else [], 1):
        user_msg = ""
        agent_msg = ""
        if run.get("messages"):
            for msg in run["messages"]:
                if msg.get("role") == "user":
                    user_msg = msg.get("content", "")
                    break
        if run.get("response"):
            resp = run["response"]
            if isinstance(resp, dict):
                agent_msg = resp.get("content") or resp.get("text") or str(resp)
            else:
                agent_msg = str(resp)

        if user_msg or agent_msg:
            lines.append(f"**[{i}] Utilizador:** {user_msg}")
            lines.append(f"**Agente:** {agent_msg[:500]}{'…' if len(agent_msg) > 500 else ''}")
            lines.append("---")

    return "\n\n".join(lines)


def delete_session_fn(session_id_partial: str):
    if not session_id_partial.strip():
        return "❌ Introduz o ID da sessão."
    conn = _db_conn(SQLITE_SESSIONS)
    result = conn.execute(
        "DELETE FROM agno_sessions WHERE session_id LIKE ?",
        (session_id_partial.strip().replace("…", "") + "%",),
    )
    deleted = result.rowcount
    conn.commit()
    conn.close()
    if deleted:
        return f"✅ {deleted} sessão(ões) eliminada(s)."
    return "❌ Sessão não encontrada."


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Logs)
# ═══════════════════════════════════════════════════════

LOG_FILE = BASE_DIR / "logs" / "health-assistant.log"


def load_logs(level_filter: str, search: str, n_lines: int):
    if not LOG_FILE.exists():
        return "Ficheiro de log não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if level_filter and level_filter != "Todos":
        lines = [line for line in lines if level_filter in line]
    if search.strip():
        lines = [line for line in lines if search.lower() in line.lower()]

    result = list(reversed(lines))[:n_lines]
    return "".join(result) or "(sem resultados)"


def log_stats_fn():
    if not LOG_FILE.exists():
        return "Ficheiro não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    counts = {k: 0 for k in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
    for line in lines:
        for k in counts:
            if k in line:
                counts[k] += 1
                break
    size_kb = LOG_FILE.stat().st_size / 1024
    return (
        f"**Total de linhas:** {len(lines)}\n"
        f"**Tamanho:** {size_kb:.1f} KB\n\n"
        + "\n".join(f"- **{k}:** {v}" for k, v in counts.items())
    )


# ═══════════════════════════════════════════════════════
# TAB 4 — ADMINISTRAÇÃO (sub-tab: Base de Conhecimento)
# ═══════════════════════════════════════════════════════

def load_knowledge(collection: str, search: str):
    kb = get_knowledge_base()
    col = kb.nutrition if collection == "Nutrição" else kb.exercises
    try:
        if search.strip():
            results = col.query(query_texts=[search.strip()], n_results=20)
            if results and results.get("ids") and results["ids"][0]:
                return [
                    [results["ids"][0][i][:16] + "…", results["documents"][0][i][:120]]
                    for i in range(len(results["ids"][0]))
                ]
            return []
        else:
            data = col.get(limit=200)
            if not data or not data.get("ids"):
                return []
            return [
                [data["ids"][i][:16] + "…", data["documents"][i][:120]]
                for i in range(len(data["ids"]))
            ]
    except Exception as e:
        return [[str(e), ""]]


def add_knowledge_fn(collection: str, text: str):
    if not text.strip():
        return "❌ Introduz o texto."
    kb = get_knowledge_base()
    if collection == "Nutrição":
        doc_id = kb.add_nutrition_info(text.strip())
    else:
        doc_id = kb.add_exercise_info(text.strip())
    return f"✅ Adicionado com o ID: {doc_id}"


def delete_knowledge_fn(collection: str, doc_id_partial: str):
    if not doc_id_partial.strip():
        return "❌ Introduz o ID."
    kb = get_knowledge_base()
    col = kb.nutrition if collection == "Nutrição" else kb.exercises
    doc_id = doc_id_partial.strip().replace("…", "")
    try:
        data = col.get()
        matches = [i for i in (data.get("ids") or []) if i.startswith(doc_id)]
        if not matches:
            return f"❌ ID '{doc_id}' não encontrado."
        col.delete(ids=matches)
        return f"✅ {len(matches)} entrada(s) eliminada(s)."
    except Exception as e:
        return f"❌ Erro: {e}"


def kb_stats_fn():
    kb = get_knowledge_base()
    return (
        f"- **Nutrição:** {kb.nutrition.count()} documentos\n"
        f"- **Exercícios:** {kb.exercises.count()} documentos\n"
        f"- **Preferências:** {kb.preferences.count()} documentos"
    )


def create_user_fn(name: str, uid: str):
    uid = uid.strip()
    name = name.strip()
    if not uid:
        return "❌ O User ID é obrigatório.", gr.update(), gr.update(), gr.update(), "", ""
    try:
        update_user_profile(uid, name=name or None)
        users = list_users()
        return (
            f"✅ '{name or uid}' criado com sucesso!",
            gr.update(choices=users, value=uid),
            uid,
            check_user_status(uid),
            "",
            "",
        )
    except Exception as e:
        return f"❌ Erro: {e}", gr.update(), gr.update(), gr.update(), "", ""


# ═══════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════

_CSS = """
/* Food preference lists — one item per line */
.vertical-list .wrap {
    flex-direction: column !important;
    gap: 2px !important;
}
.vertical-list .wrap label {
    width: 100% !important;
    padding: 5px 10px !important;
    border-radius: 6px !important;
    margin: 0 !important;
    transition: background 0.15s;
}
.vertical-list .wrap label:hover {
    background: rgba(255,255,255,0.06) !important;
}
"""

with gr.Blocks(title="Health Assistant") as demo:

    with gr.Sidebar():
        gr.Markdown("# 🌿 Health Assistant")

        _initial_users = list_users()
        _initial_uid = _initial_users[0][1] if _initial_users else ""

        user_status = gr.Markdown(check_user_status(_initial_uid))

        user_select = gr.Dropdown(
            label="👤 Utilizador",
            choices=_initial_users,
            value=_initial_uid if _initial_uid else None,
            interactive=True,
        )

        # Hidden — driven programmatically; used as input across all tabs
        global_uid = gr.Textbox(value=_initial_uid, visible=False)

        with gr.Accordion("➕ Novo Utilizador", open=False):
            new_user_name = gr.Textbox(label="Nome", placeholder="Ex: Bruno")
            new_user_id_input = gr.Textbox(label="User ID", placeholder="Ex: 29255997")
            create_user_btn = gr.Button("Criar", variant="primary")
            create_user_status = gr.Markdown()

        gr.Markdown("---")
        reset_btn = gr.Button("🗑️ Limpar Conversa", variant="secondary", size="sm")
        reset_status = gr.Markdown()

    with gr.Tabs():

        # ── TAB: CHAT ────────────────────────────────────
        with gr.Tab("💬 Conversa"):
            chatbot = gr.Chatbot(
                show_label=False,
                height=600,
                avatar_images=(None, "https://em-content.zobj.net/source/google/350/seedling_1f331.png"),
                render_markdown=True,
            )
            with gr.Group():
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Pergunta algo ao teu assistente de saúde…",
                        show_label=False,
                        scale=5,
                        lines=1,
                    )
                    send_btn = gr.Button("Enviar ↩", variant="primary", scale=1, interactive=False)

        # ── TAB: PERFIL ──────────────────────────────────
        with gr.Tab("👤 O Meu Perfil"):
            with gr.Row():
                load_profile_btn = gr.Button("📥 Carregar Perfil", variant="primary")
                save_profile_btn = gr.Button("💾 Guardar Alterações", variant="secondary")
                profile_status = gr.Markdown()

            with gr.Accordion("📝 Informação Pessoal", open=True):
                with gr.Row():
                    with gr.Column():
                        pf_name = gr.Textbox(label="Nome")
                        pf_age = gr.Number(label="Idade", precision=0)
                        pf_gender = gr.Radio(
                            choices=[("Masculino", "male"), ("Feminino", "female")],
                            label="Género",
                        )
                    with gr.Column():
                        pf_height = gr.Number(label="Altura (cm)", precision=1)
                        pf_weight = gr.Number(label="Peso actual (kg)", precision=1)
                        pf_activity = gr.Dropdown(
                            choices=[
                                ("Sedentário", "sedentary"),
                                ("Ligeiro (1-2x/semana)", "light"),
                                ("Moderado (3-5x/semana)", "moderate"),
                                ("Activo (6-7x/semana)", "active"),
                                ("Muito Activo (2x/dia)", "very_active"),
                            ],
                            label="Nível de Atividade",
                        )
                pf_goal = gr.Textbox(label="Objetivo principal", lines=2)

            with gr.Accordion("📈 Evolução de Peso", open=False):
                with gr.Row():
                    new_weight = gr.Number(label="Registar novo peso (kg)", precision=1)
                    add_weight_btn = gr.Button("Registar", variant="primary")
                    weight_status = gr.Markdown()
                weight_chart = gr.LinePlot(
                    x="Data",
                    y="Peso (kg)",
                    title="Histórico de Peso",
                    height=300,
                    show_label=False,
                )

            with gr.Accordion("🔒 Privacidade e Dados (RGPD)", open=False):
                gr.Markdown(
                    "Os teus dados são processados exclusivamente para fins de assistência "
                    "pessoal de saúde e bem-estar. Tens direito a exportar ou eliminar "
                    "todos os teus dados em qualquer momento (**RGPD Art. 20 e Art. 17**)."
                )
                with gr.Row():
                    gdpr_export_btn = gr.Button("📤 Exportar os Meus Dados", variant="secondary")
                    gdpr_delete_btn = gr.Button("🗑️ Eliminar Conta e Dados", variant="stop")
                gdpr_status = gr.Markdown()
                gdpr_export_out = gr.Code(label="Dados exportados (JSON)", language="json", visible=False)

        # ── TAB: PREFERÊNCIAS ────────────────────────────
        with gr.Tab("🥗 Preferências"):
            with gr.Row():
                load_prefs_btn = gr.Button("🔄 Carregar Preferências", variant="primary")
                apply_seed_btn = gr.Button("🌱 Aplicar Padrão", variant="secondary")
                prefs_status = gr.Markdown()

            with gr.Accordion("🥦 Alimentos — Gostos e Não Gostos", open=True):
                with gr.Row(equal_height=False):
                    # ── Lista GOSTO ──────────────────────────
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

                    # ── Setas de transferência ───────────────
                    with gr.Column(scale=1, min_width=90):
                        gr.HTML("<div style='height:120px'></div>")
                        move_to_dislikes_btn = gr.Button("→", variant="secondary", size="lg")
                        gr.HTML("<div style='height:8px'></div>")
                        move_to_likes_btn = gr.Button("←", variant="secondary", size="lg")

                    # ── Lista NÃO GOSTO ──────────────────────
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

            with gr.Accordion("🎯 Objetivos de Saúde", open=False):
                goals_check = gr.CheckboxGroup(
                    label="Objetivos",
                    choices=[],
                    interactive=True,
                    elem_classes=["vertical-list"],
                )
                with gr.Row():
                    new_goal_input = gr.Textbox(
                        placeholder="Ex: perder 5 kg, correr 5 km…",
                        show_label=False,
                        scale=5,
                    )
                    add_goal_btn = gr.Button("➕ Adicionar", variant="primary", scale=2)
                remove_goals_btn = gr.Button("🗑️ Remover selecionados", variant="stop")
                goals_status = gr.Markdown()

        # ── TAB: ADMINISTRAÇÃO ───────────────────────────
        with gr.Tab("⚙️ Administração"):
            with gr.Tabs():
                with gr.Tab("🔍 Explicabilidade"):
                    gr.Markdown("### 🧠 Explainable AI (XAI)")
                    with gr.Row():
                        xai_refresh_btn = gr.Button("🔄 Atualizar Análise XAI", variant="primary")
                        xai_clear_btn = gr.Button("🗑️ Limpar", variant="secondary")
                    xai_display = gr.Markdown("_Nenhuma análise disponível ainda._")

                with gr.Tab("📋 Sessões"):
                    with gr.Row():
                        sessions_uid_filter = gr.Textbox(label="Filtrar por User ID")
                        load_sessions_btn = gr.Button("Carregar", variant="primary")
                    sessions_table = gr.DataFrame(
                        headers=["Session ID", "User ID", "Tipo", "Mensagens", "Atualizado"],
                        datatype=["str", "str", "str", "number", "str"],
                        interactive=False,
                    )
                    with gr.Row():
                        session_id_input = gr.Textbox(label="Session ID")
                        view_session_btn = gr.Button("Ver Detalhes", variant="primary")
                        delete_session_btn = gr.Button("Eliminar", variant="stop")
                    session_detail = gr.Markdown()
                    sessions_status = gr.Markdown()

                with gr.Tab("📄 Logs"):
                    with gr.Row():
                        log_level = gr.Dropdown(
                            ["Todos", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"],
                            value="Todos",
                            label="Nível",
                        )
                        log_search = gr.Textbox(label="Pesquisar")
                        log_n = gr.Slider(50, 1000, value=200, step=50, label="Linhas")
                        load_logs_btn = gr.Button("Atualizar", variant="primary")
                    log_output = gr.Textbox(label="Logs", lines=20, interactive=False)
                    log_stats_btn = gr.Button("Estatísticas")
                    log_stats_out = gr.Markdown()

                with gr.Tab("🧠 Base de Conhecimento"):
                    with gr.Row():
                        kb_collection = gr.Radio(
                            ["Nutrição", "Exercícios"], value="Nutrição", label="Colecção"
                        )
                        kb_search = gr.Textbox(label="Pesquisa")
                        load_kb_btn = gr.Button("Carregar", variant="primary")
                    kb_table = gr.DataFrame(
                        headers=["ID", "Texto"], datatype=["str", "str"], interactive=False
                    )
                    with gr.Row():
                        new_kb_text = gr.Textbox(label="Novo Documento", lines=3)
                        add_kb_btn = gr.Button("Adicionar", variant="primary")
                    with gr.Row():
                        del_kb_id = gr.Textbox(label="ID a eliminar")
                        del_kb_btn = gr.Button("Eliminar", variant="stop")
                    kb_stats_btn = gr.Button("Estatísticas")
                    kb_stats_out = gr.Markdown()
                    kb_action_status = gr.Markdown()


    # ── EVENT HANDLERS ───────────────────────────────────

    def _load_xai():
        from xai import get_tracker
        return get_tracker().generate_markdown()

    # Convenience list — same order as _PREF_CATS
    _PREF_CHECKS = [likes_check, dislikes_check, allergies_check, goals_check, restrictions_check, health_check]

    # 1. Chat
    send_btn.click(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display, msg_input],
    )

    msg_input.submit(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display, msg_input],
    )

    msg_input.change(
        fn=lambda text: gr.update(interactive=bool(text.strip())),
        inputs=[msg_input],
        outputs=[send_btn],
    )

    reset_btn.click(reset_chat, inputs=[global_uid], outputs=[chatbot, reset_status])

    # 2. Perfil
    load_profile_btn.click(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(load_weight_chart, inputs=[global_uid], outputs=[weight_chart])

    save_profile_btn.click(
        save_profile,
        inputs=[global_uid, pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
        outputs=[profile_status],
    )

    gdpr_export_btn.click(
        gdpr_export_fn,
        inputs=[global_uid],
        outputs=[gdpr_status, gdpr_export_out],
    )
    gdpr_delete_btn.click(
        gdpr_delete_fn,
        inputs=[global_uid],
        outputs=[gdpr_status],
    )

    add_weight_btn.click(
        add_weight_entry,
        inputs=[global_uid, new_weight],
        outputs=[weight_status, weight_chart],
    )

    # 3. Preferências — load
    load_prefs_btn.click(load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS)

    apply_seed_btn.click(
        apply_seed_fn,
        inputs=[global_uid],
        outputs=[prefs_status, *_PREF_CHECKS],
    )

    # 3. Preferências — food likes
    add_like_btn.click(
        add_like_fn,
        inputs=[global_uid, new_like_input],
        outputs=[food_status, likes_check, new_like_input],
    )
    new_like_input.submit(
        add_like_fn,
        inputs=[global_uid, new_like_input],
        outputs=[food_status, likes_check, new_like_input],
    )
    remove_likes_btn.click(
        remove_likes_fn,
        inputs=[global_uid, likes_check],
        outputs=[food_status, likes_check],
    )
    move_to_dislikes_btn.click(
        move_to_dislikes_fn,
        inputs=[global_uid, likes_check],
        outputs=[food_status, likes_check, dislikes_check],
    )

    # 3. Preferências — food dislikes
    add_dislike_btn.click(
        add_dislike_fn,
        inputs=[global_uid, new_dislike_input],
        outputs=[food_status, dislikes_check, new_dislike_input],
    )
    new_dislike_input.submit(
        add_dislike_fn,
        inputs=[global_uid, new_dislike_input],
        outputs=[food_status, dislikes_check, new_dislike_input],
    )
    remove_dislikes_btn.click(
        remove_dislikes_fn,
        inputs=[global_uid, dislikes_check],
        outputs=[food_status, dislikes_check],
    )
    move_to_likes_btn.click(
        move_to_likes_fn,
        inputs=[global_uid, dislikes_check],
        outputs=[food_status, likes_check, dislikes_check],
    )

    # 3. Preferências — allergies
    add_allergy_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, new_allergy_input],
        outputs=[restrictions_status, allergies_check, new_allergy_input],
    )
    new_allergy_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, new_allergy_input],
        outputs=[restrictions_status, allergies_check, new_allergy_input],
    )
    remove_allergies_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "allergies"),
        inputs=[global_uid, allergies_check],
        outputs=[restrictions_status, allergies_check],
    )

    # 3. Preferências — restrictions
    add_restriction_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, new_restriction_input],
        outputs=[restrictions_status, restrictions_check, new_restriction_input],
    )
    new_restriction_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, new_restriction_input],
        outputs=[restrictions_status, restrictions_check, new_restriction_input],
    )
    remove_restrictions_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "restrictions"),
        inputs=[global_uid, restrictions_check],
        outputs=[restrictions_status, restrictions_check],
    )

    # 3. Preferências — health data
    add_health_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, new_health_input],
        outputs=[restrictions_status, health_check, new_health_input],
    )
    new_health_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, new_health_input],
        outputs=[restrictions_status, health_check, new_health_input],
    )
    remove_health_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "health_data"),
        inputs=[global_uid, health_check],
        outputs=[restrictions_status, health_check],
    )

    # 3. Preferências — goals
    add_goal_btn.click(
        add_goal_and_refresh,
        inputs=[global_uid, new_goal_input],
        outputs=[goals_status, goals_check, new_goal_input],
    )
    new_goal_input.submit(
        add_goal_and_refresh,
        inputs=[global_uid, new_goal_input],
        outputs=[goals_status, goals_check, new_goal_input],
    )
    remove_goals_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "goals"),
        inputs=[global_uid, goals_check],
        outputs=[goals_status, goals_check],
    )

    # 4. Admin
    xai_refresh_btn.click(_load_xai, outputs=[xai_display])
    xai_clear_btn.click(lambda: "_Análise limpa._", outputs=[xai_display])

    load_sessions_btn.click(load_sessions, inputs=[sessions_uid_filter], outputs=[sessions_table])
    view_session_btn.click(view_session_messages, inputs=[session_id_input], outputs=[session_detail])
    delete_session_btn.click(
        delete_session_fn, inputs=[session_id_input], outputs=[sessions_status]
    ).then(load_sessions, inputs=[sessions_uid_filter], outputs=[sessions_table])

    load_logs_btn.click(load_logs, inputs=[log_level, log_search, log_n], outputs=[log_output])
    log_stats_btn.click(log_stats_fn, outputs=[log_stats_out])

    load_kb_btn.click(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    add_kb_btn.click(
        add_knowledge_fn, inputs=[kb_collection, new_kb_text], outputs=[kb_action_status]
    ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    del_kb_btn.click(
        delete_knowledge_fn, inputs=[kb_collection, del_kb_id], outputs=[kb_action_status]
    ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
    kb_stats_btn.click(kb_stats_fn, outputs=[kb_stats_out])

    # 5. Sidebar — user select auto-loads everything
    user_select.change(
        fn=lambda uid: uid or "",
        inputs=[user_select],
        outputs=[global_uid],
    ).then(
        check_user_status, inputs=[global_uid], outputs=[user_status],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_weight_chart, inputs=[global_uid], outputs=[weight_chart],
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    create_user_btn.click(
        create_user_fn,
        inputs=[new_user_name, new_user_id_input],
        outputs=[create_user_status, user_select, global_uid, user_status, new_user_name, new_user_id_input],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=[pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    # Auto-load first user on page startup
    if _initial_uid:
        demo.load(
            fn=lambda: _initial_uid,
            outputs=[global_uid],
        ).then(
            load_profile,
            inputs=[global_uid],
            outputs=[pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
        ).then(
            load_weight_chart, inputs=[global_uid], outputs=[weight_chart],
        ).then(
            load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
        )

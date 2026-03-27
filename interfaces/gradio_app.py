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


# ═══════════════════════════════════════════════════════
# USER LIST
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
            label = f"{r['name']} ({r['user_id']})" if r["name"] else r["user_id"]
            choices.append((label, r["user_id"]))
        return choices
    except Exception:
        return []


# ═══════════════════════════════════════════════════════
# TAB 1 — CHAT
# ═══════════════════════════════════════════════════════

async def chat_fn(message: str, history: list, user_id: str):
    """Sends a message to the agent team and returns the response."""
    from xai import get_tracker
    tracker = get_tracker()
    tracker.reset(message)

    if not user_id.strip():
        yield history + [[message, "❌ Introduz um User ID primeiro."]], tracker.generate_markdown()
        return

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

    yield history + [[message, reply]], tracker.generate_markdown()


def reset_chat(user_id: str):
    if user_id.strip():
        _reset_session(user_id.strip())
    return [], "Nova sessão iniciada. Conversa limpa."


# ═══════════════════════════════════════════════════════
# TAB 2 — PROFILE
# ═══════════════════════════════════════════════════════

def _db_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


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


def save_profile(user_id: str, name, age, gender, height_cm, weight_kg, activity_level, goal):
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
# TAB 3 — PREFERENCES
# ═══════════════════════════════════════════════════════

def load_preferences(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "", "", "", "", "", ""
    kb = get_knowledge_base()
    sections = {
        "food_likes": [], "food_dislikes": [], "allergies": [],
        "goals": [], "restrictions": [], "health_data": [],
    }
    for cat in sections:
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": uid}, {"category": cat}]}
            )
            if data and data.get("documents"):
                sections[cat] = data["documents"]
        except Exception:
            pass
    return (
        "\n".join(sections["food_likes"]) or "(vazio)",
        "\n".join(sections["food_dislikes"]) or "(vazio)",
        "\n".join(sections["allergies"]) or "(vazio)",
        "\n".join(sections["goals"]) or "(vazio)",
        "\n".join(sections["restrictions"]) or "(vazio)",
        "\n".join(sections["health_data"]) or "(vazio)",
    )


def add_like(user_id: str, food: str):
    uid = user_id.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento."
    add_food_preference(uid, food.strip(), likes=True)
    return f"✅ Adicionado '{food}' aos gostos."


def add_dislike(user_id: str, food: str):
    uid = user_id.strip()
    if not uid or not food.strip():
        return "❌ Preenche o User ID e o alimento."
    add_food_preference(uid, food.strip(), likes=False)
    return f"✅ Adicionado '{food}' ao que não gostas."


def add_goal_fn(user_id: str, goal: str):
    uid = user_id.strip()
    if not uid or not goal.strip():
        return "❌ Preenche o User ID e o objectivo."
    add_health_goal(uid, goal.strip())
    return f"✅ Objectivo adicionado: '{goal}'"


def apply_seed_fn(user_id: str):
    uid = user_id.strip()
    if not uid:
        return "❌ Introduz um User ID."
    try:
        from knowledge.seed_data import seed_user_preferences
        seed_user_preferences(uid, force=True)
        return f"✅ Preferências padrão aplicadas ao utilizador '{uid}'."
    except Exception as e:
        return f"❌ Erro: {e}"


def add_allergy_fn(user_id: str, text: str, category: str):
    uid = user_id.strip()
    if not uid or not text.strip():
        return "❌ Preenche o User ID e o texto."
    kb = get_knowledge_base()
    kb.add_preference(uid, category, text.strip(), {"created": datetime.now().isoformat()})
    return f"✅ Adicionado em '{category}': '{text}'"


def remove_preference_fn(user_id: str, food_name: str):
    uid = user_id.strip()
    if not uid or not food_name.strip():
        return "❌ Preenche o User ID e o nome."
    kb = get_knowledge_base()
    deleted = []
    for cat in ("food_likes", "food_dislikes", "allergies", "goals", "restrictions", "health_data"):
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": uid}, {"category": cat}]}
            )
            if data and data.get("ids"):
                for i, doc in enumerate(data["documents"]):
                    if food_name.lower() in doc.lower():
                        kb.preferences.delete(ids=[data["ids"][i]])
                        deleted.append(f"'{doc}' ({cat})")
        except Exception:
            pass
    if deleted:
        return "✅ Removido: " + ", ".join(deleted)
    return f"❌ Nada encontrado com '{food_name}'"


# ═══════════════════════════════════════════════════════
# TAB 4 — SESSIONS
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
        return "Selecciona uma sessão."
    conn = _db_conn(SQLITE_SESSIONS)
    # Search by prefix
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
# TAB 5 — LOGS
# ═══════════════════════════════════════════════════════

LOG_FILE = BASE_DIR / "logs" / "health-assistant.log"


def load_logs(level_filter: str, search: str, n_lines: int):
    if not LOG_FILE.exists():
        return "Ficheiro de log não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if level_filter and level_filter != "Todos":
        lines = [l for l in lines if level_filter in l]
    if search.strip():
        lines = [l for l in lines if search.lower() in l.lower()]

    result = list(reversed(lines))[:n_lines]
    return "".join(result) or "(sem resultados)"


def log_stats_fn():
    if not LOG_FILE.exists():
        return "Ficheiro não encontrado."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    counts = {k: 0 for k in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
    for l in lines:
        for k in counts:
            if k in l:
                counts[k] += 1
                break
    size_kb = LOG_FILE.stat().st_size / 1024
    return (
        f"**Total de linhas:** {len(lines)}\n"
        f"**Tamanho:** {size_kb:.1f} KB\n\n"
        + "\n".join(f"- **{k}:** {v}" for k, v in counts.items())
    )


# ═══════════════════════════════════════════════════════
# TAB 6 — KNOWLEDGE BASE
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
    return f"✅ Adicionado com ID: {doc_id}"


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


# ═══════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════

with gr.Blocks(title="Health Assistant") as demo:

    gr.Markdown(
        "# 🌿 Health Assistant\n"
        "Assistente de saúde com IA — Nutricionista · Personal Trainer · Chef"
    )

    # ── User ID global ───────────────────────────────────
    with gr.Row():
        global_uid = gr.Textbox(
            label="User ID",
            placeholder="O teu Telegram ID ou outro identificador…",
            scale=3,
        )

    with gr.Row():
        _initial_users = list_users()
        user_select = gr.Dropdown(
            label="👤 Seleccionar utilizador existente",
            choices=_initial_users,
            value=None,
            interactive=True,
            scale=3,
        )
        refresh_users_btn = gr.Button("🔄 Actualizar lista", variant="secondary", scale=1)

    gr.Markdown(
        "ℹ️ O **User ID** é partilhado entre todos os tabs. "
        "Usa o teu Telegram user ID para ver dados existentes."
    )

    with gr.Tabs():

        # ── TAB: CHAT ────────────────────────────────────
        with gr.Tab("💬 Chat"):
            chatbot = gr.Chatbot(
                label="Health Assistant",
                height=500,
                avatar_images=(None, "https://em-content.zobj.net/source/google/350/seedling_1f331.png"),
                render_markdown=True,
            )
            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="Pergunta algo ao teu assistente de saúde…",
                    label="Mensagem",
                    scale=5,
                    lines=1,
                )
                send_btn = gr.Button("Enviar", variant="primary", scale=1)

            with gr.Row():
                reset_btn = gr.Button("🔄 Nova Sessão", variant="secondary", scale=1)
                reset_status = gr.Markdown()

            # (event handlers registados após todas as tabs — ver fim do ficheiro)

        # ── TAB: EXPLICABILIDADE XAI ─────────────────────
        with gr.Tab("🔍 Explicabilidade"):
            gr.Markdown(
                "## 🧠 Explainable AI (XAI)\n"
                "Transparência automática de cada resposta: qual especialista foi activado, "
                "que ferramentas foram chamadas, que fontes RAG foram consultadas "
                "e quais as fórmulas matemáticas utilizadas.\n\n"
                "**Como usar:** Envia uma mensagem no tab 💬 Chat e depois clica em "
                "**🔄 Actualizar Análise** para ver a explicação completa."
            )
            with gr.Row():
                xai_refresh_btn = gr.Button("🔄 Actualizar Análise XAI", variant="primary", scale=2)
                xai_clear_btn   = gr.Button("🗑️ Limpar", variant="secondary", scale=1)

            xai_display = gr.Markdown(
                value=(
                    "_Nenhuma análise disponível ainda._\n\n"
                    "Envia uma mensagem no tab **💬 Chat** e depois clica em "
                    "**🔄 Actualizar Análise** para ver a explicação."
                )
            )

            def _load_xai():
                from xai import get_tracker
                return get_tracker().generate_markdown()

            def _clear_xai():
                return "_Análise limpa. Envia uma nova mensagem no Chat._"

            xai_refresh_btn.click(_load_xai, outputs=[xai_display])
            xai_clear_btn.click(_clear_xai, outputs=[xai_display])

        # ── TAB: PERFIL ──────────────────────────────────
        with gr.Tab("👤 Perfil"):
            with gr.Row():
                load_profile_btn = gr.Button("Carregar Perfil", variant="primary")
                save_profile_btn = gr.Button("Guardar Alterações", variant="secondary")
                profile_status = gr.Markdown()

            with gr.Row():
                with gr.Column():
                    pf_name = gr.Textbox(label="Nome")
                    pf_age = gr.Number(label="Idade", precision=0)
                    pf_gender = gr.Radio(
                        ["male", "female"],
                        label="Género",
                        info="male = Masculino · female = Feminino",
                    )
                    pf_activity = gr.Dropdown(
                        ["sedentary", "light", "moderate", "active", "very_active"],
                        label="Nível de Actividade",
                    )
                with gr.Column():
                    pf_height = gr.Number(label="Altura (cm)", precision=1)
                    pf_weight = gr.Number(label="Peso actual (kg)", precision=1)
                    pf_goal = gr.Textbox(label="Objectivo principal", lines=3)

            gr.Markdown("### Histórico de Peso")
            with gr.Row():
                new_weight = gr.Number(label="Registar novo peso (kg)", precision=1)
                add_weight_btn = gr.Button("Registar", variant="primary")
                weight_status = gr.Markdown()

            weight_chart = gr.LinePlot(
                x="Data",
                y="Peso (kg)",
                title="Evolução do Peso",
                height=300,
                show_label=False,
            )

            load_profile_btn.click(
                load_profile,
                inputs=[global_uid],
                outputs=[pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
            ).then(
                load_weight_chart,
                inputs=[global_uid],
                outputs=[weight_chart],
            )

            save_profile_btn.click(
                save_profile,
                inputs=[global_uid, pf_name, pf_age, pf_gender, pf_height, pf_weight, pf_activity, pf_goal],
                outputs=[profile_status],
            )

            add_weight_btn.click(
                add_weight_entry,
                inputs=[global_uid, new_weight],
                outputs=[weight_status, weight_chart],
            )

        # ── TAB: PREFERÊNCIAS ────────────────────────────
        with gr.Tab("🍽️ Preferências"):
            with gr.Row():
                load_prefs_btn = gr.Button("Carregar Preferências", variant="primary")
                pref_status = gr.Markdown()

            with gr.Row():
                pf_likes = gr.Textbox(label="Alimentos que GOSTA", lines=5, interactive=False)
                pf_dislikes = gr.Textbox(label="Alimentos que NÃO GOSTA", lines=5, interactive=False)

            with gr.Row():
                pf_allergies = gr.Textbox(label="Alergias", lines=3, interactive=False)
                pf_goals_disp = gr.Textbox(label="Objectivos", lines=3, interactive=False)

            with gr.Row():
                pf_restrictions = gr.Textbox(label="Restrições", lines=3, interactive=False)
                pf_health = gr.Textbox(label="Dados de Saúde", lines=3, interactive=False)

            with gr.Row():
                apply_seed_btn = gr.Button("🌱 Aplicar Preferências Padrão", variant="secondary")
                seed_status = gr.Markdown()

            gr.Markdown("### Adicionar / Remover")
            with gr.Row():
                with gr.Column():
                    new_like = gr.Textbox(label="Adicionar alimento que gosta", placeholder="Ex: salmão")
                    add_like_btn = gr.Button("+ Gosto", variant="primary")
                with gr.Column():
                    new_dislike = gr.Textbox(label="Adicionar alimento que não gosta", placeholder="Ex: beterraba")
                    add_dislike_btn = gr.Button("+ Não Gosto", variant="stop")
                with gr.Column():
                    new_goal_inp = gr.Textbox(label="Novo objectivo", placeholder="Ex: perder 5kg em 3 meses")
                    add_goal_btn = gr.Button("+ Objectivo", variant="secondary")

            with gr.Row():
                with gr.Column():
                    new_category_text = gr.Textbox(label="Texto (alergia / restrição / saúde)", placeholder="Ex: intolerância à lactose")
                    new_category_type = gr.Dropdown(
                        ["allergies", "restrictions", "health_data"],
                        label="Categoria",
                        value="allergies",
                    )
                    add_category_btn = gr.Button("+ Adicionar", variant="secondary")
                with gr.Column():
                    remove_text = gr.Textbox(label="Remover por nome (qualquer categoria)", placeholder="Ex: beterraba")
                    remove_btn = gr.Button("Remover", variant="stop")

            apply_seed_btn.click(apply_seed_fn, inputs=[global_uid], outputs=[seed_status])

            load_prefs_btn.click(
                load_preferences,
                inputs=[global_uid],
                outputs=[pf_likes, pf_dislikes, pf_allergies, pf_goals_disp, pf_restrictions, pf_health],
            )
            add_like_btn.click(add_like, inputs=[global_uid, new_like], outputs=[pref_status])
            add_dislike_btn.click(add_dislike, inputs=[global_uid, new_dislike], outputs=[pref_status])
            add_goal_btn.click(add_goal_fn, inputs=[global_uid, new_goal_inp], outputs=[pref_status])
            add_category_btn.click(
                add_allergy_fn,
                inputs=[global_uid, new_category_text, new_category_type],
                outputs=[pref_status],
            )
            remove_btn.click(remove_preference_fn, inputs=[global_uid, remove_text], outputs=[pref_status])

        # ── TAB: SESSÕES ─────────────────────────────────
        with gr.Tab("📋 Sessões"):
            with gr.Row():
                sessions_uid_filter = gr.Textbox(
                    label="Filtrar por User ID (opcional)",
                    placeholder="Deixa vazio para ver todas",
                )
                load_sessions_btn = gr.Button("Carregar", variant="primary")
                sessions_status = gr.Markdown()

            sessions_table = gr.DataFrame(
                headers=["Session ID", "User ID", "Tipo", "Mensagens", "Actualizado"],
                datatype=["str", "str", "str", "number", "str"],
                label="Sessões",
                interactive=False,
                row_count=(10, "dynamic"),
            )

            gr.Markdown("### Detalhes da Sessão")
            with gr.Row():
                session_id_input = gr.Textbox(
                    label="Session ID (copia da tabela acima)",
                    placeholder="Cole aqui o Session ID…",
                )
                view_session_btn = gr.Button("Ver Mensagens", variant="primary")
                delete_session_btn = gr.Button("Eliminar Sessão", variant="stop")

            session_detail = gr.Markdown()

            load_sessions_btn.click(
                load_sessions,
                inputs=[sessions_uid_filter],
                outputs=[sessions_table],
            )
            view_session_btn.click(
                view_session_messages,
                inputs=[session_id_input],
                outputs=[session_detail],
            )
            delete_session_btn.click(
                delete_session_fn,
                inputs=[session_id_input],
                outputs=[sessions_status],
            ).then(load_sessions, inputs=[sessions_uid_filter], outputs=[sessions_table])

        # ── TAB: LOGS ────────────────────────────────────
        with gr.Tab("📄 Logs"):
            with gr.Row():
                log_level = gr.Dropdown(
                    ["Todos", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"],
                    value="Todos",
                    label="Nível",
                )
                log_search = gr.Textbox(label="Pesquisar", placeholder="Texto a filtrar…")
                log_n = gr.Slider(50, 1000, value=200, step=50, label="Máx. linhas")
                load_logs_btn = gr.Button("Actualizar", variant="primary")

            with gr.Row():
                log_stats_btn = gr.Button("Ver Estatísticas")
                log_stats_out = gr.Markdown()

            log_output = gr.Textbox(
                label="Logs (mais recentes primeiro)",
                lines=30,
                interactive=False,
            )

            load_logs_btn.click(
                load_logs,
                inputs=[log_level, log_search, log_n],
                outputs=[log_output],
            )
            log_stats_btn.click(log_stats_fn, outputs=[log_stats_out])

        # ── TAB: CONHECIMENTO ────────────────────────────
        with gr.Tab("🧠 Base de Conhecimento"):
            with gr.Row():
                kb_collection = gr.Radio(
                    ["Nutrição", "Exercícios"],
                    value="Nutrição",
                    label="Colecção",
                )
                kb_search = gr.Textbox(label="Pesquisa semântica", placeholder="Ex: proteína, HIIT, calorias…")
                load_kb_btn = gr.Button("Carregar / Pesquisar", variant="primary")

            kb_stats_out = gr.Markdown()
            kb_stats_btn = gr.Button("Ver estatísticas")

            kb_table = gr.DataFrame(
                headers=["ID", "Texto"],
                datatype=["str", "str"],
                label="Documentos",
                interactive=False,
                row_count=(10, "dynamic"),
                wrap=True,
            )

            gr.Markdown("### Gerir Documentos")
            with gr.Row():
                with gr.Column():
                    new_kb_text = gr.Textbox(label="Novo documento", lines=4)
                    add_kb_btn = gr.Button("Adicionar", variant="primary")
                with gr.Column():
                    del_kb_id = gr.Textbox(label="ID a eliminar (prefixo)", placeholder="Ex: nutrition_12345…")
                    del_kb_btn = gr.Button("Eliminar", variant="stop")
            kb_action_status = gr.Markdown()

            load_kb_btn.click(
                load_knowledge,
                inputs=[kb_collection, kb_search],
                outputs=[kb_table],
            )
            kb_stats_btn.click(kb_stats_fn, outputs=[kb_stats_out])
            add_kb_btn.click(
                add_knowledge_fn,
                inputs=[kb_collection, new_kb_text],
                outputs=[kb_action_status],
            ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])
            del_kb_btn.click(
                delete_knowledge_fn,
                inputs=[kb_collection, del_kb_id],
                outputs=[kb_action_status],
            ).then(load_knowledge, inputs=[kb_collection, kb_search], outputs=[kb_table])


    # ── Chat event handlers ──────────────────────────────
    # Definidos aqui (fora do bloco de tabs) para poder referenciar
    # xai_display (definido na tab Explicabilidade) como output adicional.
    send_btn.click(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display],
    ).then(lambda: "", outputs=[msg_input])

    msg_input.submit(
        chat_fn,
        inputs=[msg_input, chatbot, global_uid],
        outputs=[chatbot, xai_display],
    ).then(lambda: "", outputs=[msg_input])

    reset_btn.click(reset_chat, inputs=[global_uid], outputs=[chatbot, reset_status])

    # ── User selection ───────────────────────────────────
    user_select.change(
        fn=lambda uid: uid if uid else gr.update(),
        inputs=[user_select],
        outputs=[global_uid],
    )
    def _refresh_users():
        return gr.update(choices=list_users(), value=None)

    refresh_users_btn.click(
        fn=_refresh_users,
        outputs=[user_select],
    )


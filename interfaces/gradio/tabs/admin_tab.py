"""
Tab: ⚙️ Administração

Business logic and UI builder for the administration tab.
Sub-tabs: Explicabilidade (XAI), Sessões, Logs, Base de Conhecimento.
Also contains create_user_fn used by the sidebar.
"""

import json
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

from config import BASE_DIR, SQLITE_SESSIONS
from shared import _db_conn, list_users, check_user_status
from knowledge import get_knowledge_base
from tools.profile_tools import update_user_profile

LOG_FILE = BASE_DIR / "logs" / "health-assistant.log"


# ── Sessions ─────────────────────────────────────────────

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
            ts_updated = datetime.fromtimestamp(ts_updated).strftime("%Y-%m-%d %H:%M")
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


# ── Logs ─────────────────────────────────────────────────

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


# ── Knowledge base ────────────────────────────────────────

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


# ── User creation (used by sidebar) ──────────────────────

def create_user_fn(name: str, uid: str):
    uid = uid.strip()
    name = name.strip()
    if not uid:
        return "❌ O ID da Conta é obrigatório.", gr.update(), gr.update(), gr.update(), "", ""
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


# ── UI builder ───────────────────────────────────────────

def build_admin_tab() -> SimpleNamespace:
    """Create the admin tab UI. Must be called inside a gr.Blocks() context."""
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

    return SimpleNamespace(
        xai_refresh_btn=xai_refresh_btn,
        xai_clear_btn=xai_clear_btn,
        xai_display=xai_display,
        sessions_uid_filter=sessions_uid_filter,
        load_sessions_btn=load_sessions_btn,
        sessions_table=sessions_table,
        session_id_input=session_id_input,
        view_session_btn=view_session_btn,
        delete_session_btn=delete_session_btn,
        session_detail=session_detail,
        sessions_status=sessions_status,
        log_level=log_level,
        log_search=log_search,
        log_n=log_n,
        load_logs_btn=load_logs_btn,
        log_output=log_output,
        log_stats_btn=log_stats_btn,
        log_stats_out=log_stats_out,
        kb_collection=kb_collection,
        kb_search=kb_search,
        load_kb_btn=load_kb_btn,
        kb_table=kb_table,
        new_kb_text=new_kb_text,
        add_kb_btn=add_kb_btn,
        del_kb_id=del_kb_id,
        del_kb_btn=del_kb_btn,
        kb_stats_btn=kb_stats_btn,
        kb_stats_out=kb_stats_out,
        kb_action_status=kb_action_status,
    )

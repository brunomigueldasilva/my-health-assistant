"""
Tab: 💬 Conversa

Business logic and UI builder for the chat tab.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import gradio as gr

# Path setup — project root and interfaces/ must be on sys.path
_root = Path(__file__).resolve().parent.parent.parent.parent
_iface = Path(__file__).resolve().parent.parent
for _p in (_root, _iface):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared import _get_team, _get_session, _sanitize_reply, _extract_text


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
    today = datetime.now().strftime("%d/%m/%Y")
    enriched = f"[Data de hoje: {today}] [ID do utilizador: {uid}]\n{message}"
    session_id = _get_session(uid)

    try:
        team = _get_team()
        response = await team.arun(enriched, session_id=session_id, user_id=uid)
        reply = _extract_text(response)
        if not reply:
            reply = "Desculpa, não consegui processar. Tenta reformular. 🤔"
        else:
            reply = _sanitize_reply(reply)
    except Exception as e:
        reply = _sanitize_reply(str(e))

    yield history + [
        user_msg,
        {"role": "assistant", "content": reply},
    ], tracker.generate_markdown(), ""


def reset_chat(user_id: str):
    from shared import _reset_session
    if user_id.strip():
        _reset_session(user_id.strip())
    return [], "Nova sessão iniciada. Conversa limpa."


def build_chat_tab() -> SimpleNamespace:
    """Create the chat tab UI. Must be called inside a gr.Blocks() context."""
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

    return SimpleNamespace(chatbot=chatbot, msg_input=msg_input, send_btn=send_btn)

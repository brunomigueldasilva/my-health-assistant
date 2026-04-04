"""
Tab: 🚀 Onboarding
Step-by-step new-user creation wizard.

Flow:
  Step 1 — Create account  (name required; optional custom ID, otherwise auto-generated)
  Step 2 — Personal data   (gender, birth date, height, weight)
  Step 3 — Activity level
  Step 4 — Goals           (multi-select, up to 3)
  Step 5 — Allergies & intolerances
  Done   — Summary + success message

The tab is only shown when no user is currently selected (controlled by app.py).
It does NOT depend on the sidebar's global_uid — it manages its own onb_uid state
and exposes the final UID so app.py can update global_uid after completion.
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from tools.profile_tools import add_allergy, add_health_goal, update_user_profile

import gradio as gr

_root = Path(__file__).resolve().parent.parent.parent.parent
_iface = Path(__file__).resolve().parent.parent
for _p in (_root, _iface):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ── Constants (mirrored from telegram_bot.py) ─────────────────────────────

ACTIVITY_OPTIONS = [
    ("sedentary",   "🛋️ Sedentário"),
    ("light",       "🚶 Ligeiro (1-2x/semana)"),
    ("moderate",    "🏃 Moderado (3-5x/semana)"),
    ("active",      "💪 Activo (6-7x/semana)"),
    ("very_active", "🔥 Muito Activo (2x/dia)"),
]
ACTIVITY_LABEL = {k: v for k, v in ACTIVITY_OPTIONS}

GOAL_OPTIONS = [
    ("lose_weight",         "⬇️ Perder peso"),
    ("gain_muscle",         "💪 Ganhar massa muscular"),
    ("lose_fat",            "🔥 Perder massa gorda"),
    ("lose_visceral",       "🫀 Perder gordura visceral"),
    ("maintain",            "⚖️ Manter peso actual"),
    ("improve_fitness",     "🏃 Melhorar condição física"),
    ("improve_health",      "❤️ Melhorar saúde em geral"),
    ("better_diet",         "🍽️ Melhores hábitos alimentares"),
    ("target_weight",       "🎯 Atingir peso específico"),
    ("target_muscle",       "💪 Atingir massa muscular específica"),
    ("target_body_fat",     "📊 Atingir gordura corporal específica"),
    ("target_visceral_fat", "🔬 Atingir gordura visceral específica"),
    ("define_abs",          "💎 Definir os abdominais"),
]
ACTIVITY_LABEL = {k: v for k, v in ACTIVITY_OPTIONS}
GOAL_LABEL     = {k: v for k, v in GOAL_OPTIONS}
GOAL_CHOICES   = [v for _, v in GOAL_OPTIONS]   # stored as label strings (matches Telegram)
MAX_GOALS      = 3

ALLERGY_OPTIONS = ["Glúten", "Lactose", "Frutos secos", "Marisco", "Ovos", "Amendoins"]


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_birth_date(bd: str) -> str | None:
    if not bd or not str(bd).strip():
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(bd).strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── UI Builder ────────────────────────────────────────────────────────────

def build_onboarding_tab() -> SimpleNamespace:
    """Builds the new-user onboarding wizard.
    Returns a namespace with all components needed for event wiring in app.py."""
    ns = SimpleNamespace()

    # Internal state — the UID of the user being created in this wizard session.
    # Populated after Step 1; used in onb_finish to save all data.
    ns.onb_uid = gr.State(value="")

    with gr.Column():

        # ── Step 1: Create Account ───────────────────────────────────────
        with gr.Group(visible=True) as ns.step1_group:
            gr.Markdown(
                "## 🚀 Criar Conta\n\n"
                "Preenche o teu nome para começar. "
                "O perfil completo é configurado a seguir, passo a passo."
            )
            ns.new_name = gr.Textbox(
                label="Nome",
                placeholder="Ex: Bruno",
                info="Obrigatório",
            )
            with gr.Accordion("⚙️ ID personalizado (avançado)", open=False):
                ns.new_uid_input = gr.Textbox(
                    label="ID da conta",
                    placeholder="Deixa em branco para gerar automaticamente",
                    info="Usa apenas letras, números e _. Ex: bruno_2025",
                )
            ns.step1_error = gr.Markdown("", visible=False)
            ns.create_btn = gr.Button("Criar e continuar ➡️", variant="primary", size="lg")
            ns.create_loading = gr.Markdown("⏳ A iniciar... aguarda um momento.", visible=False)

        # ── Step 2: Personal Data ────────────────────────────────────────
        with gr.Group(visible=False) as ns.step2_group:
            gr.Markdown("### 👤 Passo 1 de 4 — Dados Pessoais")
            ns.gender = gr.Radio(
                label="Género",
                choices=[
                    ("👨 Masculino", "male"),
                    ("👩 Feminino",  "female"),
                    ("🧑 Outro / Prefiro não dizer", "other"),
                ],
                value=None,
            )
            ns.birth_date = gr.Textbox(
                label="Data de Nascimento",
                placeholder="DD/MM/AAAA  ou  AAAA-MM-DD",
                info="Opcional — usada para calcular a tua idade e necessidades calóricas",
            )
            with gr.Row():
                ns.height = gr.Number(
                    label="Altura (cm)",
                    precision=0,
                    minimum=50,
                    maximum=250,
                    value=None,
                    info="Opcional",
                )
                ns.weight = gr.Number(
                    label="Peso (kg)",
                    precision=1,
                    minimum=20,
                    maximum=400,
                    value=None,
                    info="Obrigatório",
                )
            ns.step2_error = gr.Markdown("", visible=False)
            ns.step2_next = gr.Button("Próximo ➡️", variant="primary")

        # ── Step 3: Activity Level ───────────────────────────────────────
        with gr.Group(visible=False) as ns.step3_group:
            gr.Markdown("### 🏃 Passo 2 de 4 — Nível de Actividade")
            ns.activity = gr.Radio(
                label="Qual é o teu nível de actividade física actual?",
                choices=[(label, key) for key, label in ACTIVITY_OPTIONS],
                value=None,
            )
            with gr.Row():
                ns.step3_back = gr.Button("⬅️ Anterior", variant="secondary")
                ns.step3_next = gr.Button("Próximo ➡️", variant="primary")

        # ── Step 4: Goals ────────────────────────────────────────────────
        with gr.Group(visible=False) as ns.step4_group:
            gr.Markdown(
                f"### 🎯 Passo 3 de 4 — Objectivos de Saúde\n\n"
                f"Selecciona até **{MAX_GOALS}** objectivos."
            )
            ns.goals = gr.CheckboxGroup(
                label="Objectivos",
                choices=GOAL_CHOICES,
                value=[],
            )
            # Target value inputs — shown dynamically when a target goal is selected
            with gr.Group(visible=False) as ns.target_weight_group:
                ns.target_weight_val = gr.Number(
                    label="🎯 Peso alvo (kg)",
                    placeholder="ex: 75",
                    precision=1, minimum=30, maximum=300, value=None,
                )
            with gr.Group(visible=False) as ns.target_muscle_group:
                ns.target_muscle_val = gr.Number(
                    label="💪 Massa muscular alvo (kg)",
                    placeholder="ex: 65",
                    precision=1, minimum=10, maximum=120, value=None,
                )
            with gr.Group(visible=False) as ns.target_body_fat_group:
                ns.target_body_fat_val = gr.Number(
                    label="📊 % gordura corporal alvo",
                    placeholder="ex: 15",
                    precision=1, minimum=1, maximum=60, value=None,
                )
            with gr.Group(visible=False) as ns.target_visceral_group:
                ns.target_visceral_val = gr.Number(
                    label="🔬 Nível de gordura visceral alvo",
                    placeholder="ex: 6",
                    precision=1, minimum=1, maximum=30, value=None,
                )
            ns.step4_error = gr.Markdown("", visible=False)
            with gr.Row():
                ns.step4_back = gr.Button("⬅️ Anterior", variant="secondary")
                ns.step4_next = gr.Button("Próximo ➡️", variant="primary")

        # ── Step 5: Allergies ────────────────────────────────────────────
        with gr.Group(visible=False) as ns.step5_group:
            gr.Markdown("### ⚠️ Passo 4 de 4 — Alergias e Intolerâncias")
            ns.allergies = gr.CheckboxGroup(
                label="Alergias / Intolerâncias",
                choices=ALLERGY_OPTIONS,
                value=[],
                info="Podes sempre editar na tab Nutrição",
            )
            ns.step5_error = gr.Markdown("", visible=False)
            with gr.Row():
                ns.step5_back = gr.Button("⬅️ Anterior", variant="secondary")
                ns.finish_btn = gr.Button("✅ Concluir", variant="primary")

        # ── Done / Summary ───────────────────────────────────────────────
        with gr.Group(visible=False) as ns.step6_group:
            ns.done_md = gr.Markdown("")
            with gr.Row():
                ns.restart_btn = gr.Button("✏️ Recomeçar Onboarding", variant="secondary")
                ns.go_to_chat_btn = gr.Button("✅ Concluir", variant="primary")

    return ns


# ── Step logic ────────────────────────────────────────────────────────────

def onb_create_user(name: str, custom_uid: str):
    """Create the user record and advance to the personal data step.

    Returns: (step1_error, step1_group, step2_group, onb_uid, create_loading)
    """
    name = (name or "").strip()
    if not name:
        return (
            gr.update(visible=True, value="❌ O nome é obrigatório para criar a conta."),
            gr.update(visible=True),   # stay on step1
            gr.update(visible=False),
            "",
            gr.update(visible=False),  # hide loading
        )

    uid = (custom_uid or "").strip() or f"web_{uuid.uuid4().hex[:8]}"

    try:
        update_user_profile(uid, name=name)
    except Exception as exc:
        return (
            gr.update(visible=True, value=f"❌ Erro ao criar conta: {exc}"),
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            gr.update(visible=False),  # hide loading
        )

    return (
        gr.update(visible=False),  # hide error
        gr.update(visible=False),  # hide step1
        gr.update(visible=True),   # show step2
        uid,                       # store new uid in onb_uid state
        gr.update(visible=False),  # hide loading
    )


def onb_step2_next(weight):
    if not weight:
        return (
            gr.update(visible=True, value="❌ O peso é obrigatório para continuar."),
            gr.update(visible=True),
            gr.update(visible=False),
        )
    return (
        gr.update(visible=False),
        gr.update(visible=False),  # hide step2
        gr.update(visible=True),   # show step3
    )


def onb_step3_back():
    return (
        gr.update(visible=False),  # hide step3
        gr.update(visible=True),   # show step2
    )


def onb_step3_next():
    return (
        gr.update(visible=False),  # hide step3
        gr.update(visible=True),   # show step4
    )


def onb_step4_back():
    return (
        gr.update(visible=False),  # hide step4
        gr.update(visible=True),   # show step3
    )


def onb_step4_next(goals):
    if len(goals) > MAX_GOALS:
        return (
            gr.update(
                visible=True,
                value=f"❌ Selecciona no máximo **{MAX_GOALS}** objectivos "
                      f"({len(goals)} seleccionados).",
            ),
            gr.update(visible=True),
            gr.update(visible=False),
        )
    return (
        gr.update(visible=False),
        gr.update(visible=False),  # hide step4
        gr.update(visible=True),   # show step5
    )


def onb_step5_back():
    return (
        gr.update(visible=False),  # hide step5
        gr.update(visible=True),   # show step4
    )


def onb_finish(onb_uid, gender, birth_date_str, height, weight, activity, goals, allergies,
               target_weight_val, target_muscle_val, target_body_fat_val, target_visceral_val):
    """Save all wizard data and show the summary screen.

    Returns: (step5_error, step5_group, step6_group, done_md, onb_uid)
    The last value (onb_uid) is consumed by app.py to update global_uid.
    """
    if not onb_uid:
        return (
            gr.update(visible=True, value="❌ Sessão inválida — reinicia o onboarding."),
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            "",
        )

    birth_date_iso = _parse_birth_date(birth_date_str)

    try:
        update_user_profile(
            onb_uid,
            birth_date=birth_date_iso,
            gender=gender or None,
            height_cm=float(height) if height else None,
            weight_kg=float(weight) if weight else None,
            activity_level=activity or None,
        )
    except Exception as exc:
        return (
            gr.update(visible=True, value=f"❌ Erro ao guardar perfil: {exc}"),
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            "",
        )

    for allergy in (allergies or []):
        try:
            add_allergy(onb_uid, allergy)
        except Exception:
            pass

    # Map target goals to their formatted strings (with user-supplied values)
    _target_vals = {
        "🎯 Atingir peso específico":            (target_weight_val,    lambda v: f"Atingir {v:.1f} kg"),
        "💪 Atingir massa muscular específica":   (target_muscle_val,    lambda v: f"Atingir {v:.1f} kg de massa muscular"),
        "📊 Atingir gordura corporal específica": (target_body_fat_val,  lambda v: f"Atingir {v:.1f}% de gordura corporal"),
        "🔬 Atingir gordura visceral específica": (target_visceral_val,  lambda v: f"Atingir {v:.1f} nível de gordura visceral"),
    }

    def _goal_str(label: str) -> str:
        val, fmt = _target_vals.get(label, (None, None))
        return fmt(val) if fmt and val else label

    for goal_label in (goals or []):
        try:
            add_health_goal(onb_uid, _goal_str(goal_label))
        except Exception:
            pass

    # Build summary table
    _gender_disp = {"male": "👨 Masculino", "female": "👩 Feminino", "other": "🧑 Outro"}
    bd_display   = birth_date_str or "—"
    gender_str   = _gender_disp.get(gender, "—") if gender else "—"
    height_str   = f"{int(height)} cm" if height else "—"
    weight_str   = f"{weight:.1f} kg"  if weight else "—"
    activity_str = ACTIVITY_LABEL.get(activity, "—") if activity else "—"
    goals_str    = "\n".join(f"- {_goal_str(g)}" for g in (goals or [])) or "— (nenhum seleccionado)"
    allergy_str  = ", ".join(allergies or []) or "Nenhuma"

    done_md = (
        "## ✅ Conta criada com sucesso!\n\n"
        f"| | |\n"
        f"|---|---|\n"
        f"| **Género** | {gender_str} |\n"
        f"| **Data de Nascimento** | {bd_display} |\n"
        f"| **Altura** | {height_str} |\n"
        f"| **Peso** | {weight_str} |\n"
        f"| **Actividade** | {activity_str} |\n"
        f"| **Alergias** | {allergy_str} |\n\n"
        f"**Objectivos:**\n{goals_str}\n\n"
        "---\n"
        "O teu perfil está pronto! 🎉  \n"
        "Clica em **Concluir** para aceder ao teu perfil."
    )

    return (
        gr.update(visible=False),  # hide step5_error
        gr.update(visible=False),  # hide step5_group
        gr.update(visible=True),   # show step6_group
        done_md,
        onb_uid,                   # returned to app.py → updates global_uid
    )


def onb_restart():
    """Reset wizard back to the create-account screen."""
    return (
        gr.update(visible=False),  # hide step6
        gr.update(visible=True),   # show step1
    )


def onb_full_reset():
    """Full wizard reset — clears all fields and returns to Step 1.
    Used when the user clicks 'Criar nova conta' from the sidebar."""
    return (
        # group visibility
        gr.update(visible=True),   # step1_group
        gr.update(visible=False),  # step2_group
        gr.update(visible=False),  # step3_group
        gr.update(visible=False),  # step4_group
        gr.update(visible=False),  # step5_group
        gr.update(visible=False),  # step6_group
        # error banners
        gr.update(visible=False, value=""),  # step1_error
        gr.update(visible=False, value=""),  # step2_error
        gr.update(visible=False, value=""),  # step4_error
        gr.update(visible=False, value=""),  # step5_error
        # form fields
        gr.update(value=""),    # new_name
        gr.update(value=""),    # new_uid_input
        gr.update(value=None),  # gender
        gr.update(value=""),    # birth_date
        gr.update(value=None),  # height
        gr.update(value=None),  # weight
        gr.update(value=None),  # activity
        gr.update(value=[]),    # goals
        gr.update(value=[]),    # allergies
        # target value groups
        gr.update(visible=False),  # target_weight_group
        gr.update(visible=False),  # target_muscle_group
        gr.update(visible=False),  # target_body_fat_group
        gr.update(visible=False),  # target_visceral_group
        # loading indicator
        gr.update(visible=False),  # create_loading
        # internal state
        "",                        # onb_uid
    )

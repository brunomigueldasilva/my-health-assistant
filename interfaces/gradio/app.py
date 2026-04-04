"""
Health Assistant — Gradio UI
=============================
Full web interface for interacting with agents and managing all user data.

Run from the project root:
    python interfaces/gradio/app.py
    # or with auto-reload:
    gradio interfaces/gradio/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # project root
sys.path.insert(0, str(Path(__file__).resolve().parent))                 # interfaces/gradio/

import gradio as gr

from shared import list_users, check_user_status
from styles import CSS
from tabs.chat_tab import build_chat_tab, chat_fn, reset_chat
from tabs.profile_tab import (
    build_profile_tab,
    load_profile,
    save_profile,
    load_weight_chart,
    load_all_comp_charts,
    gdpr_export_fn,
    gdpr_delete_fn,
    add_weight_entry,
)
from tabs.goals_tab import build_goals_tab, load_full_dashboard
from tabs.nutrition_tab import (
    build_nutrition_tab,
    load_all_prefs,
    add_like_fn,
    remove_likes_fn,
    move_to_dislikes_fn,
    add_dislike_fn,
    remove_dislikes_fn,
    move_to_likes_fn,
    add_cat_item_fn,
    remove_cat_items_fn,
    add_goal_and_refresh,
    apply_seed_fn,
    _load_category_list,
)
from tabs.admin_tab import (
    build_admin_tab,
    load_sessions,
    view_session_messages,
    delete_session_fn,
    load_logs,
    log_stats_fn,
    load_knowledge,
    add_knowledge_fn,
    delete_knowledge_fn,
    kb_stats_fn,
    delete_user_fn,
)
from tabs.onboarding_tab import (
    build_onboarding_tab,
    onb_create_user,
    onb_step2_next,
    onb_step3_back,
    onb_step3_next,
    onb_step4_back,
    onb_step4_next,
    onb_step5_back,
    onb_finish,
    onb_restart,
    onb_full_reset,
)

_CSS = CSS  # exported for main.py → gradio_demo.launch(css=_CSS)


with gr.Blocks(title="Health Assistant") as demo:

    # ── Sidebar ──────────────────────────────────────────
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

        # Hidden state — driven programmatically; used as input across all tabs
        global_uid = gr.State(value=_initial_uid)
        # Mirrors profile.comp_period so timer/load chains always have a valid
        # value even when the Profile tab or its accordion is not active.
        comp_period_state = gr.State(value="Último Ano")

        new_user_btn = gr.Button("➕ Criar nova conta", variant="secondary", size="sm")
        delete_user_btn = gr.Button("🗑️ Remover Conta", variant="stop", size="sm")

        with gr.Group(visible=False) as delete_confirm_group:
            gr.Markdown("⚠️ **Tens a certeza?** Todos os dados serão apagados permanentemente.")
            with gr.Row():
                delete_confirm_btn = gr.Button("Confirmar", variant="stop", size="sm")
                delete_cancel_btn = gr.Button("Cancelar", variant="secondary", size="sm")
        delete_user_status = gr.Markdown()

        gr.Markdown("---")
        reset_btn = gr.Button("🗑️ Limpar Conversa", variant="secondary", size="sm")
        reset_status = gr.Markdown()

    # ── Tabs ─────────────────────────────────────────────
    with gr.Tabs() as main_tabs:

        with gr.Tab("🚀 Onboarding", id="onboarding") as onb_tab_ref:
            onboarding = build_onboarding_tab()

        with gr.Tab("👤 Perfil", id="profile") as profile_tab_ref:
            profile = build_profile_tab()

        with gr.Tab("🎯 Objectivo", id="goals") as goals_tab_ref:
            goals = build_goals_tab()

        with gr.Tab("🥗 Nutrição e Gostos", id="nutrition") as nutrition_tab_ref:
            nutrition = build_nutrition_tab()

        with gr.Tab("💬 Conversa", id="chat") as chat_tab_ref:
            chat = build_chat_tab()

        with gr.Tab("⚙️ Administração", id="admin"):
            admin = build_admin_tab()

    # ── Auto-refresh timer ───────────────────────────────
    refresh_timer = gr.Timer(value=30)
    _refresh_trigger = gr.State(value=0)

    # ── Convenience aliases ──────────────────────────────
    # Preference checks ordered as _PREF_CATS:
    # [food_likes, food_dislikes, allergies, goals, restrictions, health_data]
    _PREF_CHECKS = [
        nutrition.likes_check,
        nutrition.dislikes_check,
        nutrition.allergies_check,
        profile.goals_check,
        nutrition.restrictions_check,
        nutrition.health_check,
    ]

    _comp_outputs = [
        profile.chart_bmi, profile.chart_fat, profile.chart_visceral,
        profile.chart_muscle, profile.chart_water, profile.chart_bmr,
        profile.chart_metage, profile.chart_bone,
    ]

    _dash_outputs = [
        goals.dash_kpis, goals.dash_chart_fat, goals.dash_chart_visceral,
        goals.dash_chart_weight, goals.dash_chart_muscle, goals.dash_progress,
    ]

    _profile_fields = [
        profile.pf_name, profile.pf_birth_date, profile.pf_age,
        profile.pf_gender, profile.pf_height, profile.pf_weight,
        profile.pf_activity, profile.pf_goal,
    ]

    # ── EVENT HANDLERS ───────────────────────────────────

    # 0. Onboarding wizard
    def _initial_tab_state(uid):
        """Hide/show onboarding tab AND navigate to the right tab."""
        if uid and uid.strip():
            return gr.update(visible=False), gr.update(selected="profile")
        return gr.update(visible=True), gr.update(selected="onboarding")

    onboarding.create_btn.click(
        fn=lambda: gr.update(visible=True),
        outputs=[onboarding.create_loading],
    ).then(
        onb_create_user,
        inputs=[onboarding.new_name, onboarding.new_uid_input],
        outputs=[onboarding.step1_error, onboarding.step1_group, onboarding.step2_group, onboarding.onb_uid, onboarding.create_loading],
    )
    onboarding.step2_next.click(
        onb_step2_next,
        inputs=[onboarding.weight],
        outputs=[onboarding.step2_error, onboarding.step2_group, onboarding.step3_group],
    )
    onboarding.step3_back.click(
        onb_step3_back,
        outputs=[onboarding.step3_group, onboarding.step2_group],
    )
    onboarding.step3_next.click(
        onb_step3_next,
        outputs=[onboarding.step3_group, onboarding.step4_group],
    )
    onboarding.step4_back.click(
        onb_step4_back,
        outputs=[onboarding.step4_group, onboarding.step3_group],
    )
    onboarding.goals.change(
        fn=lambda selected: (
            gr.update(visible="🎯 Atingir peso específico" in selected),
            gr.update(visible="💪 Atingir massa muscular específica" in selected),
            gr.update(visible="📊 Atingir gordura corporal específica" in selected),
            gr.update(visible="🔬 Atingir gordura visceral específica" in selected),
        ),
        inputs=[onboarding.goals],
        outputs=[
            onboarding.target_weight_group,
            onboarding.target_muscle_group,
            onboarding.target_body_fat_group,
            onboarding.target_visceral_group,
        ],
    )
    onboarding.step4_next.click(
        onb_step4_next,
        inputs=[onboarding.goals],
        outputs=[onboarding.step4_error, onboarding.step4_group, onboarding.step5_group],
    )
    onboarding.step5_back.click(
        onb_step5_back,
        outputs=[onboarding.step5_group, onboarding.step4_group],
    )
    onboarding.finish_btn.click(
        onb_finish,
        inputs=[
            onboarding.onb_uid,
            onboarding.gender,
            onboarding.birth_date,
            onboarding.height,
            onboarding.weight,
            onboarding.activity,
            onboarding.goals,
            onboarding.allergies,
            onboarding.target_weight_val,
            onboarding.target_muscle_val,
            onboarding.target_body_fat_val,
            onboarding.target_visceral_val,
        ],
        outputs=[
            onboarding.step5_error,
            onboarding.step5_group,
            onboarding.step6_group,
            onboarding.done_md,
            global_uid,
        ],
    ).then(
        lambda uid: (gr.update(choices=list_users(), value=uid), check_user_status(uid)),
        inputs=[global_uid],
        outputs=[user_select, user_status],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=_profile_fields,
    ).then(
        load_all_prefs,
        inputs=[global_uid],
        outputs=_PREF_CHECKS,
    )
    onboarding.go_to_chat_btn.click(
        fn=lambda: (gr.update(visible=False), gr.update(selected="profile")),
        outputs=[onb_tab_ref, main_tabs],
    )
    onboarding.restart_btn.click(
        onb_restart,
        outputs=[onboarding.step6_group, onboarding.step1_group],
    )

    # Tab select — refresh data when switching tabs
    profile_tab_ref.select(
        load_profile, inputs=[global_uid], outputs=_profile_fields,
    ).then(
        load_weight_chart, inputs=[global_uid, profile.weight_period], outputs=[profile.weight_chart],
    )
    goals_tab_ref.select(
        load_full_dashboard, inputs=[global_uid, goals.dash_start_date], outputs=_dash_outputs,
    )
    nutrition_tab_ref.select(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    def _load_xai():
        from xai import get_tracker
        return get_tracker().generate_markdown()

    # 1. Chat
    chat.send_btn.click(
        chat_fn,
        inputs=[chat.msg_input, chat.chatbot, global_uid],
        outputs=[chat.chatbot, admin.xai_display, chat.msg_input],
    )
    chat.msg_input.submit(
        chat_fn,
        inputs=[chat.msg_input, chat.chatbot, global_uid],
        outputs=[chat.chatbot, admin.xai_display, chat.msg_input],
    )
    chat.msg_input.change(
        fn=lambda text: gr.update(interactive=bool(text.strip())),
        inputs=[chat.msg_input],
        outputs=[chat.send_btn],
    )
    reset_btn.click(reset_chat, inputs=[global_uid], outputs=[chat.chatbot, reset_status]).then(
        lambda: "",
        outputs=[delete_user_status],
    )

    # 2. Perfil
    profile.load_profile_btn.click(
        load_profile,
        inputs=[global_uid],
        outputs=_profile_fields,
    ).then(
        lambda uid: gr.update(choices=_load_category_list(uid, "goals"), value=[]),
        inputs=[global_uid],
        outputs=[profile.goals_check],
    ).then(load_weight_chart, inputs=[global_uid, profile.weight_period], outputs=[profile.weight_chart])

    # pf_age is display-only (computed from birth_date) — excluded from save inputs
    _save_fields = [f for f in _profile_fields if f is not profile.pf_age]
    profile.save_profile_btn.click(
        save_profile,
        inputs=[global_uid, *_save_fields],
        outputs=[profile.profile_status],
    )

    gdpr_delete_all_outputs = [
        profile.gdpr_status, *_profile_fields,
        profile.weight_chart, *_comp_outputs,
    ]
    profile.gdpr_export_btn.click(
        gdpr_export_fn,
        inputs=[global_uid],
        outputs=[profile.gdpr_status, profile.gdpr_export_out],
    )
    profile.gdpr_delete_btn.click(
        gdpr_delete_fn,
        inputs=[global_uid],
        outputs=gdpr_delete_all_outputs,
    )

    profile.add_weight_btn.click(
        add_weight_entry,
        inputs=[global_uid, profile.new_weight, profile.weight_period],
        outputs=[profile.weight_status, profile.weight_chart, profile.new_weight, *_profile_fields],
    )
    profile.weight_period.change(
        load_weight_chart,
        inputs=[global_uid, profile.weight_period],
        outputs=[profile.weight_chart],
    )
    profile.comp_period.change(
        load_all_comp_charts,
        inputs=[global_uid, profile.comp_period],
        outputs=_comp_outputs,
    ).then(
        lambda p: p,
        inputs=[profile.comp_period],
        outputs=[comp_period_state],
    )

    # Goals in profile tab
    profile.add_goal_btn.click(
        add_goal_and_refresh,
        inputs=[global_uid, profile.new_goal_input],
        outputs=[profile.goals_status, profile.goals_check, profile.new_goal_input],
    )
    profile.new_goal_input.submit(
        add_goal_and_refresh,
        inputs=[global_uid, profile.new_goal_input],
        outputs=[profile.goals_status, profile.goals_check, profile.new_goal_input],
    )
    profile.remove_goals_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "goals"),
        inputs=[global_uid, profile.goals_check],
        outputs=[profile.goals_status, profile.goals_check],
    )

    # 3. Dashboard
    goals.dash_refresh_btn.click(
        load_full_dashboard,
        inputs=[global_uid, goals.dash_start_date],
        outputs=_dash_outputs,
    )
    goals.dash_start_date.submit(
        load_full_dashboard,
        inputs=[global_uid, goals.dash_start_date],
        outputs=_dash_outputs,
    )

    # 4. Preferências — load
    nutrition.load_prefs_btn.click(load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS)
    nutrition.apply_seed_btn.click(
        apply_seed_fn,
        inputs=[global_uid],
        outputs=[nutrition.prefs_status, *_PREF_CHECKS],
    )

    # Preferências — food likes
    nutrition.add_like_btn.click(
        add_like_fn,
        inputs=[global_uid, nutrition.new_like_input],
        outputs=[nutrition.food_status, nutrition.likes_check, nutrition.new_like_input],
    )
    nutrition.new_like_input.submit(
        add_like_fn,
        inputs=[global_uid, nutrition.new_like_input],
        outputs=[nutrition.food_status, nutrition.likes_check, nutrition.new_like_input],
    )
    nutrition.remove_likes_btn.click(
        remove_likes_fn,
        inputs=[global_uid, nutrition.likes_check],
        outputs=[nutrition.food_status, nutrition.likes_check],
    )
    nutrition.move_to_dislikes_btn.click(
        move_to_dislikes_fn,
        inputs=[global_uid, nutrition.likes_check],
        outputs=[nutrition.food_status, nutrition.likes_check, nutrition.dislikes_check],
    )

    # Preferências — food dislikes
    nutrition.add_dislike_btn.click(
        add_dislike_fn,
        inputs=[global_uid, nutrition.new_dislike_input],
        outputs=[nutrition.food_status, nutrition.dislikes_check, nutrition.new_dislike_input],
    )
    nutrition.new_dislike_input.submit(
        add_dislike_fn,
        inputs=[global_uid, nutrition.new_dislike_input],
        outputs=[nutrition.food_status, nutrition.dislikes_check, nutrition.new_dislike_input],
    )
    nutrition.remove_dislikes_btn.click(
        remove_dislikes_fn,
        inputs=[global_uid, nutrition.dislikes_check],
        outputs=[nutrition.food_status, nutrition.dislikes_check],
    )
    nutrition.move_to_likes_btn.click(
        move_to_likes_fn,
        inputs=[global_uid, nutrition.dislikes_check],
        outputs=[nutrition.food_status, nutrition.likes_check, nutrition.dislikes_check],
    )

    # Preferências — allergies
    nutrition.add_allergy_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, nutrition.new_allergy_input],
        outputs=[nutrition.restrictions_status, nutrition.allergies_check, nutrition.new_allergy_input],
    )
    nutrition.new_allergy_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "allergies"),
        inputs=[global_uid, nutrition.new_allergy_input],
        outputs=[nutrition.restrictions_status, nutrition.allergies_check, nutrition.new_allergy_input],
    )
    nutrition.remove_allergies_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "allergies"),
        inputs=[global_uid, nutrition.allergies_check],
        outputs=[nutrition.restrictions_status, nutrition.allergies_check],
    )

    # Preferências — restrictions
    nutrition.add_restriction_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, nutrition.new_restriction_input],
        outputs=[nutrition.restrictions_status, nutrition.restrictions_check, nutrition.new_restriction_input],
    )
    nutrition.new_restriction_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "restrictions"),
        inputs=[global_uid, nutrition.new_restriction_input],
        outputs=[nutrition.restrictions_status, nutrition.restrictions_check, nutrition.new_restriction_input],
    )
    nutrition.remove_restrictions_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "restrictions"),
        inputs=[global_uid, nutrition.restrictions_check],
        outputs=[nutrition.restrictions_status, nutrition.restrictions_check],
    )

    # Preferências — health data
    nutrition.add_health_btn.click(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, nutrition.new_health_input],
        outputs=[nutrition.restrictions_status, nutrition.health_check, nutrition.new_health_input],
    )
    nutrition.new_health_input.submit(
        lambda uid, text: add_cat_item_fn(uid, text, "health_data"),
        inputs=[global_uid, nutrition.new_health_input],
        outputs=[nutrition.restrictions_status, nutrition.health_check, nutrition.new_health_input],
    )
    nutrition.remove_health_btn.click(
        lambda uid, sel: remove_cat_items_fn(uid, sel, "health_data"),
        inputs=[global_uid, nutrition.health_check],
        outputs=[nutrition.restrictions_status, nutrition.health_check],
    )

    # 5. Admin
    admin.xai_refresh_btn.click(_load_xai, outputs=[admin.xai_display])
    admin.xai_clear_btn.click(lambda: "_Análise limpa._", outputs=[admin.xai_display])

    admin.load_sessions_btn.click(load_sessions, inputs=[admin.sessions_uid_filter], outputs=[admin.sessions_table])
    admin.view_session_btn.click(view_session_messages, inputs=[admin.session_id_input], outputs=[admin.session_detail])
    admin.delete_session_btn.click(
        delete_session_fn, inputs=[admin.session_id_input], outputs=[admin.sessions_status]
    ).then(load_sessions, inputs=[admin.sessions_uid_filter], outputs=[admin.sessions_table])

    admin.load_logs_btn.click(load_logs, inputs=[admin.log_level, admin.log_search, admin.log_n], outputs=[admin.log_output])
    admin.log_stats_btn.click(log_stats_fn, outputs=[admin.log_stats_out])

    admin.load_kb_btn.click(load_knowledge, inputs=[admin.kb_collection, admin.kb_search], outputs=[admin.kb_table])
    admin.add_kb_btn.click(
        add_knowledge_fn, inputs=[admin.kb_collection, admin.new_kb_text], outputs=[admin.kb_action_status]
    ).then(load_knowledge, inputs=[admin.kb_collection, admin.kb_search], outputs=[admin.kb_table])
    admin.del_kb_btn.click(
        delete_knowledge_fn, inputs=[admin.kb_collection, admin.del_kb_id], outputs=[admin.kb_action_status]
    ).then(load_knowledge, inputs=[admin.kb_collection, admin.kb_search], outputs=[admin.kb_table])
    admin.kb_stats_btn.click(kb_stats_fn, outputs=[admin.kb_stats_out])

    # 6. Sidebar — remove account
    delete_user_btn.click(
        fn=lambda: gr.update(visible=True),
        outputs=[delete_confirm_group],
    )
    delete_cancel_btn.click(
        fn=lambda: gr.update(visible=False),
        outputs=[delete_confirm_group],
    )
    delete_confirm_btn.click(
        delete_user_fn,
        inputs=[global_uid],
        outputs=[delete_user_status, user_select, global_uid],
    ).then(
        fn=lambda: gr.update(visible=False),
        outputs=[delete_confirm_group],
    ).then(
        check_user_status, inputs=[global_uid], outputs=[user_status],
    ).then(
        load_profile, inputs=[global_uid], outputs=_profile_fields,
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

    # 7. Sidebar — user select auto-loads everything
    user_select.change(
        fn=lambda uid: uid or "",
        inputs=[user_select],
        outputs=[global_uid],
    ).then(
        check_user_status, inputs=[user_select], outputs=[user_status],
    ).then(
        load_profile,
        inputs=[user_select],
        outputs=_profile_fields,
    ).then(
        load_weight_chart, inputs=[user_select, profile.weight_period], outputs=[profile.weight_chart],
    ).then(
        load_all_comp_charts, inputs=[user_select, comp_period_state], outputs=_comp_outputs,
    ).then(
        load_all_prefs, inputs=[user_select], outputs=_PREF_CHECKS,
    ).then(
        load_full_dashboard, inputs=[global_uid, goals.dash_start_date], outputs=_dash_outputs,
    )

    new_user_btn.click(
        fn=lambda: ("", gr.update(visible=True), gr.update(selected="onboarding")),
        outputs=[global_uid, onb_tab_ref, main_tabs],
    ).then(
        onb_full_reset,
        outputs=[
            onboarding.step1_group, onboarding.step2_group, onboarding.step3_group,
            onboarding.step4_group, onboarding.step5_group, onboarding.step6_group,
            onboarding.step1_error, onboarding.step2_error,
            onboarding.step4_error, onboarding.step5_error,
            onboarding.new_name, onboarding.new_uid_input,
            onboarding.gender, onboarding.birth_date,
            onboarding.height, onboarding.weight,
            onboarding.activity, onboarding.goals, onboarding.allergies,
            onboarding.target_weight_group, onboarding.target_muscle_group,
            onboarding.target_body_fat_group, onboarding.target_visceral_group,
            onboarding.create_loading, onboarding.onb_uid,
        ],
    )

    # 7. Periodic refresh timer
    # gr.Timer.tick() does not support gr.State inputs, so tick() only bumps a
    # hidden counter to trigger the chain; all dropdown updates happen in the
    # subsequent .then() which CAN read gr.State.
    def _bump_trigger(n):
        return n + 1

    def _sync_user_dropdown(current_uid):
        """Refresh choices and auto-select the first user when none is selected.

        Always updates choices and value together so Gradio never validates a
        stale value against new choices (avoids UserWarning).
        Returns no-op updates if the DB is temporarily unavailable (e.g. during
        a long Tanita sync write) so the current user is never lost.
        """
        users = list_users()
        if not users and current_uid:
            return gr.update(), current_uid
        if current_uid:
            return gr.update(choices=users), current_uid
        if users:
            first_uid = users[0][1]
            return gr.update(choices=users, value=first_uid), first_uid
        return gr.update(choices=users, value=None), ""

    # On every page load: sync dropdown so users created via Telegram are visible.
    demo.load(
        _sync_user_dropdown,
        inputs=[global_uid],
        outputs=[user_select, global_uid],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=_profile_fields,
    ).then(
        load_weight_chart, inputs=[global_uid, profile.weight_period], outputs=[profile.weight_chart],
    ).then(
        load_all_comp_charts, inputs=[global_uid, comp_period_state], outputs=_comp_outputs,
    ).then(
        load_full_dashboard, inputs=[global_uid, goals.dash_start_date], outputs=_dash_outputs,
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    ).then(
        _initial_tab_state, inputs=[global_uid], outputs=[onb_tab_ref, main_tabs],
    )

    refresh_timer.tick(
        fn=_bump_trigger,
        inputs=[_refresh_trigger],
        outputs=[_refresh_trigger],
    ).then(
        _sync_user_dropdown,
        inputs=[global_uid],
        outputs=[user_select, global_uid],
    ).then(
        check_user_status, inputs=[global_uid], outputs=[user_status],
    ).then(
        load_profile,
        inputs=[global_uid],
        outputs=_profile_fields,
    ).then(
        load_weight_chart, inputs=[global_uid, profile.weight_period], outputs=[profile.weight_chart],
    ).then(
        load_all_comp_charts, inputs=[global_uid, comp_period_state], outputs=_comp_outputs,
    ).then(
        load_full_dashboard, inputs=[global_uid, goals.dash_start_date], outputs=_dash_outputs,
    ).then(
        load_all_prefs, inputs=[global_uid], outputs=_PREF_CHECKS,
    )

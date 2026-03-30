"""
Tests for xai/__init__.py

Covers ExplainabilityTracker state management, logging, Markdown generation,
and specialist inference. No external dependencies required.
"""

import pytest
from xai import ExplainabilityTracker, get_tracker, xai_tool
from xai import _infer_specialist


# ── ExplainabilityTracker ─────────────────────────────────────────────────────

class TestExplainabilityTrackerReset:

    def test_reset_clears_tool_calls(self):
        tracker = ExplainabilityTracker()
        tracker.log_tool("some_tool", {"arg": "val"}, "result")
        tracker.reset()
        assert tracker.generate_markdown().startswith("_Nenhuma análise")

    def test_reset_stores_user_message(self):
        tracker = ExplainabilityTracker()
        tracker.reset("Quero um plano alimentar")
        md = tracker.generate_markdown()
        # Without any tool calls yet the tracker shows the "no analysis" message
        assert "_Nenhuma análise" in md

    def test_fresh_tracker_returns_no_analysis_message(self):
        tracker = ExplainabilityTracker()
        result = tracker.generate_markdown()
        assert "_Nenhuma análise disponível ainda._" in result


class TestExplainabilityTrackerLogTool:

    def test_log_tool_appears_in_markdown(self):
        tracker = ExplainabilityTracker()
        tracker.log_tool(
            "calculate_daily_calories",
            {"weight_kg": 75, "age": 30},
            "Meta diária: 2000 kcal",
        )
        md = tracker.generate_markdown()
        assert "calculate_daily_calories" in md
        assert "Cálculo Calórico" in md   # display name

    def test_log_tool_includes_formula_note_for_calorie_calculator(self):
        tracker = ExplainabilityTracker()
        tracker.log_tool("calculate_daily_calories", {}, "result")
        md = tracker.generate_markdown()
        assert "Mifflin-St Jeor" in md

    def test_log_tool_includes_formula_note_for_met_calculator(self):
        tracker = ExplainabilityTracker()
        tracker.log_tool("estimate_calories_burned", {}, "result")
        md = tracker.generate_markdown()
        assert "MET" in md

    def test_multiple_tool_calls_all_appear(self):
        tracker = ExplainabilityTracker()
        tracker.log_tool("get_user_profile", {"user_id": "1"}, "perfil")
        tracker.log_tool("calculate_daily_calories", {"weight_kg": 70}, "2000 kcal")
        md = tracker.generate_markdown()
        assert "get_user_profile" in md
        assert "calculate_daily_calories" in md

    def test_long_result_is_truncated_to_350_chars(self):
        tracker = ExplainabilityTracker()
        long_result = "x" * 500
        tracker.log_tool("some_tool", {}, long_result)
        md = tracker.generate_markdown()
        # The stored summary should be truncated (350 chars + "…")
        assert "x" * 350 in md
        assert "x" * 400 not in md


class TestExplainabilityTrackerLogRAG:

    def test_rag_query_appears_in_markdown(self):
        tracker = ExplainabilityTracker()
        tracker.log_rag(
            collection="nutrition_knowledge",
            query="frango proteína",
            results=[{"text": "Frango: 165 kcal"}],
        )
        md = tracker.generate_markdown()
        assert "nutrition_knowledge" in md
        assert "frango proteína" in md
        assert "Fontes RAG" in md

    def test_rag_hit_count_is_correct(self):
        tracker = ExplainabilityTracker()
        tracker.log_rag("exercise_knowledge", "HIIT", [{"text": "a"}, {"text": "b"}])
        md = tracker.generate_markdown()
        assert "2 documento(s)" in md


# ── Specialist inference ──────────────────────────────────────────────────────

class TestInferSpecialist:

    def test_trainer_tools_infer_personal_trainer(self):
        result = _infer_specialist({"search_exercises", "estimate_calories_burned"})
        assert "Personal Trainer" in result

    def test_nutritionist_tool_infers_nutricionista(self):
        result = _infer_specialist({"calculate_daily_calories"})
        assert "Nutricionista" in result

    def test_chef_tools_infer_chef_nutricionista(self):
        result = _infer_specialist({"search_food_nutrition", "calculate_meal_macros"})
        assert "Chef" in result

    def test_empty_tools_returns_dash(self):
        result = _infer_specialist(set())
        assert result == "—"

    def test_profile_only_tools_return_coordinator(self):
        result = _infer_specialist({"get_user_profile", "update_user_profile"})
        assert "Coordenador" in result


# ── xai_tool decorator ────────────────────────────────────────────────────────

class TestXaiToolDecorator:

    def test_decorator_preserves_return_value(self):
        @xai_tool
        def dummy(x: int) -> str:
            return f"value={x}"

        assert dummy(42) == "value=42"

    def test_decorator_preserves_function_name(self):
        @xai_tool
        def my_function(a: str) -> str:
            return a

        assert my_function.__name__ == "my_function"

    def test_decorator_logs_to_global_tracker(self):
        tracker = get_tracker()
        tracker.reset()

        @xai_tool
        def tracked_fn(val: str) -> str:
            return f"ok:{val}"

        tracked_fn("test_input")
        md = tracker.generate_markdown()
        assert "tracked_fn" in md

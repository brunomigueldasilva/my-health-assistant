"""
Tests for tools/exercise_tools.py

estimate_calories_burned is a pure MET calculation — tested with exact values.
search_* functions mock the KnowledgeBase.
"""

import pytest
from tools.exercise_tools import (
    estimate_calories_burned,
    search_exercises,
    search_workout_plans,
)


# ── estimate_calories_burned ──────────────────────────────────────────────────

class TestEstimateCaloriesBurned:
    """
    Formula: calories = round(MET × weight_kg × (duration_minutes / 60))
    """

    def test_running_30min_70kg(self):
        # MET = 8.0 → round(8.0 * 70 * 0.5) = 280
        result = estimate_calories_burned("running", 30, 70.0)
        assert "~280 kcal" in result

    def test_hiit_45min_80kg(self):
        # MET = 10.0 → round(10.0 * 80 * 0.75) = 600
        result = estimate_calories_burned("hiit", 45, 80.0)
        assert "~600 kcal" in result

    def test_yoga_60min_65kg(self):
        # MET = 3.0 → round(3.0 * 65 * 1.0) = 195
        result = estimate_calories_burned("yoga", 60, 65.0)
        assert "~195 kcal" in result

    def test_swimming_60min_70kg(self):
        # MET = 7.0 (natação/swimming) → round(7.0 * 70 * 1.0) = 490
        result = estimate_calories_burned("swimming", 60, 70.0)
        assert "~490 kcal" in result

    def test_portuguese_name_corrida(self):
        # "corrida" → MET = 8.0, same as "running"
        result = estimate_calories_burned("corrida", 30, 70.0)
        assert "~280 kcal" in result

    def test_unknown_exercise_uses_fallback_met(self):
        # Unknown exercise → MET = 6.0 fallback
        # round(6.0 * 75 * 0.5) = 225
        result = estimate_calories_burned("exercicio_desconhecido", 30, 75.0)
        assert "~225 kcal" in result
        assert "MET: 6.0" in result

    def test_partial_name_match(self):
        # "running_fast" → not exact match, but "running" is a substring → MET = 8.0
        # round(8.0 * 70 * 0.5) = 280
        result = estimate_calories_burned("running_fast", 30, 70.0)
        assert "~280 kcal" in result

    def test_output_contains_all_fields(self):
        result = estimate_calories_burned("cycling", 60, 80.0)
        assert "Exercício:" in result
        assert "Duração:" in result
        assert "Peso:" in result
        assert "MET:" in result
        assert "Calorias gastas:" in result

    def test_boxing_30min_75kg(self):
        # MET = 9.0 → round(9.0 * 75 * 0.5) = 338
        result = estimate_calories_burned("boxing", 30, 75.0)
        assert "~338 kcal" in result

    def test_pilates_45min_60kg(self):
        # MET = 4.0 → round(4.0 * 60 * 0.75) = 180
        result = estimate_calories_burned("pilates", 45, 60.0)
        assert "~180 kcal" in result


# ── search_exercises ──────────────────────────────────────────────────────────

class TestSearchExercises:

    def test_returns_results_when_kb_has_data(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = [
            {"text": "Agachamento: exercício para quadríceps e glúteos"},
            {"text": "Lunges: fortalece as pernas e melhora o equilíbrio"},
        ]
        result = search_exercises("leg exercises")
        assert "Agachamento" in result
        assert "Lunges" in result
        mock_kb_exercise.search_exercises.assert_called_once_with("leg exercises", n_results=5)

    def test_returns_fallback_when_kb_empty(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = []
        result = search_exercises("exercicio_inexistente")
        assert "No exercises found" in result
        assert "exercicio_inexistente" in result

    def test_formats_results_as_bullets(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = [
            {"text": "Ex A"},
            {"text": "Ex B"},
            {"text": "Ex C"},
        ]
        result = search_exercises("test")
        assert result.count("•") == 3


# ── search_workout_plans ──────────────────────────────────────────────────────

class TestSearchWorkoutPlans:

    def test_returns_plans_when_kb_has_data(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = [
            {"text": "Plano A: 3x semana, full body"},
        ]
        result = search_workout_plans("lose fat")
        assert "Plano A" in result
        assert "📋 Planos de treino" in result

    def test_searches_with_correct_query(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = [{"text": "X"}]
        search_workout_plans("build muscle")
        call_args = mock_kb_exercise.search_exercises.call_args
        assert "build muscle" in call_args[0][0]

    def test_returns_fallback_when_kb_empty(self, mock_kb_exercise):
        mock_kb_exercise.search_exercises.return_value = []
        result = search_workout_plans("plano_inexistente")
        assert "No workout plans found" in result

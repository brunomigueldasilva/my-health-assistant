"""
Tests for tools/nutrition_tools.py

calculate_daily_calories and calculate_meal_macros are tested as pure functions
(no external dependencies). search_* functions mock the KnowledgeBase.
_search_open_food_facts and the fallback path in search_food_nutrition mock httpx.
"""

import pytest
from unittest.mock import MagicMock, patch
from tools.nutrition_tools import (
    calculate_daily_calories,
    search_food_nutrition,
    search_user_food_preferences,
    calculate_meal_macros,
    _search_open_food_facts,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bmr_male(w, h, age):
    return 10 * w + 6.25 * h - 5 * age + 5


def _bmr_female(w, h, age):
    return 10 * w + 6.25 * h - 5 * age - 161


MULTIPLIERS = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55,
    "active": 1.725, "very_active": 1.9,
}

ADJUSTMENTS = {"lose_weight": -400, "maintain": 0, "gain_muscle": 300}


# ── calculate_daily_calories ──────────────────────────────────────────────────

class TestCalculateDailyCalories:

    def test_male_moderate_maintain(self):
        result = calculate_daily_calories(
            weight_kg=80, height_cm=180, age=35,
            gender="male", activity_level="moderate", goal="maintain",
        )
        bmr = _bmr_male(80, 180, 35)          # 1755
        target = round(bmr * 1.55 + 0)        # 2720
        assert f"Meta diária: {target} kcal" in result
        assert f"BMR: {round(bmr)} kcal" in result

    def test_female_active_lose_weight(self):
        result = calculate_daily_calories(
            weight_kg=60, height_cm=165, age=28,
            gender="female", activity_level="active", goal="lose_weight",
        )
        bmr = _bmr_female(60, 165, 28)         # 1330.25
        target = round(bmr * 1.725 - 400)      # 1895
        assert f"Meta diária: {target} kcal" in result
        assert "Ajuste (lose_weight): -400 kcal" in result

    def test_male_very_active_gain_muscle(self):
        result = calculate_daily_calories(
            weight_kg=70, height_cm=170, age=25,
            gender="male", activity_level="very_active", goal="gain_muscle",
        )
        bmr = _bmr_male(70, 170, 25)           # 1642.5
        target = round(bmr * 1.9 + 300)        # 3421
        assert f"Meta diária: {target} kcal" in result
        assert "Ajuste (gain_muscle): +300 kcal" in result

    def test_female_sedentary_maintain(self):
        result = calculate_daily_calories(
            weight_kg=55, height_cm=160, age=40,
            gender="female", activity_level="sedentary", goal="maintain",
        )
        bmr = _bmr_female(55, 160, 40)         # 1189
        target = round(bmr * 1.2 + 0)          # 1427
        assert f"Meta diária: {target} kcal" in result

    def test_portuguese_aliases(self):
        """Gender 'masculino', activity 'moderado', goal 'manter' must work."""
        result = calculate_daily_calories(
            weight_kg=80, height_cm=180, age=35,
            gender="masculino", activity_level="moderado", goal="manter",
        )
        bmr = _bmr_male(80, 180, 35)
        target = round(bmr * 1.55 + 0)
        assert f"Meta diária: {target} kcal" in result

    def test_macro_distribution_lose_weight(self):
        """Losing weight → 40% protein, 30% carbs, 30% fat."""
        result = calculate_daily_calories(
            weight_kg=60, height_cm=165, age=28,
            gender="female", activity_level="active", goal="lose_weight",
        )
        assert "40%" in result   # protein percentage
        assert "30%" in result   # carbs and fat percentage

    def test_macro_distribution_gain_muscle(self):
        """Gaining muscle → 30% protein, 45% carbs, 25% fat."""
        result = calculate_daily_calories(
            weight_kg=70, height_cm=170, age=25,
            gender="male", activity_level="very_active", goal="gain_muscle",
        )
        assert "45%" in result   # carbs percentage
        assert "25%" in result   # fat percentage

    def test_unknown_activity_falls_back_to_moderate(self):
        """Unknown activity_level should use the 1.55 moderate multiplier."""
        result_unknown = calculate_daily_calories(
            weight_kg=75, height_cm=175, age=30,
            gender="male", activity_level="unknown_level", goal="maintain",
        )
        result_moderate = calculate_daily_calories(
            weight_kg=75, height_cm=175, age=30,
            gender="male", activity_level="moderate", goal="maintain",
        )
        # Both should produce the same target calorie value
        assert "Meta diária:" in result_unknown
        # Extract target line from both and compare
        def _target(s):
            for line in s.splitlines():
                if "Meta diária:" in line:
                    return line.strip()
        assert _target(result_unknown) == _target(result_moderate)

    def test_result_contains_required_sections(self):
        """Output must always include BMR, TDEE, and macro sections."""
        result = calculate_daily_calories(
            weight_kg=70, height_cm=170, age=30,
            gender="male", activity_level="moderate", goal="maintain",
        )
        assert "BMR:" in result
        assert "TDEE:" in result
        assert "Proteína:" in result
        assert "Carboidratos:" in result
        assert "Gordura:" in result


# ── search_food_nutrition ─────────────────────────────────────────────────────

class TestSearchFoodNutrition:

    def test_returns_results_when_kb_has_data(self, mock_kb_nutrition):
        mock_kb_nutrition.search_nutrition.return_value = [
            {"text": "Frango: 165 kcal por 100g, 31g proteína"},
            {"text": "Frango grelhado é rico em proteínas magras"},
        ]
        result = search_food_nutrition("frango")
        assert "Frango: 165 kcal" in result
        assert "proteínas magras" in result
        mock_kb_nutrition.search_nutrition.assert_called_once_with("frango", n_results=3)

    def test_returns_fallback_when_kb_and_api_empty(self, mock_kb_nutrition):
        mock_kb_nutrition.search_nutrition.return_value = []
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {"products": []}
            result = search_food_nutrition("alimento_desconhecido")
        assert "Não encontrei" in result
        assert "alimento_desconhecido" in result

    def test_uses_api_when_kb_empty(self, mock_kb_nutrition):
        """When KB has no results, Open Food Facts data should appear."""
        mock_kb_nutrition.search_nutrition.return_value = []
        api_product = {
            "product_name": "Quinoa",
            "nutriments": {
                "energy-kcal_100g": 368,
                "proteins_100g": 14.1,
                "carbohydrates_100g": 64.2,
                "fat_100g": 6.1,
                "fiber_100g": 7.0,
            },
        }
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {"products": [api_product]}
            result = search_food_nutrition("quinoa")
        assert "Quinoa" in result
        assert "368 kcal" in result
        assert "Open Food Facts" in result

    def test_kb_results_take_priority_over_api(self, mock_kb_nutrition):
        """When KB has results, the API must NOT be called."""
        mock_kb_nutrition.search_nutrition.return_value = [
            {"text": "Frango local: 165 kcal por 100g"},
        ]
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            result = search_food_nutrition("frango")
        mock_get.assert_not_called()
        assert "Frango local" in result

    def test_formats_each_result_as_bullet(self, mock_kb_nutrition):
        mock_kb_nutrition.search_nutrition.return_value = [
            {"text": "Item A"},
            {"text": "Item B"},
        ]
        result = search_food_nutrition("teste")
        assert result.count("•") == 2


# ── search_user_food_preferences ─────────────────────────────────────────────

class TestSearchUserFoodPreferences:

    def test_returns_user_preferences(self, mock_kb_nutrition):
        mock_kb_nutrition.search_preferences.return_value = [
            {"text": "frango", "metadata": {"category": "food_likes"}},
            {"text": "brócolos", "metadata": {"category": "food_likes"}},
        ]
        result = search_user_food_preferences("likes", user_id="123")
        assert "frango" in result
        assert "food_likes" in result

    def test_falls_back_to_default_when_no_user_id(self, mock_kb_nutrition):
        mock_kb_nutrition.search_preferences.return_value = [
            {"text": "pão integral", "metadata": {"category": "food_likes"}},
        ]
        result = search_user_food_preferences("likes", user_id="")
        # Called with "default" user
        mock_kb_nutrition.search_preferences.assert_called_with("default", "likes", n_results=20)
        assert "pão integral" in result

    def test_returns_no_preferences_message_when_both_empty(self, mock_kb_nutrition):
        mock_kb_nutrition.search_preferences.return_value = []
        result = search_user_food_preferences("allergies", user_id="999")
        assert "Sem preferências" in result


# ── calculate_meal_macros ─────────────────────────────────────────────────────

class TestCalculateMealMacros:

    def test_returns_nutritional_info_when_kb_has_data(self, mock_kb_nutrition):
        mock_kb_nutrition.search_nutrition.return_value = [
            {"text": "Peito de frango 150g: ~250 kcal, 47g proteína"},
        ]
        result = calculate_meal_macros("150g chicken breast")
        assert "Peito de frango" in result
        assert "ℹ️ Informação nutricional" in result

    def test_returns_error_when_kb_empty(self, mock_kb_nutrition):
        mock_kb_nutrition.search_nutrition.return_value = []
        result = calculate_meal_macros("ingrediente_inexistente")
        assert "Informação insuficiente" in result


# ── _search_open_food_facts ───────────────────────────────────────────────────

class TestSearchOpenFoodFacts:

    def _make_response(self, products: list) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"products": products}
        return mock_resp

    def test_returns_formatted_result_with_macros(self):
        product = {
            "product_name": "Aveia",
            "nutriments": {
                "energy-kcal_100g": 389,
                "proteins_100g": 16.9,
                "carbohydrates_100g": 66.3,
                "fat_100g": 6.9,
                "fiber_100g": 10.6,
            },
        }
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response([product])
            results = _search_open_food_facts("aveia")

        assert len(results) == 1
        assert "Aveia" in results[0]["text"]
        assert "389 kcal" in results[0]["text"]
        assert "16.9g" in results[0]["text"]    # protein
        assert "Open Food Facts" in results[0]["metadata"]["source"]

    def test_includes_fiber_when_present(self):
        product = {
            "product_name": "Chia",
            "nutriments": {
                "energy-kcal_100g": 486,
                "proteins_100g": 16.5,
                "carbohydrates_100g": 42.1,
                "fat_100g": 30.7,
                "fiber_100g": 34.4,
            },
        }
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response([product])
            results = _search_open_food_facts("chia")

        assert "34.4g" in results[0]["text"]   # fiber present

    def test_omits_fiber_when_zero(self):
        product = {
            "product_name": "Açúcar",
            "nutriments": {
                "energy-kcal_100g": 400,
                "proteins_100g": 0,
                "carbohydrates_100g": 100,
                "fat_100g": 0,
                "fiber_100g": 0,
            },
        }
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response([product])
            results = _search_open_food_facts("açúcar")

        assert "Fibra" not in results[0]["text"]

    def test_returns_empty_list_on_timeout(self):
        import httpx as real_httpx
        with patch("tools.nutrition_tools.httpx.get", side_effect=real_httpx.TimeoutException("timeout")):
            results = _search_open_food_facts("qualquer_alimento")
        assert results == []

    def test_returns_empty_list_on_http_error(self):
        with patch("tools.nutrition_tools.httpx.get", side_effect=Exception("connection error")):
            results = _search_open_food_facts("qualquer_alimento")
        assert results == []

    def test_returns_empty_list_when_no_products(self):
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response([])
            results = _search_open_food_facts("produto_inexistente")
        assert results == []

    def test_limits_to_three_products(self):
        products = [
            {"product_name": f"Produto {i}", "nutriments": {"energy-kcal_100g": 100 * i}}
            for i in range(1, 6)   # 5 products returned
        ]
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response(products)
            results = _search_open_food_facts("multi")
        assert len(results) <= 3

    def test_api_called_with_correct_params(self):
        with patch("tools.nutrition_tools.httpx.get") as mock_get:
            mock_get.return_value = self._make_response([])
            _search_open_food_facts("banana")
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["search_terms"] == "banana"
        assert params["json"] == 1
        assert params["page_size"] == 3

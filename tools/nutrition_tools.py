"""
Nutrition Tools — food search, calorie calculation, macro tracking.
Tool docstrings are in English so the LLM can parse them reliably.
User-facing output remains in Portuguese.
"""

import logging
from knowledge import get_knowledge_base
from xai import xai_tool

logger = logging.getLogger(__name__)


@xai_tool
def search_food_nutrition(food_name: str) -> str:
    """
    Search nutritional information for a food item in the knowledge base.

    Args:
        food_name: Name of the food to search (e.g. "chicken breast", "brown rice")

    Returns:
        Nutritional info found (calories, macros, benefits) in Portuguese
    """
    kb = get_knowledge_base()
    results = kb.search_nutrition(food_name, n_results=3)

    if not results:
        return f"Não encontrei informação nutricional sobre '{food_name}' na base de dados. Usa conhecimento geral."

    return "\n".join(f"• {r['text']}" for r in results)


@xai_tool
def search_user_food_preferences(query: str, user_id: str = "") -> str:
    """
    Search the user's food preferences and dietary restrictions.

    Args:
        query: Type of preference to search (e.g. "likes", "dislikes", "allergies", "goals")
        user_id: Telegram user ID from the [User: Name, ID: <id>] message prefix (optional)

    Returns:
        List of the user's food preferences
    """
    kb = get_knowledge_base()
    uid = user_id.strip() if user_id else ""
    results = kb.search_preferences(uid, query, n_results=20) if uid else []

    if not results:
        results = kb.search_preferences("default", query, n_results=20)

    if not results:
        return "Sem preferências alimentares registadas. Usar /gosto e /nao_gosto para adicionar."

    return "\n".join(
        f"[{r['metadata'].get('category', 'geral')}] {r['text']}" for r in results
    )


@xai_tool
def calculate_daily_calories(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str,
) -> str:
    """
    Calculate daily caloric needs using Mifflin-St Jeor formula.

    Args:
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        age: Age in years
        gender: "male" or "female"
        activity_level: "sedentary", "light", "moderate", "active", "very_active"
        goal: "lose_weight", "maintain", "gain_muscle"

    Returns:
        Detailed calorie and macro calculation
    """
    if gender.lower() in ("masculino", "m", "male"):
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    multipliers = {
        "sedentary": 1.2, "sedentario": 1.2,
        "light": 1.375, "leve": 1.375,
        "moderate": 1.55, "moderado": 1.55,
        "active": 1.725, "activo": 1.725,
        "very_active": 1.9, "muito_activo": 1.9,
    }
    tdee = bmr * multipliers.get(activity_level.lower(), 1.55)

    adjustments = {
        "lose_weight": -400, "perder_peso": -400,
        "maintain": 0, "manter": 0,
        "gain_muscle": 300, "ganhar_massa": 300,
    }
    adjustment = adjustments.get(goal.lower(), 0)
    target = round(tdee + adjustment)

    if "lose" in goal.lower() or "perder" in goal.lower():
        p_pct, c_pct, f_pct = 0.40, 0.30, 0.30
    elif "gain" in goal.lower() or "ganhar" in goal.lower():
        p_pct, c_pct, f_pct = 0.30, 0.45, 0.25
    else:
        p_pct, c_pct, f_pct = 0.30, 0.40, 0.30

    return (
        f"📊 Cálculo Calórico:\n"
        f"  • BMR: {round(bmr)} kcal\n"
        f"  • TDEE: {round(tdee)} kcal\n"
        f"  • Ajuste ({goal}): {adjustment:+d} kcal\n"
        f"  • Meta diária: {target} kcal\n\n"
        f"🥩 Macros recomendados:\n"
        f"  • Proteína: {round((target * p_pct) / 4)}g ({int(p_pct*100)}%)\n"
        f"  • Carboidratos: {round((target * c_pct) / 4)}g ({int(c_pct*100)}%)\n"
        f"  • Gordura: {round((target * f_pct) / 9)}g ({int(f_pct*100)}%)\n\n"
        f"💡 Distribuir por 4-5 refeições ao longo do dia."
    )


@xai_tool
def calculate_meal_macros(foods: str) -> str:
    """
    Estimate macros for a meal from a list of foods with quantities.

    Args:
        foods: Comma-separated list of foods with quantities
               (e.g. "150g chicken breast, 200g brown rice, 100g broccoli")

    Returns:
        Nutritional information for the listed foods
    """
    kb = get_knowledge_base()
    results = kb.search_nutrition(foods, n_results=5)

    if not results:
        return "Informação insuficiente para calcular os macros desta refeição."

    return (
        "ℹ️ Informação nutricional encontrada:\n\n"
        + "\n".join(f"• {r['text']}" for r in results)
        + "\n\n💡 Ajustar às quantidades indicadas pelo utilizador."
    )


NUTRITION_TOOLS = [
    search_food_nutrition,
    search_user_food_preferences,
    calculate_daily_calories,
    calculate_meal_macros,
]

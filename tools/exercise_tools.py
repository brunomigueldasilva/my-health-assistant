"""
Exercise Tools — search exercises, workout plans, calorie estimation.
Tool docstrings in English for LLM reliability.
"""

import logging
from knowledge import get_knowledge_base
from xai import xai_tool

logger = logging.getLogger(__name__)


@xai_tool
def search_exercises(query: str) -> str:
    """
    Search exercises in the knowledge base by muscle group, type, or goal.

    Args:
        query: Free-text search (e.g. "chest exercises", "HIIT", "lose visceral fat")

    Returns:
        List of relevant exercises with details
    """
    kb = get_knowledge_base()
    results = kb.search_exercises(query, n_results=5)

    if not results:
        return f"No exercises found for '{query}'. Use general knowledge."

    return "\n".join(f"• {r['text']}" for r in results)


@xai_tool
def search_workout_plans(goal: str) -> str:
    """
    Search structured workout plans for a specific fitness goal.

    Args:
        goal: Fitness goal (e.g. "lose fat", "build muscle",
              "improve cardio", "beginner workout")

    Returns:
        Recommended workout plans
    """
    kb = get_knowledge_base()
    results = kb.search_exercises(f"plano treino {goal}", n_results=5)

    if not results:
        return f"No workout plans found for '{goal}'."

    return "📋 Planos de treino relevantes:\n\n" + "\n".join(
        f"• {r['text']}" for r in results
    )


@xai_tool
def estimate_calories_burned(
    exercise: str, duration_minutes: int, weight_kg: float
) -> str:
    """
    Estimate calories burned during an exercise session.

    Args:
        exercise: Exercise name (e.g. "running", "weight training", "HIIT", "swimming")
        duration_minutes: Duration in minutes
        weight_kg: User weight in kg

    Returns:
        Estimated calories burned with breakdown
    """
    met_values = {
        "corrida": 8.0, "running": 8.0,
        "caminhada": 3.5, "walking": 3.5,
        "musculação": 6.0, "weight_training": 6.0, "weights": 6.0,
        "hiit": 10.0,
        "ciclismo": 7.5, "cycling": 7.5,
        "natação": 7.0, "swimming": 7.0,
        "saltar_corda": 11.0, "jump_rope": 11.0,
        "yoga": 3.0,
        "pilates": 4.0,
        "remo": 7.0, "rowing": 7.0,
        "boxe": 9.0, "boxing": 9.0,
        "futebol": 7.0, "football": 7.0, "soccer": 7.0,
    }

    exercise_key = exercise.lower().replace(" ", "_").replace("-", "_")
    met = met_values.get(exercise_key, 6.0)

    if exercise_key not in met_values:
        for key, val in met_values.items():
            if key in exercise_key or exercise_key in key:
                met = val
                break

    calories = round(met * weight_kg * (duration_minutes / 60))

    return (
        f"🔥 Estimativa de calorias:\n"
        f"  • Exercício: {exercise}\n"
        f"  • Duração: {duration_minutes} min\n"
        f"  • Peso: {weight_kg} kg\n"
        f"  • MET: {met}\n"
        f"  • Calorias gastas: ~{calories} kcal\n\n"
        f"💡 Valores aproximados. Variam com intensidade e condição física."
    )


EXERCISE_TOOLS = [
    search_exercises,
    search_workout_plans,
    estimate_calories_burned,
]

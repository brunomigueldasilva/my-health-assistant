"""
Coordinator Agent — receives messages and routes to the correct specialist.

Uses Agno Team with mode="route" for automatic routing.
"""

from agno.team.team import Team
from agno.db.sqlite import SqliteDb

from config import DEBUG_MODE, SQLITE_SESSIONS
from config import get_model
from agents.nutritionist import nutritionist_agent
from agents.trainer import trainer_agent
from agents.chef import chef_agent
from tools.profile_tools import PROFILE_TOOLS


def create_health_team() -> Team:
    """
    Create the health team with automatic routing.

    Agno Team modes:
      - "route"       → coordinator analyzes the message and sends
                         to the most appropriate agent (our use case)
      - "coordinate"  → coordinator delegates and supervises multiple agents
      - "collaborate" → all agents work on the same task
    """

    health_team = Team(
        name="Health Assistant Team",
        mode="route",
        model=get_model(),
        members=[
            nutritionist_agent,
            trainer_agent,
            chef_agent,
        ],
        db=SqliteDb(db_file=str(SQLITE_SESSIONS)),
        description=(
            "You are the coordinator of a health and wellness team. "
            "Your role is to analyze the user's message and route it "
            "to the most appropriate specialist agent."
        ),
        instructions=[
            "The user writes in Portuguese. ALWAYS respond in European Portuguese.",
            "Analyze the user message and route to the correct specialist:",
            "",
            "→ NUTRITIONIST: questions about food, calories, macros, "
            "  meal plans, diets, supplements, caloric deficit, "
            "  nutritional information about foods.",
            "",
            "→ PERSONAL TRAINER: questions about exercises, workouts, "
            "  workout plans, muscle groups, calories burned during exercise, "
            "  HIIT, weight training, cardio, flexibility.",
            "",
            "→ CHEF: recipe requests, specific meal suggestions, "
            "  food preparation, meal prep, ideas for breakfast/"
            "  lunch/dinner/snacks.",
            "",
            "If the message is ambiguous or involves multiple domains, "
            "route to the main agent (e.g. 'I want to lose weight' → Nutritionist).",
            "",
            "For profile, preferences, and goals questions, use the tools directly.",
        ],
        tools=PROFILE_TOOLS,
        show_members_responses=True,
        markdown=True,
        debug_mode=DEBUG_MODE,
    )

    return health_team

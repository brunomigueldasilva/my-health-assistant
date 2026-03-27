"""
Seed Data — Populates the knowledge base with initial data.

Usage:
    python -m knowledge.seed_data

Edit the lists below with your own preferences before running.
"""

import logging

from knowledge import get_knowledge_base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# ✏️  EDIT YOUR PREFERENCES HERE
# ═══════════════════════════════════════════════════════

DEFAULT_USER_ID = "default"

# Foods you like
FOOD_LIKES = [
    "frango grelhado",
    "salmão",
    "arroz integral",
    "brócolos",
    "batata-doce",
    "ovos",
    "abacate",
    "iogurte grego natural",
    "amêndoas",
    "bananas",
    "espinafres",
    "tomate",
    "queijo fresco",
    "aveia",
    "feijão preto",
]

# Foods you DON'T like
FOOD_DISLIKES = [
    "beterraba",
    "fígado",
    "nabo",
    "coentros",
    "azeitonas pretas",
    "tofu",
]

# Allergies or intolerances
ALLERGIES = [
    # "glúten",
    # "lactose",
    # "frutos secos",
]

# Dietary restrictions
RESTRICTIONS = [
    # "vegetariano",
    # "sem glúten",
    # "baixo em sódio",
]

# ═══════════════════════════════════════════════════════
# NUTRITIONAL KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════

NUTRITION_DATA = [
    # Proteins
    "Peito de frango grelhado (100g): 165 kcal, 31g proteína, 3.6g gordura, 0g carboidratos. "
    "Excelente fonte de proteína magra. Ideal para ganho muscular e perda de gordura.",
    "Salmão (100g): 208 kcal, 20g proteína, 13g gordura (rico em ómega-3), 0g carboidratos. "
    "O ómega-3 reduz inflamação e melhora saúde cardiovascular.",
    "Ovos inteiros (1 unidade ~50g): 72 kcal, 6.3g proteína, 4.8g gordura, 0.4g carboidratos. "
    "Contém todos os aminoácidos essenciais, vitamina D e colina.",
    "Iogurte grego natural (100g): 59 kcal, 10g proteína, 0.7g gordura, 3.6g carboidratos. "
    "Rico em probióticos, bom para saúde intestinal.",
    "Queijo fresco (100g): 103 kcal, 11g proteína, 4.5g gordura, 3.5g carboidratos.",
    "Feijão preto cozido (100g): 132 kcal, 8.9g proteína, 0.5g gordura, 23.7g carboidratos. "
    "Rico em fibra e ferro vegetal.",

    # Carbohydrates
    "Arroz integral cozido (100g): 123 kcal, 2.7g proteína, 1g gordura, 25.6g carboidratos. "
    "Fonte de carboidratos complexos, rica em fibra e magnésio.",
    "Batata-doce cozida (100g): 90 kcal, 2g proteína, 0.1g gordura, 20.7g carboidratos. "
    "Índice glicémico moderado, rica em vitamina A e potássio.",
    "Aveia (100g): 389 kcal, 16.9g proteína, 6.9g gordura, 66.3g carboidratos. "
    "Rica em beta-glucanas que reduzem colesterol. Excelente para pequeno-almoço.",
    "Banana (1 média ~118g): 105 kcal, 1.3g proteína, 0.4g gordura, 27g carboidratos. "
    "Boa fonte de potássio, ideal pré-treino.",

    # Healthy fats
    "Abacate (100g): 160 kcal, 2g proteína, 14.7g gordura (monoinsaturada), 8.5g carboidratos. "
    "Rico em potássio, fibra e gorduras saudáveis para o coração.",
    "Amêndoas (28g ~23 unidades): 164 kcal, 6g proteína, 14g gordura, 6g carboidratos. "
    "Ricas em vitamina E, magnésio e gorduras monoinsaturadas.",
    "Azeite extra-virgem (1 colher de sopa ~14g): 119 kcal, 0g proteína, 13.5g gordura, 0g carboidratos. "
    "Base da dieta mediterrânica, anti-inflamatório natural.",

    # Vegetables
    "Brócolos cozidos (100g): 35 kcal, 2.4g proteína, 0.4g gordura, 7.2g carboidratos. "
    "Excelente fonte de vitamina C, K e fibra. Propriedades anti-cancerígenas.",
    "Espinafres crus (100g): 23 kcal, 2.9g proteína, 0.4g gordura, 3.6g carboidratos. "
    "Rico em ferro, vitamina K, folato e antioxidantes.",
    "Tomate (100g): 18 kcal, 0.9g proteína, 0.2g gordura, 3.9g carboidratos. "
    "Rico em licopeno (antioxidante), vitamina C.",

    # Conceitos nutricionais
    "Para perder gordura visceral: défice calórico de 300-500 kcal/dia, proteína alta "
    "(1.6-2.2g/kg), reduzir açúcares refinados e álcool. Exercício aeróbico + musculação.",
    "Para ganho muscular: superávit calórico de 200-300 kcal/dia, proteína 1.8-2.2g/kg, "
    "carboidratos complexos pré e pós-treino, sono 7-9h por noite.",
    "Macros para perda de peso: 40% proteína, 30% carboidratos, 30% gordura. "
    "Ajustar conforme resposta individual e nível de actividade.",
    "Macros para manutenção/desempenho: 30% proteína, 45% carboidratos, 25% gordura.",
    "Hidratação: mínimo 2L de água/dia. Adicionar 500ml por hora de exercício. "
    "A desidratação reduz performance em até 25%.",
    "Timing nutricional: refeição pré-treino 1-2h antes (carboidratos + proteína), "
    "refeição pós-treino até 2h depois (proteína + carboidratos rápidos).",
]

# ═══════════════════════════════════════════════════════
# EXERCISE KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════

EXERCISE_DATA = [
    # Weight training — Chest
    "Supino reto com barra: peito, tríceps, deltóide anterior. "
    "3-4 séries de 8-12 repetições. Exercício composto fundamental.",
    "Flexões (push-ups): peito, tríceps, core. Sem equipamento. "
    "3 séries até falha ou 15-20 reps. Variações: diamante, inclinado, declinado.",
    "Supino inclinado com halteres: peito superior, deltóide anterior. "
    "3 séries de 10-12 repetições. Foco no peito superior.",

    # Weight training — Back
    "Remada curvada com barra: dorsais, rombóides, trapézio, bíceps. "
    "3-4 séries de 8-12 reps. Manter costas neutras.",
    "Puxada alta (lat pulldown): dorsais, bíceps, antebraço. "
    "3 séries de 10-15 reps. Alternativa a elevações.",
    "Elevações (pull-ups): dorsais, bíceps, core. Peso corporal. "
    "3 séries até falha. Exercício rei para costas.",

    # Weight training — Legs
    "Agachamento (squat): quadríceps, glúteos, isquiotibiais, core. "
    "4 séries de 8-12 reps. Exercício composto mais completo.",
    "Peso morto (deadlift): isquiotibiais, glúteos, dorsais, core. "
    "3-4 séries de 6-10 reps. Maior activação muscular global.",
    "Lunges (afundos): quadríceps, glúteos, equilíbrio. "
    "3 séries de 12 reps por perna. Bom para unilateral.",

    # Weight training — Shoulders and Arms
    "Press militar (overhead press): deltóides, tríceps, trapézio. "
    "3 séries de 8-12 reps. Pode ser com barra ou halteres.",
    "Curl bíceps com halteres: bíceps, antebraço. "
    "3 séries de 10-15 reps. Alternado ou simultâneo.",
    "Extensão tríceps (skull crusher): tríceps. "
    "3 séries de 10-12 reps. Com barra EZ ou halteres.",

    # Cardio
    "Corrida moderada (8 km/h): queima ~400-500 kcal/hora. "
    "Melhora saúde cardiovascular, reduz gordura visceral. 30-45 min recomendado.",
    "HIIT (High Intensity Interval Training): queima ~500-800 kcal/hora. "
    "20-30 min. Alterna sprints (30s) com recuperação (60s). "
    "Muito eficaz para perda de gordura e melhoria de VO2max.",
    "Ciclismo moderado: queima ~400-600 kcal/hora. "
    "Baixo impacto articular. Bom para recuperação activa.",
    "Natação: queima ~400-700 kcal/hora. "
    "Trabalha corpo inteiro com zero impacto. Ideal para lesões.",
    "Saltar à corda: queima ~600-900 kcal/hora. "
    "Melhora coordenação e resistência cardiovascular. 15-20 min.",

    # Workout plans
    "Treino Push/Pull/Legs (PPL): dividir treino em empurrar (peito, ombros, tríceps), "
    "puxar (costas, bíceps), pernas. 6 dias/semana. Ideal para intermédio/avançado.",
    "Treino Full Body: trabalhar todo o corpo em cada sessão. "
    "3 dias/semana. Ideal para iniciantes. Focar em exercícios compostos.",
    "Treino Upper/Lower: alternar membros superiores e inferiores. "
    "4 dias/semana. Bom equilíbrio volume/recuperação.",

    # Specific goals
    "Para reduzir gordura visceral: combinar HIIT (2-3x/semana) com musculação (3-4x/semana). "
    "A musculação aumenta metabolismo basal. Cardio queima calorias directamente. "
    "Priorizar exercícios compostos (squat, deadlift, supino) que recrutam mais músculos.",
    "Para ganho muscular (hipertrofia): 4-6 dias/semana de musculação. "
    "Volume: 10-20 séries por grupo muscular/semana. Progressão de carga essencial. "
    "Descanso 60-90s entre séries. Fase excêntrica lenta (3-4s).",
    "Para melhoria cardiovascular: 150 min/semana de actividade moderada OU "
    "75 min/semana de actividade vigorosa. Incluir pelo menos 2 sessões de HIIT.",
]


def seed_user_preferences(user_id: str, force: bool = False) -> bool:
    """
    Seeds default food preferences for a user.

    Only adds preferences if the user has none yet (avoids duplicates),
    unless force=True.

    Args:
        user_id: User ID
        force: If True, seeds even when preferences already exist

    Returns:
        True if preferences were added, False if they already existed (and force=False)
    """
    kb = get_knowledge_base()

    # Check if user already has preferences
    if not force:
        try:
            existing = kb.preferences.get(where={"user_id": user_id})
            if existing and existing.get("ids"):
                logger.info("User %s already has preferences, skipping seed.", user_id)
                return False
        except Exception:
            pass

    logger.info("Seeding default preferences for user: %s", user_id)

    for food in FOOD_LIKES:
        kb.add_preference(user_id, "food_likes", food, {"sentiment": "positive"})

    for food in FOOD_DISLIKES:
        kb.add_preference(user_id, "food_dislikes", food, {"sentiment": "negative"})

    for allergy in ALLERGIES:
        kb.add_preference(user_id, "allergies", allergy, {"severity": "high"})

    for restriction in RESTRICTIONS:
        kb.add_preference(user_id, "restrictions", restriction, {})

    logger.info("✅ Default preferences added for: %s", user_id)
    return True


def seed_all():
    """Seeds the knowledge base with all data."""
    kb = get_knowledge_base()

    logger.info("═══ Seeding food preferences ═══")
    seed_user_preferences(DEFAULT_USER_ID)

    logger.info("═══ Seeding nutritional knowledge ═══")
    for info in NUTRITION_DATA:
        kb.add_nutrition_info(info)

    logger.info("═══ Seeding exercise knowledge ═══")
    for info in EXERCISE_DATA:
        kb.add_exercise_info(info)

    logger.info("✅ Seed complete! Knowledge base populated.")


if __name__ == "__main__":
    seed_all()

"""
Explainable AI (XAI) — ExplainabilityTracker
=============================================
Captura chamadas a ferramentas, queries ao RAG (ChromaDB) e infere o
especialista activado em cada resposta.

Fornece um resumo em Markdown para apresentar na tab "Explicabilidade"
da UI Gradio.

Utilização:
    from xai import get_tracker, xai_tool

    @xai_tool
    def minha_ferramenta(arg: str) -> str:
        ...
"""

import functools
import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


# ── Nomes legíveis das ferramentas ────────────────────────────────────────────

TOOL_DISPLAY_NAMES: dict[str, str] = {
    "search_food_nutrition":        "Pesquisa Nutricional (RAG)",
    "search_user_food_preferences": "Preferências Alimentares do Utilizador (RAG)",
    "calculate_daily_calories":     "Cálculo Calórico — Mifflin-St Jeor",
    "calculate_meal_macros":        "Macros da Refeição (RAG)",
    "search_exercises":             "Pesquisa de Exercícios (RAG)",
    "search_workout_plans":         "Planos de Treino (RAG)",
    "estimate_calories_burned":     "Estimativa de Calorias — Fórmula MET",
    "get_user_profile":             "Consulta do Perfil do Utilizador",
    "update_user_profile":          "Atualização do Perfil",
    "add_food_preference":          "Registo de Preferência Alimentar",
    "add_health_goal":              "Registo de Objetivo de Saúde",
    "get_weight_history":           "Consulta do Histórico de Peso",
}

# Notas explicativas sobre os cálculos internos de cada ferramenta
TOOL_FORMULA_NOTES: dict[str, str] = {
    "calculate_daily_calories": (
        "**Fórmula Mifflin-St Jeor:**\n"
        "- Homem:  BMR = 10×peso + 6.25×altura − 5×idade + 5\n"
        "- Mulher: BMR = 10×peso + 6.25×altura − 5×idade − 161\n"
        "- TDEE = BMR × multiplicador de atividade\n"
        "  (sedentário=1.2 · leve=1.375 · moderado=1.55 · activo=1.725 · muito activo=1.9)\n"
        "- Meta = TDEE ± ajuste do objetivo\n"
        "  (perder peso=−400 kcal · manter=0 · ganhar massa=+300 kcal)"
    ),
    "estimate_calories_burned": (
        "**Fórmula MET (Metabolic Equivalent of Task):**\n"
        "- Calorias = MET × peso(kg) × duração(horas)\n"
        "- Valores MET por exercício:\n"
        "  corrida=8.0 · HIIT=10.0 · musculação=6.0 · ciclismo=7.5\n"
        "  natação=7.0 · caminhada=3.5 · yoga=3.0 · boxe=9.0"
    ),
}


# ── Inferência do especialista activado ──────────────────────────────────────

_TRAINER_TOOLS      = {"search_exercises", "search_workout_plans", "estimate_calories_burned"}
_NUTRITIONIST_EXCL  = {"calculate_daily_calories"}
_CHEF_NUTRITION     = {"search_food_nutrition", "search_user_food_preferences", "calculate_meal_macros"}


def _infer_specialist(called_tools: set[str]) -> str:
    """Infere o especialista com base nas ferramentas chamadas."""
    if called_tools & _TRAINER_TOOLS:
        return "🏋️ Personal Trainer"
    if called_tools & _NUTRITIONIST_EXCL:
        return "🥗 Nutricionista"
    if called_tools & _CHEF_NUTRITION:
        return "👨‍🍳 Chef / Nutricionista"
    if called_tools:
        return "🤖 Coordenador (resposta directa sem especialista)"
    return "—"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    name:         str
    display_name: str
    args:         dict
    result_summary: str
    formula_note: str = ""
    timestamp:    str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


@dataclass
class RAGQueryRecord:
    collection:  str
    query:       str
    hits:        int
    top_results: list[str]
    timestamp:   str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


# ── Tracker principal ─────────────────────────────────────────────────────────

class ExplainabilityTracker:
    """
    Regista em tempo-real todas as chamadas a ferramentas e queries RAG
    efectuadas durante uma única interacção com o agente.

    É um singleton global — chamar reset() no início de cada mensagem
    garante que os dados correspondem sempre à última interacção.
    """

    def __init__(self) -> None:
        self._tool_calls:   list[ToolCallRecord] = []
        self._rag_queries:  list[RAGQueryRecord] = []
        self._user_message: str = ""
        self._timestamp:    str = ""

    # ── Controlo ─────────────────────────────────────────────────────────────

    def reset(self, user_message: str = "") -> None:
        """Limpa o estado para a nova mensagem."""
        self._tool_calls   = []
        self._rag_queries  = []
        self._user_message = user_message
        self._timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Registo ───────────────────────────────────────────────────────────────

    def log_tool(self, name: str, args: dict, result: str) -> None:
        """Regista uma chamada a uma ferramenta."""
        display  = TOOL_DISPLAY_NAMES.get(name, name)
        formula  = TOOL_FORMULA_NOTES.get(name, "")
        summary  = result[:350] + "…" if len(result) > 350 else result
        self._tool_calls.append(ToolCallRecord(name, display, args, summary, formula))
        logger.info("[XAI] tool=%-35s args=%s", name, list(args.keys()))

    def log_rag(self, collection: str, query: str, results: list[dict]) -> None:
        """Regista uma query ao ChromaDB (RAG)."""
        top = [r.get("text", "")[:130] for r in results[:3]]
        self._rag_queries.append(RAGQueryRecord(collection, query, len(results), top))
        logger.info("[XAI] rag=%-25s query=%-30r hits=%d", collection, query, len(results))

    # ── Geração do relatório ──────────────────────────────────────────────────

    def generate_markdown(self) -> str:
        """Gera o relatório XAI completo em Markdown."""
        if not self._tool_calls and not self._rag_queries:
            return (
                "_Nenhuma análise disponível ainda._\n\n"
                "Envia uma mensagem no tab **💬 Chat** e depois clica em "
                "**🔄 Atualizar Análise** para ver a explicação."
            )

        specialist = _infer_specialist({tc.name for tc in self._tool_calls})

        lines: list[str] = [
            f"**⏱️ Timestamp:** {self._timestamp}",
            "",
            f"**💬 Mensagem analisada:** _{self._user_message[:150]}_" if self._user_message else "",
            "",
            f"**🤖 Especialista activado:** {specialist}",
            "",
        ]

        # ── Ferramentas ───────────────────────────────────────────────────────
        if self._tool_calls:
            lines += ["---", "## 🔧 Ferramentas Utilizadas", ""]
            for i, tc in enumerate(self._tool_calls, 1):
                # Filtrar args internos irrelevantes
                visible_args = {
                    k: v for k, v in tc.args.items()
                    if k not in ("self",) and v is not None
                }
                args_str = "  |  ".join(
                    f"`{k}` = `{str(v)[:50]}`" for k, v in visible_args.items()
                )
                lines.append(f"### {i}. {tc.display_name}")
                lines.append(f"**Função:** `{tc.name}` &nbsp;·&nbsp; ⏱️ {tc.timestamp}")
                if args_str:
                    lines.append(f"**Argumentos:** {args_str}")
                lines.append("**Resultado:**")
                lines.append(f"> {tc.result_summary.replace(chr(10), '  ')}")
                if tc.formula_note:
                    lines.append("")
                    lines.append("**📐 Fundamento matemático:**")
                    lines.append(tc.formula_note)
                lines.append("")

        # ── Fontes RAG ────────────────────────────────────────────────────────
        if self._rag_queries:
            lines += ["---", "## 🔍 Fontes RAG Consultadas", ""]
            lines.append(
                "O modelo consultou a base de conhecimento vectorial (ChromaDB) "
                "para fundamentar a sua resposta com informação relevante."
            )
            lines.append("")
            for rq in self._rag_queries:
                lines.append(
                    f"**Colecção:** `{rq.collection}` &nbsp;·&nbsp; "
                    f"**Query:** _{rq.query}_ &nbsp;·&nbsp; "
                    f"**{rq.hits} documento(s) recuperado(s)** &nbsp;·&nbsp; ⏱️ {rq.timestamp}"
                )
                if rq.top_results:
                    lines.append("**Top resultados:**")
                    for j, txt in enumerate(rq.top_results, 1):
                        trimmed = (txt[:130] + "…") if len(txt) > 130 else txt
                        lines.append(f"{j}. {trimmed}")
                lines.append("")

        # ── Rodapé ────────────────────────────────────────────────────────────
        lines += [
            "---",
            "_Esta análise foi gerada automaticamente pelo módulo XAI do Health Assistant._",
        ]

        return "\n".join(lines)


# ── Singleton global ──────────────────────────────────────────────────────────

_tracker = ExplainabilityTracker()


def get_tracker() -> ExplainabilityTracker:
    """Retorna a instância global do tracker XAI."""
    return _tracker


# ── Decorator ─────────────────────────────────────────────────────────────────

def xai_tool(fn: Callable) -> Callable:
    """
    Decorator que envolve uma função-ferramenta para registar
    automaticamente a sua chamada no ExplainabilityTracker global.

    Preserva a assinatura e docstring originais (via functools.wraps)
    para que o framework Agno continue a gerar os schemas de ferramenta
    correctamente.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Capturar argumentos usando a assinatura original
        sig = inspect.signature(fn)
        try:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call_args = {k: v for k, v in bound.arguments.items() if k != "self"}
        except TypeError:
            call_args = {}

        result = fn(*args, **kwargs)

        try:
            _tracker.log_tool(fn.__name__, call_args, str(result))
        except Exception as exc:
            logger.warning("[XAI] Erro ao registar ferramenta %s: %s", fn.__name__, exc)

        return result

    return wrapper

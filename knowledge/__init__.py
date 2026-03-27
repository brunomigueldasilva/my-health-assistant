"""
RAG Knowledge Base — ChromaDB vector store for preferences,
nutritional information, and exercises.
"""

import logging
from typing import Optional

import chromadb
from chromadb.config import Settings

from config import CHROMA_DIR, CHROMA_COLLECTION_PREFERENCES, CHROMA_COLLECTION_NUTRITION, CHROMA_COLLECTION_EXERCISES

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
    Manages the ChromaDB vector store with 3 collections:
      - user_preferences: likes, dislikes, goals, health data
      - nutrition_knowledge: food info, calories, macros
      - exercise_knowledge: exercises, muscle groups, calories burned
    """

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        # Collections
        self.preferences = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_PREFERENCES,
            metadata={"hnsw:space": "cosine"},
        )
        self.nutrition = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_NUTRITION,
            metadata={"hnsw:space": "cosine"},
        )
        self.exercises = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_EXERCISES,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("KnowledgeBase initialised with ChromaDB at %s", CHROMA_DIR)

    # ── User preferences ────────────────────────────────

    def add_preference(
        self,
        user_id: str,
        category: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """Adds a preference to the vector store."""
        doc_id = f"{user_id}_{category}_{hash(text) % 10**8}"
        meta = {"user_id": user_id, "category": category}
        if metadata:
            meta.update(metadata)

        self.preferences.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[meta],
        )
        logger.info("Preference added: [%s] %s", category, text[:60])
        return doc_id

    def search_preferences(
        self, user_id: str, query: str, n_results: int = 5
    ) -> list[dict]:
        """Searches preferences for a given user."""
        results = self.preferences.query(
            query_texts=[query],
            n_results=n_results,
            where={"user_id": user_id},
        )
        formatted = self._format_results(results)
        try:
            from xai import get_tracker
            get_tracker().log_rag("user_preferences", query, formatted)
        except Exception:
            pass
        return formatted

    # ── Nutritional knowledge ───────────────────────────

    def add_nutrition_info(self, text: str, metadata: Optional[dict] = None) -> str:
        """Adds nutritional information to the knowledge base."""
        doc_id = f"nutrition_{hash(text) % 10**8}"
        meta = metadata or {}
        meta["type"] = "nutrition"

        self.nutrition.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
        return doc_id

    def search_nutrition(self, query: str, n_results: int = 5) -> list[dict]:
        """Searches nutritional information."""
        results = self.nutrition.query(
            query_texts=[query],
            n_results=n_results,
        )
        formatted = self._format_results(results)
        try:
            from xai import get_tracker
            get_tracker().log_rag("nutrition_knowledge", query, formatted)
        except Exception:
            pass
        return formatted

    # ── Exercise knowledge ──────────────────────────────

    def add_exercise_info(self, text: str, metadata: Optional[dict] = None) -> str:
        """Adds exercise information to the knowledge base."""
        doc_id = f"exercise_{hash(text) % 10**8}"
        meta = metadata or {}
        meta["type"] = "exercise"

        self.exercises.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
        return doc_id

    def search_exercises(self, query: str, n_results: int = 5) -> list[dict]:
        """Searches exercises."""
        results = self.exercises.query(
            query_texts=[query],
            n_results=n_results,
        )
        formatted = self._format_results(results)
        try:
            from xai import get_tracker
            get_tracker().log_rag("exercise_knowledge", query, formatted)
        except Exception:
            pass
        return formatted

    # ── Utilities ───────────────────────────────────────

    @staticmethod
    def _format_results(results: dict) -> list[dict]:
        """Converts ChromaDB results to a list of dicts."""
        formatted = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                entry = {
                    "text": doc,
                    "metadata": (
                        results["metadatas"][0][i] if results.get("metadatas") else {}
                    ),
                    "distance": (
                        results["distances"][0][i] if results.get("distances") else None
                    ),
                }
                formatted.append(entry)
        return formatted

    def get_user_profile_summary(self, user_id: str) -> str:
        """Generates a full summary of the user's profile."""
        sections = {
            "food_likes": "Alimentos que gosta",
            "food_dislikes": "Alimentos que não gosta",
            "allergies": "Alergias alimentares",
            "goals": "Objectivos de saúde",
            "health_data": "Dados de saúde",
            "restrictions": "Restrições alimentares",
        }

        summary_parts = []
        for category, label in sections.items():
            results = self.preferences.query(
                query_texts=[category],
                n_results=20,
                where={"$and": [{"user_id": user_id}, {"category": category}]},
            )
            if results and results["documents"] and results["documents"][0]:
                items = ", ".join(results["documents"][0])
                summary_parts.append(f"**{label}**: {items}")

        if not summary_parts:
            return "Perfil ainda sem informações. Use os comandos para adicionar preferências."

        return "\n".join(summary_parts)


# Singleton
_kb_instance: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Returns the KnowledgeBase singleton instance."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance

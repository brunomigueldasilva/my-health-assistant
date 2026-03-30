"""
Tests for knowledge/__init__.py (KnowledgeBase)

Uses an in-memory ChromaDB (EphemeralClient) to avoid touching disk.
The singleton is bypassed — each test gets a fresh KnowledgeBase instance.
"""

import pytest
import chromadb
from unittest.mock import patch, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def kb(tmp_path, monkeypatch):
    """
    KnowledgeBase backed by an isolated per-test ChromaDB directory.
    Monkeypatches CHROMA_DIR so each test starts with a clean slate.
    """
    import knowledge as kb_module
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    monkeypatch.setattr(kb_module, "CHROMA_DIR", chroma_dir)
    from knowledge import KnowledgeBase
    return KnowledgeBase()


# ── add_preference / search_preferences ──────────────────────────────────────

class TestPreferences:
    def test_add_preference_returns_doc_id(self, kb):
        doc_id = kb.add_preference("u1", "food_likes", "frango grelhado")
        assert "u1" in doc_id
        assert "food_likes" in doc_id

    def test_add_preference_doc_id_is_deterministic(self, kb):
        id1 = kb.add_preference("u1", "food_likes", "arroz")
        id2 = kb.add_preference("u1", "food_likes", "arroz")
        assert id1 == id2  # upsert — same hash

    def test_search_preferences_returns_added_item(self, kb):
        kb.add_preference("u1", "food_likes", "banana")
        results = kb.search_preferences("u1", "banana", n_results=5)
        texts = [r["text"] for r in results]
        assert any("banana" in t for t in texts)

    def test_search_preferences_filters_by_user_id(self, kb):
        kb.add_preference("u1", "food_likes", "maçã")
        kb.add_preference("u2", "food_likes", "laranja")
        results = kb.search_preferences("u1", "fruta", n_results=5)
        assert all(r["metadata"]["user_id"] == "u1" for r in results)

    def test_search_preferences_empty_returns_empty_list(self, kb):
        results = kb.search_preferences("no_such_user", "anything")
        assert results == []

    def test_add_preference_metadata_stored(self, kb):
        kb.add_preference("u1", "allergies", "amendoins", metadata={"severity": "high"})
        results = kb.search_preferences("u1", "amendoins")
        assert results[0]["metadata"]["severity"] == "high"

    def test_preference_result_has_distance_field(self, kb):
        kb.add_preference("u1", "food_likes", "tomate")
        results = kb.search_preferences("u1", "tomate")
        assert "distance" in results[0]


# ── add_nutrition_info / search_nutrition ─────────────────────────────────────

class TestNutrition:
    def test_add_nutrition_info_returns_doc_id(self, kb):
        doc_id = kb.add_nutrition_info("Frango: 165 kcal/100g, proteína 31g")
        assert doc_id.startswith("nutrition_")

    def test_add_nutrition_info_sets_type_metadata(self, kb):
        kb.add_nutrition_info("Ovo: 155 kcal/100g")
        results = kb.search_nutrition("ovo", n_results=5)
        assert results[0]["metadata"]["type"] == "nutrition"

    def test_search_nutrition_returns_added_item(self, kb):
        kb.add_nutrition_info("Aveia: 389 kcal/100g, fibra 10g")
        results = kb.search_nutrition("aveia", n_results=5)
        texts = [r["text"] for r in results]
        assert any("Aveia" in t for t in texts)

    def test_search_nutrition_empty_returns_empty_list(self, kb):
        results = kb.search_nutrition("produto_inexistente")
        assert results == []

    def test_add_nutrition_doc_id_is_deterministic(self, kb):
        id1 = kb.add_nutrition_info("Salmão: 208 kcal")
        id2 = kb.add_nutrition_info("Salmão: 208 kcal")
        assert id1 == id2

    def test_add_nutrition_accepts_custom_metadata(self, kb):
        kb.add_nutrition_info("Brócolo: 34 kcal", metadata={"source": "usda"})
        results = kb.search_nutrition("brócolo")
        assert results[0]["metadata"]["source"] == "usda"

    def test_search_nutrition_result_structure(self, kb):
        kb.add_nutrition_info("Quinoa: 120 kcal/100g")
        results = kb.search_nutrition("quinoa")
        assert len(results) > 0
        assert "text" in results[0]
        assert "metadata" in results[0]
        assert "distance" in results[0]


# ── add_exercise_info / search_exercises ──────────────────────────────────────

class TestExercises:
    def test_add_exercise_info_returns_doc_id(self, kb):
        doc_id = kb.add_exercise_info("Agachamento: quadríceps, glúteos, 6 MET")
        assert doc_id.startswith("exercise_")

    def test_add_exercise_info_sets_type_metadata(self, kb):
        kb.add_exercise_info("Flexão: peito, tríceps")
        results = kb.search_exercises("flexão")
        assert results[0]["metadata"]["type"] == "exercise"

    def test_search_exercises_returns_added_item(self, kb):
        kb.add_exercise_info("Corrida: cardiovascular, 8 MET")
        results = kb.search_exercises("corrida", n_results=5)
        texts = [r["text"] for r in results]
        assert any("Corrida" in t for t in texts)

    def test_search_exercises_empty_returns_empty_list(self, kb):
        results = kb.search_exercises("exercicio_inexistente")
        assert results == []

    def test_add_exercise_doc_id_is_deterministic(self, kb):
        id1 = kb.add_exercise_info("Natação: 7 MET")
        id2 = kb.add_exercise_info("Natação: 7 MET")
        assert id1 == id2

    def test_search_exercises_result_structure(self, kb):
        kb.add_exercise_info("Yoga: flexibilidade, 3 MET")
        results = kb.search_exercises("yoga")
        assert len(results) > 0
        assert "text" in results[0]
        assert "metadata" in results[0]
        assert "distance" in results[0]


# ── _format_results ───────────────────────────────────────────────────────────

class TestFormatResults:
    def test_empty_results_returns_empty_list(self):
        from knowledge import KnowledgeBase
        assert KnowledgeBase._format_results({}) == []
        assert KnowledgeBase._format_results({"documents": [[]]}) == []

    def test_formats_single_result(self):
        from knowledge import KnowledgeBase
        raw = {
            "documents": [["texto exemplo"]],
            "metadatas": [[{"user_id": "u1"}]],
            "distances": [[0.12]],
        }
        result = KnowledgeBase._format_results(raw)
        assert len(result) == 1
        assert result[0]["text"] == "texto exemplo"
        assert result[0]["metadata"]["user_id"] == "u1"
        assert result[0]["distance"] == pytest.approx(0.12)

    def test_formats_multiple_results(self):
        from knowledge import KnowledgeBase
        raw = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"k": "v1"}, {"k": "v2"}]],
            "distances": [[0.1, 0.2]],
        }
        result = KnowledgeBase._format_results(raw)
        assert len(result) == 2
        assert result[1]["text"] == "doc2"

    def test_handles_missing_metadatas(self):
        from knowledge import KnowledgeBase
        raw = {"documents": [["doc1"]]}
        result = KnowledgeBase._format_results(raw)
        assert result[0]["metadata"] == {}

    def test_handles_missing_distances(self):
        from knowledge import KnowledgeBase
        raw = {
            "documents": [["doc1"]],
            "metadatas": [[{}]],
        }
        result = KnowledgeBase._format_results(raw)
        assert result[0]["distance"] is None


# ── get_user_profile_summary ──────────────────────────────────────────────────

class TestGetUserProfileSummary:
    def test_empty_profile_returns_default_message(self, kb):
        result = kb.get_user_profile_summary("new_user")
        assert "Perfil ainda sem informações" in result

    def test_returns_food_likes_section(self, kb):
        kb.add_preference("u1", "food_likes", "frango assado")
        result = kb.get_user_profile_summary("u1")
        assert "Alimentos que gosta" in result
        assert "frango assado" in result

    def test_returns_allergies_section(self, kb):
        kb.add_preference("u1", "allergies", "glúten")
        result = kb.get_user_profile_summary("u1")
        assert "Alergias alimentares" in result
        assert "glúten" in result

    def test_multiple_categories_shown(self, kb):
        kb.add_preference("u1", "food_likes", "peixe")
        kb.add_preference("u1", "food_dislikes", "fígado")
        kb.add_preference("u1", "goals", "perder peso")
        result = kb.get_user_profile_summary("u1")
        assert "Alimentos que gosta" in result
        assert "Alimentos que não gosta" in result
        assert "Objetivos de saúde" in result

    def test_does_not_include_other_users_data(self, kb):
        kb.add_preference("u1", "food_likes", "sopa")
        kb.add_preference("u2", "food_likes", "pizza")
        result = kb.get_user_profile_summary("u1")
        assert "pizza" not in result


# ── get_knowledge_base singleton ──────────────────────────────────────────────

class TestGetKnowledgeBaseSingleton:
    def test_returns_same_instance(self):
        import knowledge as kb_module
        # Reset singleton to ensure a fresh call
        original = kb_module._kb_instance
        try:
            kb_module._kb_instance = None
            with patch("knowledge.chromadb.PersistentClient", return_value=chromadb.EphemeralClient()):
                inst1 = kb_module.get_knowledge_base()
                inst2 = kb_module.get_knowledge_base()
            assert inst1 is inst2
        finally:
            kb_module._kb_instance = original

"""
Shared pytest fixtures for MyHealthAssistant test suite.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def reset_xai_tracker():
    """Reset the global XAI tracker before and after every test."""
    from xai import get_tracker
    get_tracker().reset()
    yield
    get_tracker().reset()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect SQLite profile DB to a temporary file for each test."""
    db_path = tmp_path / "test_profiles.db"
    monkeypatch.setattr("tools.profile_tools.SQLITE_DB", db_path)
    return db_path


@pytest.fixture
def tmp_db_tanita(tmp_path, monkeypatch):
    """Redirect SQLite tanita DB to a temporary file for each test."""
    db_path = tmp_path / "test_tanita.db"
    monkeypatch.setattr("tools.tanita_tools.SQLITE_DB", db_path)
    return db_path


@pytest.fixture
def mock_kb():
    """
    MagicMock that mimics KnowledgeBase.
    Returns empty results by default; override in each test as needed.
    """
    kb = MagicMock()
    kb.search_nutrition.return_value = []
    kb.search_exercises.return_value = []
    kb.search_preferences.return_value = []
    kb.get_user_profile_summary.return_value = "Sem preferências."
    kb.preferences.get.return_value = {"documents": [], "ids": []}
    return kb


@pytest.fixture
def mock_kb_nutrition(mock_kb, monkeypatch):
    """Patch get_knowledge_base in the nutrition tools module."""
    monkeypatch.setattr("tools.nutrition_tools.get_knowledge_base", lambda: mock_kb)
    return mock_kb


@pytest.fixture
def mock_kb_exercise(mock_kb, monkeypatch):
    """Patch get_knowledge_base in the exercise tools module."""
    monkeypatch.setattr("tools.exercise_tools.get_knowledge_base", lambda: mock_kb)
    return mock_kb


@pytest.fixture
def mock_kb_profile(mock_kb, monkeypatch):
    """Patch get_knowledge_base in the profile tools module."""
    monkeypatch.setattr("tools.profile_tools.get_knowledge_base", lambda: mock_kb)
    return mock_kb

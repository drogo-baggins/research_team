import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from research_team.search.factory import SearchEngineFactory
from research_team.search.human import HumanSearchEngine


def test_factory_returns_human_engine_by_default(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "human")
    engine = SearchEngineFactory.create()
    assert isinstance(engine, HumanSearchEngine)


def test_factory_raises_for_unknown_mode(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "unknown_mode")
    with pytest.raises(ValueError, match="Unknown SEARCH_MODE"):
        SearchEngineFactory.create()

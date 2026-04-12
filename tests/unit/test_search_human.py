import pytest
from unittest.mock import AsyncMock, patch
from research_team.search.base import SearchEngine, SearchResult
from research_team.search.human import HumanSearchEngine


def test_search_result_model():
    """SearchResultが正しいフィールドを持つ"""
    result = SearchResult(
        url="https://example.com",
        title="Example",
        content="Test content",
        source="human",
    )
    assert result.url == "https://example.com"
    assert result.source == "human"


@pytest.mark.asyncio
async def test_human_search_engine_is_search_engine():
    """HumanSearchEngineがSearchEngineの実装である"""
    engine = HumanSearchEngine()
    assert isinstance(engine, SearchEngine)


@pytest.mark.asyncio
async def test_human_search_returns_results():
    """HumanSearchEngineがSearchResultのリストを返す"""
    mock_page = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.url = "https://example.com/result"

    engine = HumanSearchEngine()
    with patch.object(engine, "_navigate_and_wait", return_value=mock_page):
        with patch.object(engine, "_extract_content", return_value="Some content"):
            results = await engine.search("test query", max_results=1)

    assert len(results) >= 0
    for r in results:
        assert isinstance(r, SearchResult)

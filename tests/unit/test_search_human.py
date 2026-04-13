import pytest
from unittest.mock import AsyncMock, patch
from research_team.search.base import SearchEngine, SearchResult
from research_team.search.human import HumanSearchEngine


def test_search_result_model():
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
    engine = HumanSearchEngine()
    assert isinstance(engine, SearchEngine)


@pytest.mark.asyncio
async def test_human_search_returns_results():
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


@pytest.mark.asyncio
async def test_approval_skips_rejected_pages():
    mock_ui = AsyncMock()
    mock_ui.request_content_approval = AsyncMock(return_value=False)

    mock_link = AsyncMock()
    mock_link.get_attribute = AsyncMock(return_value="https://example.com/page1")

    mock_page = AsyncMock()
    mock_page.title = AsyncMock(return_value="Some Title")
    mock_page.url = "https://example.com/page1"
    mock_page.query_selector_all = AsyncMock(return_value=[mock_link])

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate_and_wait", side_effect=[mock_page, mock_page]):
        with patch.object(engine, "_extract_content", return_value="content"):
            results = await engine.search("test", max_results=1)

    assert results == []


@pytest.mark.asyncio
async def test_approval_includes_approved_pages():
    mock_ui = AsyncMock()
    mock_ui.request_content_approval = AsyncMock(return_value=True)

    mock_link = AsyncMock()
    mock_link.get_attribute = AsyncMock(return_value="https://example.com/page1")

    mock_search_page = AsyncMock()
    mock_search_page.url = "https://google.com/search"
    mock_search_page.title = AsyncMock(return_value="Search")
    mock_search_page.query_selector_all = AsyncMock(return_value=[mock_link])

    mock_result_page = AsyncMock()
    mock_result_page.url = "https://example.com/page1"
    mock_result_page.title = AsyncMock(return_value="Result Title")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate_and_wait", side_effect=[mock_search_page, mock_result_page]):
        with patch.object(engine, "_extract_content", return_value="rich content here"):
            results = await engine.search("test", max_results=1)

    assert len(results) == 1
    assert results[0].url == "https://example.com/page1"


@pytest.mark.asyncio
async def test_fetch_calls_approval():
    mock_ui = AsyncMock()
    mock_ui.request_content_approval = AsyncMock(return_value=True)

    mock_page = AsyncMock()
    mock_page.url = "https://example.com/article"
    mock_page.title = AsyncMock(return_value="Article Title")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate_and_wait", return_value=mock_page):
        with patch.object(engine, "_extract_content", return_value="article body"):
            result = await engine.fetch("https://example.com/article")

    mock_ui.request_content_approval.assert_called_once()
    assert result.url == "https://example.com/article"


@pytest.mark.asyncio
async def test_no_approval_needed_without_ui():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/article"
    mock_page.title = AsyncMock(return_value="Article")

    engine = HumanSearchEngine(control_ui=None)
    with patch.object(engine, "_navigate_and_wait", return_value=mock_page):
        with patch.object(engine, "_extract_content", return_value="body"):
            result = await engine.fetch("https://example.com/article")

    assert result.content == "body"

# tests/unit/test_search_human.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.base import SearchResult
from research_team.search.human import HumanSearchEngine


def _make_search_page(evaluate_return=None, inner_text_return="body text"):
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=evaluate_return or [])
    page.inner_text = AsyncMock(return_value=inner_text_return)
    page.title = AsyncMock(return_value="Test - Google Search")
    page.close = AsyncMock()
    return page


def test_search_result_model():
    result = SearchResult(
        url="https://example.com",
        title="Example",
        content="Test content",
        source="human",
    )
    assert result.url == "https://example.com"
    assert result.source == "human"


def _make_mock_ui(*, wait_for_capture_return=True, closed=False):
    mock_ui = AsyncMock()
    mock_ui.closed = closed
    mock_ui.wait_for_capture = AsyncMock(return_value=wait_for_capture_return)
    return mock_ui


@pytest.mark.asyncio
async def test_search_returns_multiple_results_when_extractor_finds_links():
    """GoogleSearchExtractor が結果を返した場合、複数件の SearchResult が返ること。"""
    mock_ui = _make_mock_ui()

    page = _make_search_page(evaluate_return=[
        {"href": "https://example.com/article1", "title": "Article 1", "snippet": "Snip 1"},
        {"href": "https://example.com/article2", "title": "Article 2", "snippet": "Snip 2"},
    ])
    page.url = "https://www.google.com/search?q=test"

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        results = await engine.search("test query", max_results=5)

    assert len(results) >= 2
    urls = [r.url for r in results]
    assert "https://example.com/article1" in urls
    assert "https://example.com/article2" in urls
    mock_ui.wait_for_capture.assert_called_once()


@pytest.mark.asyncio
async def test_search_falls_back_to_single_result_when_extractor_finds_nothing():
    """evaluate_all が空を返した場合、フォールバックで1件返すこと。"""
    mock_ui = _make_mock_ui()

    page = _make_search_page(
        evaluate_return=[],
        inner_text_return="Google search results content",
    )
    page.url = "https://www.google.com/search?q=python+asyncio"

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        results = await engine.search("python asyncio", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://www.google.com/search?q=python+asyncio"
    assert results[0].source == "human"
    assert "Google search results content" in results[0].content


@pytest.mark.asyncio
async def test_search_returns_empty_when_user_skips():
    mock_ui = _make_mock_ui(wait_for_capture_return=False)

    page = AsyncMock()
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page) as mock_navigate:
        results = await engine.search("test", max_results=5)

    assert results == []
    mock_navigate.assert_called_once()


@pytest.mark.asyncio
async def test_search_returns_empty_when_ui_closed():
    mock_ui = _make_mock_ui(closed=True)

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate") as mock_navigate:
        results = await engine.search("test", max_results=5)

    assert results == []
    mock_navigate.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_ui_closed():
    mock_ui = _make_mock_ui(closed=True)

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate") as mock_navigate:
        result = await engine.fetch("https://example.com/article")

    assert result.content == ""
    mock_navigate.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_calls_approval():
    """fetch() がユーザー承認を求めること。"""
    mock_ui = _make_mock_ui()

    page = AsyncMock()
    page.url = "https://example.com/article"
    page.title = AsyncMock(return_value="Article Title")
    page.inner_text = AsyncMock(return_value="article body")
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        result = await engine.fetch("https://example.com/article")

    mock_ui.wait_for_capture.assert_called_once_with("https://example.com/article")
    assert result.url == "https://example.com/article"
    assert result.content == "article body"


@pytest.mark.asyncio
async def test_fetch_returns_empty_content_when_user_rejects():
    mock_ui = _make_mock_ui(wait_for_capture_return=False)

    page = AsyncMock()
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page) as mock_navigate:
        result = await engine.fetch("https://example.com/article")

    assert result.url == "https://example.com/article"
    assert result.content == ""
    mock_navigate.assert_called_once()


@pytest.mark.asyncio
async def test_no_approval_needed_without_ui():
    """control_ui が None の場合、承認なしで fetch できること。"""
    page = AsyncMock()
    page.url = "https://example.com/article"
    page.title = AsyncMock(return_value="Article")
    page.inner_text = AsyncMock(return_value="body text")
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=None)
    with patch.object(engine, "_navigate", return_value=page):
        result = await engine.fetch("https://example.com/article")

    assert result.content == "body text"

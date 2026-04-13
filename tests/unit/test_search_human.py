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
async def test_search_returns_search_results_page_as_single_result():
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=True)

    mock_search_page = AsyncMock()
    mock_search_page.url = "https://www.google.com/search?q=python+asyncio"
    mock_search_page.title = AsyncMock(return_value="python asyncio - Google Search")
    mock_search_page.inner_text = AsyncMock(return_value="Google search results content")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=mock_search_page):
        results = await engine.search("python asyncio", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://www.google.com/search?q=python+asyncio"
    assert results[0].source == "human"
    assert "Google search results content" in results[0].content
    mock_ui.wait_for_capture.assert_called_once_with("https://www.google.com/search?q=python+asyncio")


@pytest.mark.asyncio
async def test_search_returns_empty_when_user_skips_results_page():
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=False)

    mock_search_page = AsyncMock()
    mock_search_page.url = "https://www.google.com/search?q=test"
    mock_search_page.title = AsyncMock(return_value="test - Google Search")
    mock_search_page.inner_text = AsyncMock(return_value="some content")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=mock_search_page):
        results = await engine.search("test", max_results=5)

    assert results == []


@pytest.mark.asyncio
async def test_fetch_calls_approval():
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=True)

    mock_page = AsyncMock()
    mock_page.url = "https://example.com/article"
    mock_page.title = AsyncMock(return_value="Article Title")
    mock_page.inner_text = AsyncMock(return_value="article body")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=mock_page):
        result = await engine.fetch("https://example.com/article")

    mock_ui.wait_for_capture.assert_called_once_with("https://example.com/article")
    assert result.url == "https://example.com/article"
    assert result.content == "article body"


@pytest.mark.asyncio
async def test_fetch_returns_empty_content_when_user_rejects():
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=False)

    mock_page = AsyncMock()
    mock_page.url = "https://example.com/article"
    mock_page.title = AsyncMock(return_value="Article")

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=mock_page):
        result = await engine.fetch("https://example.com/article")

    assert result.url == "https://example.com/article"
    assert result.content == ""


@pytest.mark.asyncio
async def test_no_approval_needed_without_ui():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/article"
    mock_page.title = AsyncMock(return_value="Article")
    mock_page.inner_text = AsyncMock(return_value="body text")

    engine = HumanSearchEngine(control_ui=None)
    with patch.object(engine, "_navigate", return_value=mock_page):
        result = await engine.fetch("https://example.com/article")

    assert result.content == "body text"


class TestHumanSearchEngineSearchParsed:
    @pytest.mark.asyncio
    async def test_search_returns_multiple_results_when_parser_finds_links(self):
        mock_html = (
            'Title1 /url?q=https://example.com/article1&sa=U snippet1 '
            '/url?q=https://example.com/article2&sa=U snippet2'
        )

        engine = HumanSearchEngine()

        mock_page = AsyncMock()
        mock_page.url = "https://www.google.com/search?q=test"
        mock_page.inner_text = AsyncMock(return_value=mock_html)
        mock_page.title = AsyncMock(return_value="test - Google Search")
        mock_page.close = AsyncMock()

        with patch.object(engine, "_navigate", return_value=mock_page):
            results = await engine.search("test query", max_results=5)

        assert len(results) >= 2
        urls = [r.url for r in results]
        assert "https://example.com/article1" in urls
        assert "https://example.com/article2" in urls

    @pytest.mark.asyncio
    async def test_search_falls_back_to_single_result_when_parser_finds_nothing(self):
        mock_html = "検索結果が見つかりませんでした"

        engine = HumanSearchEngine()

        mock_page = AsyncMock()
        mock_page.url = "https://www.google.com/search?q=test"
        mock_page.inner_text = AsyncMock(return_value=mock_html)
        mock_page.title = AsyncMock(return_value="test - Google Search")
        mock_page.close = AsyncMock()

        with patch.object(engine, "_navigate", return_value=mock_page):
            results = await engine.search("test query", max_results=5)

        assert len(results) == 1
        assert results[0].source == "human"

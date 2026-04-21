import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.serper import SerperSearchEngine, _html_to_text
from research_team.search.factory import SearchEngineFactory


def test_html_to_text_extracts_body_text():
    html = "<html><body><p>Hello world</p></body></html>"
    assert "Hello world" in _html_to_text(html)


def test_html_to_text_skips_script_and_style():
    html = "<html><head><style>body{color:red}</style></head><body><script>var x=1;</script><p>Content</p></body></html>"
    text = _html_to_text(html)
    assert "Content" in text
    assert "color:red" not in text
    assert "var x=1" not in text


def test_html_to_text_empty():
    assert _html_to_text("") == ""


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    return SerperSearchEngine()


@pytest.mark.asyncio
async def test_search_returns_results(engine):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "organic": [
            {"title": "Title 1", "link": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Title 2", "link": "https://example.com/2", "snippet": "Snippet 2"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=mock_client):
        results = await engine.search("test query", max_results=2)

    assert len(results) == 2
    assert results[0].url == "https://example.com/1"
    assert results[0].title == "Title 1"
    assert results[0].content == "Snippet 1"
    assert results[0].source == "serper"


@pytest.mark.asyncio
async def test_search_sends_locale_params(engine):
    engine.set_preferred_locales(["ja"])
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"organic": []}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=mock_client):
        await engine.search("クエリ")

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
    assert payload["gl"] == "jp"
    assert payload["hl"] == "ja"


@pytest.mark.asyncio
async def test_search_truncates_to_max_results(engine):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "organic": [
            {"title": f"T{i}", "link": f"https://example.com/{i}", "snippet": "s"}
            for i in range(10)
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=mock_client):
        results = await engine.search("q", max_results=3)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_fetch_via_scraper_html_response(engine):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body><p>Page content</p></body></html>"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=mock_client):
        result = await engine.fetch("https://example.com/page")

    assert result.url == "https://example.com/page"
    assert "Page content" in result.content
    assert result.source == "serper"


@pytest.mark.asyncio
async def test_fetch_via_scraper_json_response(engine):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"text": "Extracted text content"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=mock_client):
        result = await engine.fetch("https://example.com/page")

    assert "Extracted text content" in result.content


@pytest.mark.asyncio
async def test_fetch_falls_back_to_direct_on_scraper_failure(engine):
    scraper_response = MagicMock()
    scraper_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "503", request=MagicMock(), response=MagicMock()
    ))

    direct_response = MagicMock()
    direct_response.raise_for_status = MagicMock()
    direct_response.text = "<html><body><p>Fallback content</p></body></html>"

    call_count = 0

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return scraper_response

        async def get(self, *args, **kwargs):
            return direct_response

    with patch("research_team.search.serper.httpx.AsyncClient", return_value=MockClient()):
        result = await engine.fetch("https://example.com/page")

    assert "Fallback content" in result.content
    assert result.source == "serper-direct"


def test_factory_creates_serper_engine(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "serper")
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    engine = SearchEngineFactory.create()
    assert isinstance(engine, SerperSearchEngine)

# tests/unit/test_google_extractor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from research_team.search.google_extractor import GoogleSearchExtractor
from research_team.search.base import SearchResult


JS_RESULT_DIRECT = [
    {"href": "https://example.com/article1", "title": "Article 1", "snippet": "Snippet 1"},
    {"href": "https://example.com/article2", "title": "Article 2", "snippet": "Snippet 2"},
    {"href": "https://maps.google.com/maps",  "title": "Google Maps", "snippet": ""},
    {"href": "https://example.com/article3", "title": "Article 3", "snippet": "Snippet 3"},
    {"href": "https://example.com/article4", "title": "Article 4", "snippet": "Snippet 4"},
    {"href": "https://example.com/article5", "title": "Article 5", "snippet": "Snippet 5"},
]

JS_RESULT_REDIRECT = [
    {"href": "https://www.google.com/url?q=https://example.com/article1&sa=U", "title": "Article 1", "snippet": "Snippet 1"},
    {"href": "https://www.google.com/url?q=https://example.com/article2&sa=U", "title": "Article 2", "snippet": "Snippet 2"},
]


def _make_page(js_return_value):
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=js_return_value)
    return page


class TestGoogleSearchExtractor:

    @pytest.mark.asyncio
    async def test_extract_returns_list_of_search_results(self):
        page = _make_page(JS_RESULT_DIRECT[:2])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].url == "https://example.com/article1"
        assert results[0].title == "Article 1"
        assert results[0].content == "Snippet 1"
        assert results[0].source == "human"

    @pytest.mark.asyncio
    async def test_extract_handles_direct_urls(self):
        page = _make_page([
            {"href": "https://example.com/target?id=1", "title": "Target", "snippet": "desc"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/target?id=1"

    @pytest.mark.asyncio
    async def test_extract_resolves_google_redirect_urls(self):
        page = _make_page([
            {"href": "https://www.google.com/url?q=https://example.com/target%3Fid%3D1&sa=U",
             "title": "Target", "snippet": "desc"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/target?id=1"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_own_urls(self):
        page = _make_page(JS_RESULT_DIRECT)
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=10)

        urls = [r.url for r in results]
        assert not any("google.com" in u for u in urls)

    @pytest.mark.asyncio
    async def test_extract_respects_max_results(self):
        page = _make_page(JS_RESULT_DIRECT)
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_extract_returns_empty_on_evaluate_error(self):
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=Exception("DOM error"))

        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_extract_returns_empty_when_no_results(self):
        page = _make_page([])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_extract_handles_url_query_param_fallback(self):
        page = _make_page([
            {"href": "https://www.google.com/url?url=https://example.com/fallback&sa=U", "title": "Fallback", "snippet": ""},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/fallback"

    @pytest.mark.asyncio
    async def test_extract_drops_non_http_urls(self):
        page = _make_page([
            {"href": "ftp://example.com/file", "title": "FTP", "snippet": ""},
            {"href": "https://example.com/valid", "title": "Valid", "snippet": "ok"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/valid"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_subdomain(self):
        page = _make_page([
            {"href": "https://news.google.com/story", "title": "Google News", "snippet": ""},
            {"href": "https://example.com/ok", "title": "OK", "snippet": "fine"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/ok"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_redirect_to_google_domain(self):
        page = _make_page([
            {"href": "https://www.google.com/url?q=https://maps.google.com/target&sa=U",
             "title": "Should be excluded", "snippet": ""},
            {"href": "https://example.com/valid", "title": "Valid", "snippet": "ok"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        urls = [r.url for r in results]
        assert "https://maps.google.com/target" not in urls
        assert "https://example.com/valid" in urls

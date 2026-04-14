# tests/unit/test_google_extractor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from research_team.search.google_extractor import GoogleSearchExtractor
from research_team.search.base import SearchResult


JS_RESULT = [
    {"href": "/url?q=https://example.com/article1&sa=U", "title": "Article 1", "snippet": "Snippet 1"},
    {"href": "/url?q=https://example.com/article2&sa=U", "title": "Article 2", "snippet": "Snippet 2"},
    {"href": "/url?q=https://google.com/maps&sa=U",      "title": "Google Maps", "snippet": ""},
    {"href": "/url?q=https://example.com/article3&sa=U", "title": "Article 3", "snippet": "Snippet 3"},
    {"href": "/url?q=https://example.com/article4&sa=U", "title": "Article 4", "snippet": "Snippet 4"},
    {"href": "/url?q=https://example.com/article5&sa=U", "title": "Article 5", "snippet": "Snippet 5"},
]


def _make_page(js_return_value):
    """evaluate_all が js_return_value を返す Page モック。"""
    locator = MagicMock()
    locator.evaluate_all = AsyncMock(return_value=js_return_value)
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    return page


class TestGoogleSearchExtractor:

    @pytest.mark.asyncio
    async def test_extract_returns_list_of_search_results(self):
        """evaluate_all の結果を SearchResult に変換して返すこと。"""
        page = _make_page(JS_RESULT[:2])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].url == "https://example.com/article1"
        assert results[0].title == "Article 1"
        assert results[0].content == "Snippet 1"
        assert results[0].source == "human"

    @pytest.mark.asyncio
    async def test_extract_resolves_google_redirect_urls(self):
        """/url?q= 形式のリダイレクトを実際の URL に解決すること。"""
        page = _make_page([
            {"href": "/url?q=https://example.com/target%3Fid%3D1&sa=U",
             "title": "Target", "snippet": "desc"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/target?id=1"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_own_urls(self):
        """google.com ドメインの URL を除外すること。"""
        page = _make_page(JS_RESULT)  # google.com/maps が含まれる
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=10)

        urls = [r.url for r in results]
        assert not any("google.com" in u for u in urls)

    @pytest.mark.asyncio
    async def test_extract_respects_max_results(self):
        """max_results を超えた結果を返さないこと。"""
        page = _make_page(JS_RESULT)  # 6件（google除外で5件）
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_extract_returns_empty_on_evaluate_error(self):
        """evaluate_all が例外を投げた場合は空リストを返すこと。"""
        locator = MagicMock()
        locator.evaluate_all = AsyncMock(side_effect=Exception("DOM error"))
        page = MagicMock()
        page.locator = MagicMock(return_value=locator)

        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_extract_returns_empty_when_no_results(self):
        """JS が空リストを返した場合は空リストを返すこと。"""
        page = _make_page([])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_extract_handles_url_query_param_fallback(self):
        """/url?url= 形式も解決できること。"""
        page = _make_page([
            {"href": "/url?url=https://example.com/fallback&sa=U", "title": "Fallback", "snippet": ""},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/fallback"

    @pytest.mark.asyncio
    async def test_extract_drops_non_http_urls(self):
        """http/https 以外のスキームを除外すること。"""
        page = _make_page([
            {"href": "/url?q=ftp://example.com/file&sa=U", "title": "FTP", "snippet": ""},
            {"href": "/url?q=https://example.com/valid&sa=U", "title": "Valid", "snippet": "ok"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/valid"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_subdomain(self):
        """google.com のサブドメインも除外すること。"""
        page = _make_page([
            {"href": "/url?q=https://news.google.com/story&sa=U", "title": "Google News", "snippet": ""},
            {"href": "/url?q=https://example.com/ok&sa=U", "title": "OK", "snippet": "fine"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/ok"

    @pytest.mark.asyncio
    async def test_extract_does_not_resolve_absolute_google_redirect(self):
        """絶対形式 https://www.google.com/url?... は除外されること。
    
        ロケーター a[href^="/url?"] は相対形式のみにマッチするため、
        絶対形式の href はそもそも evaluate_all に渡らない。
        万が一渡ってきた場合は http/https で始まるが /url? で始まらないため
        _resolve_url が空文字列を返し除外される。
        """
        page = _make_page([
            {"href": "https://www.google.com/url?q=https://example.com/target&sa=U",
             "title": "Should be excluded", "snippet": ""},
            {"href": "/url?q=https://example.com/valid&sa=U", "title": "Valid", "snippet": "ok"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)
        urls = [r.url for r in results]
        assert "https://example.com/target" not in urls
        assert "https://example.com/valid" in urls

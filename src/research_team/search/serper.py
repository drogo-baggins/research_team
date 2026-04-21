import os
import logging
from html.parser import HTMLParser
import httpx
from research_team.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

_SERPER_SEARCH_URL = "https://google.serper.dev/search"
_SERPER_SCRAPE_URL = "https://scraper.serper.dev"

_LOCALE_PARAMS: dict[str, dict[str, str]] = {
    "ja": {"gl": "jp", "hl": "ja"},
    "zh": {"gl": "cn", "hl": "zh-cn"},
    "ko": {"gl": "kr", "hl": "ko"},
    "en": {"gl": "us", "hl": "en"},
    "de": {"gl": "de", "hl": "de"},
    "fr": {"gl": "fr", "hl": "fr"},
}


class _TextExtractor(HTMLParser):
    """Extract readable text from HTML, skipping scripts and styles."""

    _SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


class SerperSearchEngine(SearchEngine):

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self._api_key = api_key or os.environ["SERPER_API_KEY"]
        self._timeout = timeout or float(os.environ.get("RT_SERPER_TIMEOUT_SEC", "30"))
        self._preferred_locales: list[str] = ["ja", "en"]

    def set_preferred_locales(self, locales: list[str]) -> None:
        self._preferred_locales = locales

    def _locale_params(self) -> dict[str, str]:
        for locale in self._preferred_locales:
            if locale in _LOCALE_PARAMS:
                return _LOCALE_PARAMS[locale]
        return _LOCALE_PARAMS["en"]

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        payload: dict = {"q": query, "num": max_results, **self._locale_params()}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(_SERPER_SEARCH_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("organic", [])[:max_results]:
            results.append(
                SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    content=item.get("snippet", ""),
                    source="serper",
                )
            )
        return results

    async def fetch(self, url: str) -> SearchResult:
        try:
            return await self._fetch_via_scraper(url)
        except Exception as exc:
            logger.warning("Serper scraper failed for %s (%s), falling back to direct GET", url, exc)
            return await self._fetch_direct(url)

    async def _fetch_via_scraper(self, url: str) -> SearchResult:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(_SERPER_SCRAPE_URL, json={"url": url}, headers=self._headers())
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                text = data.get("text") or _html_to_text(data.get("html", ""))
            else:
                text = _html_to_text(resp.text)

        return SearchResult(url=url, title="", content=text, source="serper")

    async def _fetch_direct(self, url: str) -> SearchResult:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; research-team/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = _html_to_text(resp.text)

        return SearchResult(url=url, title="", content=text, source="serper-direct")

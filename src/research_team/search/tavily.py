import os
import httpx
from research_team.search.base import SearchEngine, SearchResult


class TavilySearchEngine(SearchEngine):
    """Tavily Search API を使った自動検索エンジン"""

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ["TAVILY_API_KEY"]

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.BASE_URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_raw_content": True,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            SearchResult(
                url=r["url"],
                title=r.get("title", ""),
                content=r.get("raw_content") or r.get("content", ""),
                source="tavily",
            )
            for r in data.get("results", [])
        ]

    async def fetch(self, url: str) -> SearchResult:
        """Tavilyのextract APIでURLコンテンツを取得"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.tavily.com/extract",
                json={"api_key": self._api_key, "urls": [url]},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        result = data.get("results", [{}])[0]
        return SearchResult(
            url=url,
            title=result.get("title", ""),
            content=result.get("raw_content", ""),
            source="tavily",
        )

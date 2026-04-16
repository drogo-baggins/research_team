import logging
import os
from urllib.parse import urlparse

from aiohttp import web
from research_team.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _extract_domain(url: str) -> str:
    """URL からドメイン（www. 除去済み）を返す。パース失敗時は空文字列。"""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


class SearchServer:
    def __init__(self, engine: SearchEngine) -> None:
        self._engine = engine
        self._app = web.Application()
        self._app.router.add_get("/search", self._handle_search)
        self._app.router.add_get("/fetch", self._handle_fetch)
        self._runner: web.AppRunner | None = None
        self.port: int = 0

        domain_limit = int(os.environ.get("RT_DOMAIN_FETCH_LIMIT", "10"))
        self._domain_limit = domain_limit

        self._search_cache: dict[str, list[dict]] = {}
        self._fetch_cache: dict[str, dict] = {}
        self._domain_fetch_counts: dict[str, int] = {}

    async def start(self) -> int:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_search(self, request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        max_results = int(request.query.get("max", "5"))
        key = _normalize_query(query)

        if key in self._search_cache:
            logger.debug("SearchServer: search cache hit for query=%r", query)
            return web.json_response(self._search_cache[key])

        try:
            results = await self._engine.search(query, max_results=max_results)
            serialized = [r.model_dump() for r in results]
            self._search_cache[key] = serialized
            return web.json_response(serialized)
        except Exception as exc:
            logger.exception("SearchServer._handle_search error: query=%r", query)
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_fetch(self, request: web.Request) -> web.Response:
        url = request.query.get("url", "")

        if url in self._fetch_cache:
            logger.debug("SearchServer: fetch cache hit for url=%r", url)
            return web.json_response(self._fetch_cache[url])

        domain = _extract_domain(url)
        if domain:
            count = self._domain_fetch_counts.get(domain, 0)
            if count >= self._domain_limit:
                logger.info(
                    "SearchServer: domain fetch limit reached (domain=%r, limit=%d), returning cached stub",
                    domain,
                    self._domain_limit,
                )
                stub = SearchResult(
                    url=url,
                    title="",
                    content=f"[このドメイン（{domain}）はセッション内fetch上限（{self._domain_limit}回）に達したためスキップされました]",
                    source="dedup",
                ).model_dump()
                return web.json_response(stub)
            self._domain_fetch_counts[domain] = count + 1

        try:
            result = await self._engine.fetch(url)
            self._fetch_cache[url] = result.model_dump()
            return web.json_response(self._fetch_cache[url])
        except Exception as exc:
            logger.exception("SearchServer._handle_fetch error: url=%r", url)
            return web.json_response({"error": str(exc)}, status=500)

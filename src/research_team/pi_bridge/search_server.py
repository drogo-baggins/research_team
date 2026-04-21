import asyncio
import logging
import os
from urllib.parse import urlparse

from aiohttp import web
from research_team.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _extract_domain(url: str) -> str:
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

        self._pending_searches: dict[str, asyncio.Task[list[dict]]] = {}
        self._pending_fetches: dict[str, asyncio.Task[dict]] = {}

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

    async def _run_search(self, key: str, query: str, max_results: int) -> list[dict]:
        results = await self._engine.search(query, max_results=max_results)
        serialized = [r.model_dump() for r in results]
        self._search_cache[key] = serialized
        self._pending_searches.pop(key, None)
        return serialized

    async def _handle_search(self, request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        max_results = int(request.query.get("max", "5"))
        key = _normalize_query(query)

        if key in self._search_cache:
            logger.debug("SearchServer: search cache hit for query=%r", query)
            return web.json_response(self._search_cache[key])

        if key not in self._pending_searches:
            task: asyncio.Task[list[dict]] = asyncio.create_task(
                self._run_search(key, query, max_results)
            )
            self._pending_searches[key] = task

        try:
            serialized = await asyncio.shield(self._pending_searches[key])
            return web.json_response(serialized)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SearchServer._handle_search error: query=%r", query)
            self._pending_searches.pop(key, None)
            return web.json_response({"error": "search failed"}, status=500)

    async def _run_fetch(self, url: str) -> dict:
        result = await self._engine.fetch(url)
        serialized = result.model_dump()
        self._fetch_cache[url] = serialized
        self._pending_fetches.pop(url, None)
        return serialized

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

        if url not in self._pending_fetches:
            fetch_task: asyncio.Task[dict] = asyncio.create_task(self._run_fetch(url))
            self._pending_fetches[url] = fetch_task

        try:
            serialized = await asyncio.shield(self._pending_fetches[url])
            return web.json_response(serialized)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SearchServer._handle_fetch error: url=%r", url)
            self._pending_fetches.pop(url, None)
            return web.json_response({"error": "fetch failed"}, status=500)

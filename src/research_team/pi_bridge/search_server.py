import asyncio
from aiohttp import web
from research_team.search.base import SearchEngine


class SearchServer:
    def __init__(self, engine: SearchEngine) -> None:
        self._engine = engine
        self._lock = asyncio.Lock()
        self._app = web.Application()
        self._app.router.add_get("/search", self._handle_search)
        self._app.router.add_get("/fetch", self._handle_fetch)
        self._runner: web.AppRunner | None = None
        self.port: int = 0

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
        async with self._lock:
            query = request.query.get("q", "")
            max_results = int(request.query.get("max", "5"))
            results = await self._engine.search(query, max_results=max_results)
            return web.json_response([r.model_dump() for r in results])

    async def _handle_fetch(self, request: web.Request) -> web.Response:
        async with self._lock:
            url = request.query.get("url", "")
            result = await self._engine.fetch(url)
            return web.json_response(result.model_dump())

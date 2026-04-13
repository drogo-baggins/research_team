import asyncio
import threading
import pytest
from aiohttp import web


async def _make_dummy_app() -> web.Application:
    app = web.Application()

    async def search_handler(request: web.Request) -> web.Response:
        query = request.query.get("q", "test")
        host = request.host
        html = (
            "<!DOCTYPE html><html><body>"
            f"<h1>Search: {query}</h1>"
            f'<a href="http://{host}/page/1">Result 1</a>'
            f'<a href="http://{host}/page/2">Result 2</a>'
            "</body></html>"
        )
        return web.Response(text=html, content_type="text/html")

    async def page_handler(request: web.Request) -> web.Response:
        page_id = request.match_info.get("id", "0")
        html = (
            "<!DOCTYPE html>"
            f"<html><head><title>Test Page {page_id}</title></head><body>"
            f"<h1>Test Content {page_id}</h1>"
            f"<p>This is dummy content for page {page_id}. Lorem ipsum dolor sit amet.</p>"
            "</body></html>"
        )
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/search", search_handler)
    app.router.add_get("/page/{id}", page_handler)
    return app


@pytest.fixture(scope="session")
def dummy_search_server():
    loop = asyncio.new_event_loop()
    runner_holder: list[web.AppRunner] = []
    port_holder: list[int] = []
    stop_event = asyncio.Event()
    ready = threading.Event()

    def run() -> None:
        async def _start() -> None:
            app = await _make_dummy_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            runner_holder.append(runner)
            port_holder.append(port)
            ready.set()
            await stop_event.wait()
            await runner.cleanup()

        loop.run_until_complete(_start())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(timeout=10)

    port = port_holder[0]
    yield f"http://127.0.0.1:{port}/search?q="

    loop.call_soon_threadsafe(stop_event.set)
    t.join(timeout=5)

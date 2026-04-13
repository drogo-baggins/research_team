import asyncio
import sys
from aiohttp import web

DEFAULT_PORT = 8765


def _build_app() -> web.Application:
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


async def _run(port: int) -> None:
    app = _build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    actual_port = site._server.sockets[0].getsockname()[1]
    print(f"http://127.0.0.1:{actual_port}/search?q=", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    asyncio.run(_run(port))

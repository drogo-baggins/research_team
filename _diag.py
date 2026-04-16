import asyncio
import os
from aiohttp import web
from playwright.async_api import async_playwright
from research_team.ui.control_ui import ControlUI
from research_team.orchestrator.coordinator import ResearchCoordinator

HTML = "<html><body><a href='http://127.0.0.1:9876/p'>x</a></body></html>"


async def main():
    app = web.Application()

    async def handler(req):
        return web.Response(text=HTML, content_type="text/html")

    app.router.add_get("/search", handler)
    app.router.add_get("/p", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9876)
    await site.start()
    os.environ["SEARCH_ENGINE_URL"] = "http://127.0.0.1:9876/search?q="
    print("dummy server up on 9876")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ui = ControlUI(browser)
        print("starting UI...")
        await ui.start()
        print("UI started OK")

        async def _auto(url, title):
            print(f"  approval called: {url}")
            return True

        ui.request_content_approval = _auto
        coordinator = ResearchCoordinator(workspace_dir="/tmp/ws", ui=ui)

        async def inject():
            await asyncio.sleep(0.5)
            print("injecting topic...")
            await ui._chat_queue.put("Pythonとは")
            print("topic injected")

        asyncio.create_task(inject())
        print("calling run_interactive...")
        try:
            await asyncio.wait_for(coordinator.run_interactive(depth="quick"), timeout=60)
            print("DONE")
        except asyncio.TimeoutError:
            print("TIMEOUT after 60s")
        except Exception as e:
            import traceback
            print(f"ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
        await ui.close()
    await runner.cleanup()


asyncio.run(main())

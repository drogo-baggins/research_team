import asyncio
import os
import sys
import time
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()

async def main():
    from aiohttp import web
    
    app = web.Application()
    async def search_handler(request):
        query = request.query.get("q", "test")
        host = request.host
        html = f"<html><body><h1>Search: {query}</h1><a href='http://{host}/page/1'>Result 1</a></body></html>"
        return web.Response(text=html, content_type="text/html")
    async def page_handler(request):
        pid = request.match_info.get("id", "0")
        html = f"<html><head><title>Test Page {pid}</title></head><body><h1>Test Content {pid}</h1><p>Python is a programming language. Lorem ipsum.</p></body></html>"
        return web.Response(text=html, content_type="text/html")
    app.router.add_get("/search", search_handler)
    app.router.add_get("/page/{id}", page_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    dummy_url = f"http://127.0.0.1:{port}/search?q="
    print(f"Dummy server at {dummy_url} | Model: {os.environ.get('PI_MODEL')}", flush=True)
    
    os.environ["SEARCH_ENGINE_URL"] = dummy_url
    os.environ["SEARCH_MODE"] = "human"
    
    from playwright.async_api import async_playwright
    from research_team.ui.control_ui import ControlUI
    from research_team.orchestrator.coordinator import ResearchCoordinator

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ui = ControlUI(browser)
        await ui.start()
        
        approval_calls = []
        async def _auto_approve(url, title):
            print(f"AUTO-APPROVE: {url}", flush=True)
            approval_calls.append((url, title))
            return True
        
        ui.request_content_approval = _auto_approve
        
        coordinator = ResearchCoordinator(workspace_dir="C:/tmp/test_ws2", ui=ui)
        
        async def _inject_topic():
            await asyncio.sleep(0.2)
            await ui._chat_queue.put("Python")
        
        asyncio.create_task(_inject_topic())
        t0 = time.time()
        print("Starting run_interactive...", flush=True)
        try:
            await asyncio.wait_for(coordinator.run_interactive(depth="quick"), timeout=180)
            print(f"DONE in {time.time()-t0:.1f}s, approvals={len(approval_calls)}", flush=True)
        except asyncio.TimeoutError:
            print(f"TIMEOUT after {time.time()-t0:.1f}s, approvals={len(approval_calls)}", flush=True)
        except Exception as e:
            print(f"ERROR after {time.time()-t0:.1f}s: {type(e).__name__}: {e}", flush=True)
        
        await ui.close()
        await browser.close()
    
    await runner.cleanup()

asyncio.run(main())

import asyncio
import json
from pathlib import Path
from playwright.async_api import Browser, BrowserContext, Page


_HTML_PATH = Path(__file__).parent / "control_page.html"


class ControlUI:
    def __init__(self, browser: Browser):
        self._browser = browser
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._chat_queue: asyncio.Queue[str] = asyncio.Queue()
        self._captcha_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._page.expose_binding("__rt_signal", self._handle_signal)
        await self._page.goto(_HTML_PATH.as_uri())

    async def _handle_signal(self, source: dict, payload: dict) -> None:
        match payload.get("type"):
            case "chat":
                await self._chat_queue.put(payload.get("message", ""))
            case "captcha_done":
                self._captcha_event.set()

    async def append_agent_message(self, sender: str, text: str) -> None:
        safe_sender = json.dumps(sender)
        safe_text = json.dumps(text)
        await self._page.evaluate(f"appendMessage({safe_sender}, {safe_text}, false)")

    async def append_log(self, status: str, text: str) -> None:
        safe_status = json.dumps(status)
        safe_text = json.dumps(text)
        await self._page.evaluate(f"appendLog({safe_status}, {safe_text})")

    async def wait_for_user_message(self) -> str:
        return await self._chat_queue.get()

    async def request_captcha(self) -> None:
        self._captcha_event.clear()
        await self._page.evaluate("setCaptchaVisible(true)")
        await self._captcha_event.wait()

    async def close(self) -> None:
        if self._context:
            await self._context.close()

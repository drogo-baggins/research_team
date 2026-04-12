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
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_result: bool = False

    async def start(self) -> None:
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._page.expose_binding("__rt_signal", self._handle_signal)
        await self._page.goto(_HTML_PATH.as_uri())

    def _is_alive(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def _handle_signal(self, source: dict, payload: dict) -> None:
        match payload.get("type"):
            case "chat":
                await self._chat_queue.put(payload.get("message", ""))
            case "captcha_done":
                self._captcha_event.set()
            case "approval_done":
                self._approval_result = payload.get("approved", False)
                self._approval_event.set()

    async def append_agent_message(self, sender: str, text: str) -> None:
        if not self._is_alive():
            return
        safe_sender = json.dumps(sender)
        safe_text = json.dumps(text)
        await self._page.evaluate(f"appendMessage({safe_sender}, {safe_text}, false)")

    async def append_log(self, status: str, text: str) -> None:
        if not self._is_alive():
            return
        safe_status = json.dumps(status)
        safe_text = json.dumps(text)
        await self._page.evaluate(f"appendLog({safe_status}, {safe_text})")

    async def stream_delta(self, agent_name: str, delta: str) -> None:
        if not self._is_alive():
            return
        safe_name = json.dumps(agent_name)
        safe_delta = json.dumps(delta)
        await self._page.evaluate(f"streamDelta({safe_name}, {safe_delta})")

    async def wait_for_user_message(self) -> str:
        return await self._chat_queue.get()

    async def request_captcha(self) -> None:
        self._captcha_event.clear()
        if self._is_alive():
            await self._page.evaluate("setCaptchaVisible(true)")
        await self._captcha_event.wait()

    async def request_content_approval(self, url: str, title: str, preview: str) -> bool:
        self._approval_event.clear()
        self._approval_result = False
        if self._is_alive():
            safe_url = json.dumps(url)
            safe_title = json.dumps(title)
            safe_preview = json.dumps(preview[:500])
            await self._page.evaluate(
                f"setApprovalVisible(true, {safe_url}, {safe_title}, {safe_preview})"
            )
        await self._approval_event.wait()
        return self._approval_result

    async def close(self) -> None:
        if self._context:
            await self._context.close()

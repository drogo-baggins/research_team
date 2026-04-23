import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from playwright.async_api import Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


_HTML_PATH = Path(__file__).parent / "control_page.html"


class ControlUI:
    def __init__(self, browser: Browser):
        self._browser = browser
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._chat_queue: asyncio.Queue[str] = asyncio.Queue()
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_result: bool = False
        self._pending_approval_url: str | None = None
        self._closed_event: asyncio.Event = asyncio.Event()
        self._wbs_approval_event: asyncio.Event = asyncio.Event()
        self._wbs_approval_result: dict | None = None
        self._on_approval_start: Callable[[], None] | None = None
        self._on_approval_end: Callable[[], None] | None = None
        self._current_mode: str = "new_request"
        self._mode_change_callback: Callable | None = None
        self._session_selection_event: asyncio.Event = asyncio.Event()
        self._session_selection_result: str | None = None

    def set_approval_hooks(
        self,
        on_start: Callable[[], None] | None,
        on_end: Callable[[], None] | None,
    ) -> None:
        self._on_approval_start = on_start
        self._on_approval_end = on_end

    @property
    def closed(self) -> bool:
        return self._closed_event.is_set()

    async def wait_until_closed(self) -> None:
        await self._closed_event.wait()

    async def start(self) -> None:
        from playwright.async_api import Error as PlaywrightError
        try:
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            await self._page.expose_binding("__rt_signal", self._handle_signal)
            self._page.on("load", self._on_page_load)
            self._page.on("close", self._on_page_close)
            await self._page.goto(_HTML_PATH.as_uri())
        except PlaywrightError as exc:
            logger.error("ControlUI.start: failed to initialize browser UI: %s", exc)
            self._closed_event.set()
            raise

    def _on_page_close(self, page: Page) -> None:
        self._closed_event.set()
        self._approval_event.set()
        self._wbs_approval_event.set()
        self._session_selection_event.set()
        self._chat_queue.put_nowait("")

    async def _on_page_load(self, page: Page) -> None:
        if self._pending_approval_url is not None:
            safe_url = json.dumps(self._pending_approval_url)
            try:
                await page.evaluate(f"setApprovalVisible(true, {safe_url})")
            except Exception:
                pass

    def _is_alive(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def _handle_signal(self, source: dict, payload: dict) -> None:
        match payload.get("type"):
            case "chat":
                await self._chat_queue.put(payload.get("message", ""))
            case "mode_selected":
                self._current_mode = payload.get("mode", "new_request")
                if self._mode_change_callback is not None:
                    asyncio.create_task(self._mode_change_callback(self._current_mode))
            case "session_selected":
                self._session_selection_result = payload.get("session_id")
                self._session_selection_event.set()
            case "approval_done":
                self._approval_result = payload.get("approved", False)
                self._approval_event.set()
            case "wbs_approval":
                approved = payload.get("approved", False)
                if not approved and not payload.get("feedback"):
                    self._wbs_approval_result = None
                else:
                    self._wbs_approval_result = {
                        "approved": approved,
                        "depth": payload.get("depth", "standard"),
                        "style": payload.get("style", "research_report"),
                        "locales": payload.get("locales", ["ja", "en"]),
                    }
                self._wbs_approval_event.set()
            case "wbs_feedback":
                self._wbs_approval_result = {
                    "approved": False,
                    "feedback": payload.get("text", ""),
                    "depth": payload.get("depth", "standard"),
                    "style": payload.get("style", "research_report"),
                    "locales": payload.get("locales", ["ja", "en"]),
                }
                self._wbs_approval_event.set()

    async def append_agent_message(self, sender: str, text: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            safe_sender = json.dumps(sender)
            safe_text = json.dumps(text)
            await self._page.evaluate(f"appendMessage({safe_sender}, {safe_text}, false)")
        except Exception:
            pass

    async def append_log(self, status: str, text: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            safe_status = json.dumps(status)
            safe_text = json.dumps(text)
            await self._page.evaluate(f"appendLog({safe_status}, {safe_text})")
        except Exception:
            pass

    async def stream_delta(self, agent_name: str, delta: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            safe_name = json.dumps(agent_name)
            safe_delta = json.dumps(delta)
            await self._page.evaluate(f"streamDelta({safe_name}, {safe_delta})")
        except Exception:
            pass

    async def set_wbs(self, milestones: list[dict]) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(f"setWbs({json.dumps(milestones)})")
        except Exception:
            pass

    async def update_wbs_task(self, task_id: str, done: bool) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(f"updateWbsTask({json.dumps(task_id)}, {json.dumps(done)})")
        except Exception:
            pass

    async def set_agent_status(self, agent_name: str, status: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(f"setAgentStatus({json.dumps(agent_name)}, {json.dumps(status)})")
        except Exception:
            pass

    async def wait_for_user_message(self) -> str:
        msg = await self._chat_queue.get()
        return msg

    def get_current_mode(self) -> str:
        return self._current_mode

    async def show_wbs_approval(self, depth: str, style: str, locales: list[str] | None = None) -> dict | None:
        self._wbs_approval_event.clear()
        self._wbs_approval_result = None
        if self._is_alive():
            assert self._page
            try:
                await self._page.evaluate(
                    f"showWbsApproval({json.dumps(depth)}, {json.dumps(style)}, {json.dumps(locales or ['ja', 'en'])})"
                )
            except Exception:
                self._wbs_approval_event.set()
        else:
            self._wbs_approval_event.set()
        await self._wbs_approval_event.wait()
        return self._wbs_approval_result

    async def wait_for_capture(self, url: str) -> bool:
        logger.warning("wait_for_capture CALLED: url=%s", url)
        self._approval_event.clear()
        self._approval_result = False
        self._pending_approval_url = url
        if self._is_alive():
            assert self._page
            logger.warning("wait_for_capture: page is alive, calling setApprovalVisible")
            try:
                safe_url = json.dumps(url)
                await self._page.evaluate(f"setApprovalVisible(true, {safe_url})")
                logger.warning("wait_for_capture: setApprovalVisible done, waiting for event")
            except Exception:
                self._approval_event.set()
        else:
            logger.warning("wait_for_capture: page is NOT alive, skipping evaluate")
            self._approval_event.set()
        if self._on_approval_start:
            self._on_approval_start()
        await self._approval_event.wait()
        if self._on_approval_end:
            self._on_approval_end()
        self._pending_approval_url = None
        logger.warning("wait_for_capture: event fired, result=%s", self._approval_result)
        return self._approval_result

    async def show_artifact_link(self, label: str, path: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(
                f"addArtifactLink({json.dumps(label)}, {json.dumps(path)})"
            )
        except Exception:
            pass

    def set_mode_change_callback(self, cb: Callable) -> None:
        self._mode_change_callback = cb

    async def render_session_list(self, sessions: list[dict]) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(f"renderSessionList({json.dumps(sessions)})")
        except Exception:
            pass

    async def wait_for_session_selection(self) -> str | None:
        self._session_selection_event.clear()
        self._session_selection_result = None
        await self._session_selection_event.wait()
        return self._session_selection_result

    async def close(self) -> None:
        if self._context:
            await self._context.close()

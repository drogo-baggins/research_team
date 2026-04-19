import asyncio
import json as _json
import logging
import re as _re
from urllib.parse import urlencode
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError
from research_team.pi_bridge.client import PiAgentClient
from research_team.search.base import SearchEngine, SearchResult
from research_team.search.google_extractor import GoogleSearchExtractor

logger = logging.getLogger(__name__)

_LOCALE_PARAMS: dict[str, dict[str, str]] = {
    "ja":    {"hl": "ja",    "gl": "jp", "lr": "lang_ja"},
    "ko":    {"hl": "ko",    "gl": "kr", "lr": "lang_ko"},
    "zh-CN": {"hl": "zh-CN", "gl": "cn", "lr": "lang_zh"},
    "zh-TW": {"hl": "zh-TW", "gl": "tw", "lr": "lang_zh"},
    "ar":    {"hl": "ar",               "lr": "lang_ar"},
    "ru":    {"hl": "ru",    "gl": "ru", "lr": "lang_ru"},
    "fr":    {"hl": "fr",    "gl": "fr", "lr": "lang_fr"},
    "de":    {"hl": "de",    "gl": "de", "lr": "lang_de"},
    "es":    {"hl": "es",    "gl": "es", "lr": "lang_es"},
    "pt":    {"hl": "pt",    "gl": "br", "lr": "lang_pt"},
    "hi":    {"hl": "hi",    "gl": "in", "lr": "lang_hi"},
    "th":    {"hl": "th",    "gl": "th", "lr": "lang_th"},
    "vi":    {"hl": "vi",    "gl": "vn", "lr": "lang_vi"},
    "id":    {"hl": "id",    "gl": "id", "lr": "lang_id"},
    "it":    {"hl": "it",    "gl": "it", "lr": "lang_it"},
    "nl":    {"hl": "nl",    "gl": "nl", "lr": "lang_nl"},
    "pl":    {"hl": "pl",    "gl": "pl", "lr": "lang_pl"},
    "tr":    {"hl": "tr",    "gl": "tr", "lr": "lang_tr"},
}

_SCRIPT_LOCALE: list[tuple[tuple[int, int], str]] = [
    ((0x3040, 0x309F), "ja"),
    ((0x30A0, 0x30FF), "ja"),
    ((0xAC00, 0xD7A3), "ko"),
    ((0x1100, 0x11FF), "ko"),
    ((0x0600, 0x06FF), "ar"),
    ((0x0400, 0x04FF), "ru"),
    ((0x0900, 0x097F), "hi"),
    ((0x0E00, 0x0E7F), "th"),
    ((0x1E00, 0x1EFF), "vi"),
]


_LOCALE_LANGUAGE_NAMES: dict[str, str] = {
    "ja": "Japanese",
    "ko": "Korean",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "ar": "Arabic",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "en": "English",
}


def _extract_json_object(text: str) -> dict:
    match = _re.search(r'"translated"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if match:
        return {"translated": _json.loads(f'"{match.group(1)}"')}
    raise ValueError(f"no translated field found in: {text!r}")


class _QueryTranslator:
    def __init__(self) -> None:
        self._client: PiAgentClient | None = None

    async def translate(self, query: str, target_locale: str) -> str:
        language = _LOCALE_LANGUAGE_NAMES.get(target_locale)
        if not language:
            return query
        try:
            if self._client is None:
                self._client = PiAgentClient(
                    system_prompt=(
                        'You are a search query translator. '
                        'You receive JSON: {"query": "...", "target_language": "..."}. '
                        'You respond with JSON only: {"translated": "..."}. '
                        'No explanation, no markdown, no extra fields.'
                    ),
                )
                await self._client.start()
            request = _json.dumps({"query": query, "target_language": language}, ensure_ascii=False)
            parts: list[str] = []
            async for event in self._client.prompt(request):
                if event.type == "message_update":
                    ame = event.data.get("assistantMessageEvent", {})
                    if ame.get("type") == "text_delta":
                        parts.append(ame.get("delta", ""))
                elif event.type == "message_end":
                    if not parts:
                        msg = event.data.get("message", {})
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text":
                                parts.append(block.get("text", ""))
            raw = "".join(parts).strip()
            logger.info("_QueryTranslator.translate: raw response: %r", raw)
            translated = _extract_json_object(raw).get("translated", "")
            result = translated if translated else query
            logger.info("_QueryTranslator.translate: %r -> %r", query, result)
            return result
        except Exception as exc:
            logger.warning("_QueryTranslator.translate: failed (%s), using original: %r", exc, query)
            self._client = None
            return query

    async def close(self) -> None:
        if self._client:
            await self._client.stop()
            self._client = None


def _detect_locale(query: str, preferred_locales: list[str]) -> str | None:
    detected: str | None = None
    for (lo, hi), locale in _SCRIPT_LOCALE:
        if any(lo <= ord(c) <= hi for c in query):
            detected = locale
            break

    if detected is None:
        has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF for c in query)
        if has_cjk:
            for candidate in ("zh-CN", "zh-TW"):
                if candidate in preferred_locales:
                    return candidate

    if detected and detected in preferred_locales:
        return detected

    return preferred_locales[0] if preferred_locales else None


class HumanSearchEngine(SearchEngine):
    _extractor = GoogleSearchExtractor()

    def __init__(
        self,
        search_engine_url: str = "https://www.google.com/search",
        browser: Browser | None = None,
        control_ui=None,
        preferred_locales: list[str] | None = None,
    ):
        self._search_engine_url = search_engine_url.rstrip("?").rstrip("?q=")
        self._browser = browser
        self._control_ui = control_ui
        self._preferred_locales: list[str] = preferred_locales if preferred_locales is not None else ["ja", "en"]
        self._playwright = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._translator: _QueryTranslator | None = None

    def set_preferred_locales(self, locales: list[str]) -> None:
        self._preferred_locales = locales

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            if self._browser is None:
                try:
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except PlaywrightError as exc:
                    logger.error("HumanSearchEngine: failed to launch browser: %s", exc)
                    raise
            try:
                _ctx_locale = self._preferred_locales[0] if self._preferred_locales else "en"
                self._context = await self._browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale=_ctx_locale,
                )
                await self._context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
            except PlaywrightError as exc:
                logger.error("HumanSearchEngine: failed to create browser context: %s", exc)
                raise
        return self._context

    async def _navigate(self, url: str) -> Page:
        context = await self._get_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=0)
            return page
        except PlaywrightError as exc:
            try:
                await page.close()
            except Exception:
                pass
            logger.warning("HumanSearchEngine._navigate: failed for %s: %s", url, exc)
            raise

    def _ui_closed(self) -> bool:
        return self._control_ui is not None and self._control_ui.closed

    async def _require_approval(self, url: str) -> bool:
        if self._control_ui is None:
            return True
        if self._control_ui.closed:
            return False
        try:
            return await self._control_ui.wait_for_capture(url)
        except Exception as exc:
            logger.warning("HumanSearchEngine._require_approval: unexpected error: %s", exc)
            return True

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self._ui_closed():
            logger.info("HumanSearchEngine.search: UI closed, skipping query: %s", query)
            return []
        async with self._lock:
            locale = _detect_locale(query, self._preferred_locales)
            if len(self._preferred_locales) == 1 and locale and locale in _LOCALE_LANGUAGE_NAMES:
                if self._translator is None:
                    self._translator = _QueryTranslator()
                query = await self._translator.translate(query, locale)
                logger.debug("HumanSearchEngine.search: translated query: %s", query)
            params: dict[str, str] = {"q": query}
            if locale and locale in _LOCALE_PARAMS:
                params.update(_LOCALE_PARAMS[locale])
            search_url = f"{self._search_engine_url}?{urlencode(params)}"

            logger.debug("HumanSearchEngine.search: navigating to %s", search_url)
            try:
                page = await self._navigate(search_url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.search: navigation failed: %s", e)
                return []
            logger.debug("HumanSearchEngine.search: page opened, url=%s", page.url)

            approved = await self._require_approval(search_url)
            if not approved:
                logger.info("HumanSearchEngine.search: user rejected query: %s", query)
                try:
                    await page.close()
                except Exception:
                    pass
                return []

            try:
                try:
                    await page.wait_for_selector("#rso", timeout=5000)
                    logger.debug("HumanSearchEngine.search: #rso appeared in DOM")
                except Exception:
                    logger.debug("HumanSearchEngine.search: #rso not found within 5s, proceeding")

                results = await self._extractor.extract(page, max_results=max_results)
                if results:
                    return results

                logger.debug(
                    "HumanSearchEngine.search: extractor returned 0 results, falling back to raw page"
                )
                try:
                    content = await page.inner_text("body")
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    content = "\n".join(lines[:500])
                except PlaywrightError as e:
                    logger.warning("HumanSearchEngine.search: inner_text failed: %s", e)
                    content = ""
                try:
                    title = await page.title()
                except PlaywrightError:
                    title = query
                return [SearchResult(url=search_url, title=title, content=content, source="human")]
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    async def fetch(self, url: str) -> SearchResult:
        if self._ui_closed():
            logger.info("HumanSearchEngine.fetch: UI closed, skipping url: %s", url)
            return SearchResult(url=url, title="", content="", source="human")
        async with self._lock:
            try:
                page = await self._navigate(url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.fetch: navigation failed: %s", e)
                return SearchResult(url=url, title="", content="", source="human")

            approved = await self._require_approval(url)
            if not approved:
                try:
                    await page.close()
                except Exception:
                    pass
                return SearchResult(url=url, title="", content="", source="human")

            try:
                content = await page.inner_text("body")
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                content = "\n".join(lines[:500])
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.fetch: inner_text failed: %s", e)
                content = ""
            try:
                title = await page.title()
            except PlaywrightError:
                title = url
            try:
                await page.close()
            except Exception:
                pass
            return SearchResult(url=url, title=title, content=content, source="human")

    async def close(self) -> None:
        if self._translator:
            try:
                await self._translator.close()
            except Exception as exc:
                logger.warning("HumanSearchEngine.close: translator.close() failed: %s", exc)
        try:
            if self._context:
                await self._context.close()
        except Exception as exc:
            logger.warning("HumanSearchEngine.close: context.close() failed: %s", exc)
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("HumanSearchEngine.close: playwright.stop() failed: %s", exc)

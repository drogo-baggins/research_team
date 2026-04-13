import asyncio
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from research_team.search.base import SearchEngine, SearchResult

_CAPTCHA_SIGNALS = ["captcha", "challenge", "robot", "blocked", "verify", "sorry"]


class HumanSearchEngine(SearchEngine):
    def __init__(
        self,
        search_engine_url: str = "https://www.google.com/search?q=",
        browser: Browser | None = None,
        control_ui=None,
        no_timeout: bool = False,
    ):
        self._search_engine_url = search_engine_url
        self._browser = browser
        self._control_ui = control_ui
        self._no_timeout = no_timeout
        self._playwright = None
        self._context: BrowserContext | None = None

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=False)
            self._context = await self._browser.new_context()
        return self._context

    def _timeout(self, default_ms: int) -> int:
        return 0 if self._no_timeout else default_ms

    def _is_captcha_page(self, url: str, title: str) -> bool:
        return any(s in url.lower() or s in title.lower() for s in _CAPTCHA_SIGNALS)

    async def _navigate_and_wait(self, url: str, timeout_ms: int = 15_000) -> Page:
        context = await self._get_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout(timeout_ms))
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        return page

    async def _wait_for_captcha_resolution(self, page: Page) -> None:
        while self._is_captcha_page(page.url, await page.title()):
            await asyncio.sleep(2)

    async def _extract_content(self, page: Page) -> str:
        try:
            text = await page.inner_text("body")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines[:500])
        except Exception:
            return ""

    async def _handle_captcha_if_needed(self, page: Page) -> None:
        if self._is_captcha_page(page.url, await page.title()):
            if self._control_ui is not None:
                await self._control_ui.request_captcha()
            if self._no_timeout:
                await self._wait_for_captcha_resolution(page)

    async def _request_approval(self, page: Page) -> bool:
        if self._control_ui is None:
            return True
        title = await page.title()
        url = page.url
        return await self._control_ui.request_content_approval(url, title)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        search_url = f"{self._search_engine_url}{query.replace(' ', '+')}"
        page = await self._navigate_and_wait(search_url)
        await self._handle_captcha_if_needed(page)

        links = await page.query_selector_all("a[href^='http']:not([href*='google'])")
        results: list[SearchResult] = []

        for link in links[:max_results * 2]:
            href = await link.get_attribute("href")
            if not href or not href.startswith("http"):
                continue
            try:
                result_page = await self._navigate_and_wait(href, timeout_ms=10_000)
                await self._handle_captcha_if_needed(result_page)
                approved = await self._request_approval(result_page)
                if not approved:
                    await result_page.close()
                    continue
                title = await result_page.title()
                content = await self._extract_content(result_page)
                await result_page.close()

                if content:
                    results.append(SearchResult(
                        url=href, title=title, content=content, source="human",
                    ))
                    if len(results) >= max_results:
                        break
            except Exception:
                continue

        await page.close()
        return results

    async def fetch(self, url: str) -> SearchResult:
        page = await self._navigate_and_wait(url)
        await self._handle_captcha_if_needed(page)
        approved = await self._request_approval(page)
        title = await page.title()
        content = await self._extract_content(page) if approved else ""
        await page.close()
        return SearchResult(url=url, title=title, content=content, source="human")

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()


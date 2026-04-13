import asyncio
import logging
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError
from research_team.search.base import SearchEngine, SearchResult
from research_team.search.google_parser import GoogleSearchParser

logger = logging.getLogger(__name__)


class HumanSearchEngine(SearchEngine):
    _parser = GoogleSearchParser()

    def __init__(
        self,
        search_engine_url: str = "https://www.google.com/search?q=",
        browser: Browser | None = None,
        control_ui=None,
    ):
        self._search_engine_url = search_engine_url
        self._browser = browser
        self._control_ui = control_ui
        self._playwright = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            if self._browser is None:
                try:
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(headless=False)
                except PlaywrightError as exc:
                    logger.error("HumanSearchEngine: failed to launch browser: %s", exc)
                    raise
            try:
                self._context = await self._browser.new_context()
            except PlaywrightError as exc:
                logger.error("HumanSearchEngine: failed to create browser context: %s", exc)
                raise
        return self._context

    async def _navigate(self, url: str) -> Page:
        context = await self._get_context()
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="commit", timeout=0)
            return page
        except PlaywrightError as exc:
            logger.warning("HumanSearchEngine._navigate: failed for %s: %s", url, exc)
            raise

    async def _wait_and_extract(self, page: Page) -> str:
        if self._control_ui is not None:
            approved = await self._control_ui.wait_for_capture(page.url)
            if not approved:
                raise PermissionError(f"User skipped: {page.url}")
        text = await page.inner_text("body")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:500])

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with self._lock:
            search_url = f"{self._search_engine_url}{query.replace(' ', '+')}"
            logger.warning("HumanSearchEngine.search: navigating to %s", search_url)
            try:
                page = await self._navigate(search_url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.search: navigation failed (browser closed?): %s", e)
                return []
            logger.warning("HumanSearchEngine.search: page opened, url=%s, control_ui=%s", page.url, self._control_ui)
            try:
                content = await self._wait_and_extract(page)
            except PermissionError:
                logger.info("User skipped search results page for query: %s", query)
                try:
                    await page.close()
                except Exception:
                    pass
                return []
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.search: page closed during extraction: %s", e)
                try:
                    await page.close()
                except Exception:
                    pass
                return []
            try:
                title = await page.title()
            except PlaywrightError:
                title = query
            try:
                await page.close()
            except Exception:
                pass

        parsed = self._parser.parse(content, max_results=max_results)
        if parsed:
            logger.info(
                "HumanSearchEngine.search: parsed %d results from Google SERP",
                len(parsed),
            )
            return parsed

        logger.warning(
            "HumanSearchEngine.search: parser returned 0 results, falling back to raw page"
        )
        return [SearchResult(url=search_url, title=title, content=content, source="human")]

    async def fetch(self, url: str) -> SearchResult:
        async with self._lock:
            try:
                page = await self._navigate(url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.fetch: navigation failed (browser closed?): %s", e)
                return SearchResult(url=url, title="", content="", source="human")
            try:
                content = await self._wait_and_extract(page)
            except (PermissionError, PlaywrightError) as e:
                logger.warning("HumanSearchEngine.fetch: page closed during extraction: %s", e)
                try:
                    await page.close()
                except Exception:
                    pass
                return SearchResult(url=url, title="", content="", source="human")
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

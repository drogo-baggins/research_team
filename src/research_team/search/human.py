import asyncio
import logging
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError
from research_team.search.base import SearchEngine, SearchResult
from research_team.search.google_extractor import GoogleSearchExtractor

logger = logging.getLogger(__name__)


class HumanSearchEngine(SearchEngine):
    _extractor = GoogleSearchExtractor()

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

    async def _require_approval(self, page: Page) -> bool:
        if self._control_ui is None:
            return True
        if self._control_ui.closed:
            return False
        try:
            return await self._control_ui.wait_for_capture(page.url)
        except Exception as exc:
            logger.warning("HumanSearchEngine._require_approval: unexpected error: %s", exc)
            return True

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self._ui_closed():
            logger.info("HumanSearchEngine.search: UI closed, skipping query: %s", query)
            return []
        async with self._lock:
            search_url = f"{self._search_engine_url}{query.replace(' ', '+')}"
            logger.debug("HumanSearchEngine.search: navigating to %s", search_url)
            try:
                page = await self._navigate(search_url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.search: navigation failed: %s", e)
                return []
            logger.debug("HumanSearchEngine.search: page opened, url=%s", page.url)

            try:
                approved = await self._require_approval(page)
                if not approved:
                    logger.info("User skipped search results page for query: %s", query)
                    return []

                if page.url != search_url and not page.url.startswith(search_url):
                    logger.debug(
                        "HumanSearchEngine.search: page URL drifted after approval (%s), re-navigating to %s",
                        page.url,
                        search_url,
                    )
                    try:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=0)
                    except PlaywrightError as e:
                        logger.warning("HumanSearchEngine.search: re-navigation failed: %s", e)

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

            approved = await self._require_approval(page)
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

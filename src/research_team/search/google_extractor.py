# src/research_team/search/google_extractor.py
"""Google 検索結果ページからの構造化データ抽出。

Google 固有の DOM 構造・リダイレクト URL 解決ロジックをこのモジュールに閉じ込める。
将来 Bing や DuckDuckGo に対応する場合は別モジュールを作成し SerpExtractor を継承すること。
"""

import logging
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.async_api import Page

from research_team.search.base import SearchResult
from research_team.search.serp_extractor import SerpExtractor

logger = logging.getLogger(__name__)

# Google の有機的検索結果リンクは /url?q= または /url?url= リダイレクト形式。
# h3 タグがタイトル、[data-sncf] または最近傍の div テキストがスニペット。
_EXTRACT_JS = """
els => els.map(a => {
  const href = a.getAttribute('href') || '';
  const title = (a.querySelector('h3')?.textContent || '').trim();
  const block = a.closest('[data-hveid]') || a.parentElement;
  const snippet = (
    block?.querySelector('[data-sncf]')?.textContent ||
    block?.querySelector('div > span')?.textContent ||
    ''
  ).trim();
  return { href, title, snippet };
})
"""

_EXCLUDED_DOMAINS = frozenset({
    "google.com", "google.co.jp", "google.co.uk",
    "accounts.google.com", "maps.google.com",
    "webcache.googleusercontent.com",
})


class GoogleSearchExtractor(SerpExtractor):
    """Google SERP から title・url・snippet を Playwright Locator 経由で抽出する。

    `page.locator('a[href^="/url?"]').evaluate_all(...)` でブラウザ内 JS を
    1往復実行し、構造化データとして取得する。
    DOM 操作に失敗した場合は空リストを返す（呼び出し元でフォールバックを実装すること）。
    """

    async def extract(self, page: Page, max_results: int = 5) -> list[SearchResult]:
        try:
            raw_items: list[dict] = await page.locator('a[href^="/url?"]').evaluate_all(
                _EXTRACT_JS
            )
        except Exception as exc:
            logger.debug("GoogleSearchExtractor.extract: evaluate_all failed: %s", exc)
            return []

        results: list[SearchResult] = []
        for item in raw_items:
            if len(results) >= max_results:
                break
            url = self._resolve_url(item.get("href", ""))
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("title") or url,
                    content=item.get("snippet", ""),
                    source="human",
                )
            )

        if results:
            logger.info(
                "GoogleSearchExtractor.extract: extracted %d results from SERP",
                len(results),
            )
        else:
            logger.debug("GoogleSearchExtractor.extract: no results extracted")

        return results

    def _resolve_url(self, href: str) -> str:
        """Google リダイレクト URL を実際の URL に解決し、Google ドメインを除外する。

        Google SERP の有機的検索結果リンクは /url?q=... 形式。
        q パラメータが実際の URL。url= パラメータもフォールバックとして処理する。
        絶対 URL 形式 (https://www.google.com/url?...) は当クラスのロケーター
        (a[href^="/url?"]) がマッチしないため処理しない。
        """
        if not href:
            return ""
        if href.startswith("/url?"):
            full = urljoin("https://www.google.com", href)
            qs = parse_qs(urlparse(full).query)
            resolved = (qs.get("q") or qs.get("url") or [""])[0]
            if not resolved:
                return ""
            href = resolved
        if not href.startswith(("http://", "https://")):
            return ""
        try:
            domain = urlparse(href).netloc.lower().removeprefix("www.")
        except Exception:
            return ""
        if any(domain == ex or domain.endswith("." + ex) for ex in _EXCLUDED_DOMAINS):
            return ""
        return href

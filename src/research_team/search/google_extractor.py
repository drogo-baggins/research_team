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

_EXTRACT_JS = """
() => {
  const rso = document.querySelector('#rso');
  if (!rso) return [];
  const seen = new Set();
  const results = [];
  for (const a of rso.querySelectorAll('a')) {
    if (!a.querySelector('h3')) continue;
    const href = a.href || a.getAttribute('href') || '';
    if (!href || seen.has(href)) continue;
    seen.add(href);
    const title = (a.querySelector('h3')?.textContent || '').trim();
    const block = a.closest('[data-hveid]') || a.parentElement;
    const snippet = (
      block?.querySelector('[data-sncf]')?.textContent ||
      block?.querySelector('div > span')?.textContent ||
      ''
    ).trim();
    results.push({ href, title, snippet });
  }
  return results;
}
"""

_EXCLUDED_DOMAINS = frozenset({
    "google.com", "google.co.jp", "google.co.uk",
    "accounts.google.com", "maps.google.com",
    "webcache.googleusercontent.com",
})


class GoogleSearchExtractor(SerpExtractor):
    """Google SERP から title・url・snippet を Playwright 経由で抽出する。

    `#rso` コンテナ内の `<h3>` を含む `<a>` タグを有機的検索結果として扱う。
    Google は直接の絶対 URL (`href="https://..."`) を使用するようになっており、
    旧来の `/url?q=` リダイレクト形式もフォールバックとして処理する。
    DOM 操作に失敗した場合は空リストを返す（呼び出し元でフォールバックを実装すること）。
    """

    async def extract(self, page: Page, max_results: int = 5) -> list[SearchResult]:
        try:
            raw_items: list[dict] = await page.evaluate(_EXTRACT_JS)
        except Exception as exc:
            logger.debug("GoogleSearchExtractor.extract: evaluate failed: %s", exc)
            return []

        logger.debug(
            "GoogleSearchExtractor.extract: evaluate returned %d raw items",
            len(raw_items),
        )

        results: list[SearchResult] = []
        for item in raw_items:
            if len(results) >= max_results:
                break
            url = self._resolve_url(item.get("href", ""))
            if not url:
                logger.debug(
                    "GoogleSearchExtractor.extract: skipped href=%r (resolve_url returned empty)",
                    item.get("href", ""),
                )
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
        """URL を正規化し、Google ドメインを除外する。

        Google SERP の有機的検索結果リンクは現在直接の絶対 URL を使用するが、
        旧来の /url?q=... 形式もフォールバックとして処理する。
        """
        if not href:
            return ""
        if "/url?" in href:
            try:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                resolved = (qs.get("q") or qs.get("url") or [""])[0]
                if resolved:
                    href = resolved
            except Exception:
                pass
        if not href.startswith(("http://", "https://")):
            return ""
        try:
            domain = urlparse(href).netloc.lower().removeprefix("www.")
        except Exception:
            return ""
        if any(domain == ex or domain.endswith("." + ex) for ex in _EXCLUDED_DOMAINS):
            return ""
        return href

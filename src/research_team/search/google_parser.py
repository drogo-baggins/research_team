"""Google 検索結果ページのパーサー。

このモジュールは Google 固有の DOM 構造に関する知識を閉じ込める。
将来、Bing や DuckDuckGo などの検索エンジンに対応する場合は
別の parser クラスを追加する設計とする（このファイルには手を加えない）。
"""

import logging
import re
from urllib.parse import unquote, urlparse

from research_team.search.base import SearchResult

logger = logging.getLogger(__name__)


class GoogleSearchParser:
    """Google 検索結果 HTML から SearchResult のリストを生成する。

    Google の DOM 構造は頻繁に変わる。/url?q= リダイレクトパターンを使って
    個別 URL を抽出するヒューリスティックアプローチを採用する。
    パースに失敗した場合は空リストを返す（呼び出し元でフォールバックを実装すること）。
    """

    _REDIRECT_PATTERN = re.compile(r"/url\?q=([^&]+)")
    _EXCLUDED_DOMAINS = {
        "google.com", "google.co.jp", "google.co.uk",
        "accounts.google.com", "maps.google.com",
        "webcache.googleusercontent.com",
    }

    def parse(self, html: str, max_results: int = 5) -> list[SearchResult]:
        if not html:
            return []

        results: list[SearchResult] = []

        for match in self._REDIRECT_PATTERN.finditer(html):
            if len(results) >= max_results:
                break

            raw_url = unquote(match.group(1))
            url = self._clean_url(raw_url)
            if not url:
                continue

            # タイトルは通常 URL より前（リンクテキスト）、スニペットは後に続く
            # Google の DOM 構造に合わせ、前 200 chars・後 500 chars を走査する
            start = max(0, match.start() - 200)
            end = min(len(html), match.end() + 500)
            context = html[start:end]

            title = self._extract_title_from_context(context) or url
            snippet = self._extract_snippet_from_context(context)

            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    content=snippet,
                    source="human",
                )
            )

        if results:
            logger.debug("GoogleSearchParser: parsed %d results", len(results))
        else:
            logger.warning(
                "GoogleSearchParser: no results found in HTML (len=%d)", len(html)
            )

        return results[:max_results]

    def _clean_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            return ""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().removeprefix("www.")
            if any(domain == ex or domain.endswith("." + ex) for ex in self._EXCLUDED_DOMAINS):
                return ""
        except Exception:
            return ""
        return url

    def _extract_title_from_context(self, context: str) -> str:
        m = re.search(r"<h3[^>]*>(.*?)</h3>", context, re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return ""

    def _extract_snippet_from_context(self, context: str) -> str:
        text = re.sub(r"<[^>]+>", " ", context)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:200] if text else ""

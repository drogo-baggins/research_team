import logging
import re
from urllib.parse import unquote, urlparse

from research_team.search.base import SearchResult

logger = logging.getLogger(__name__)


class GoogleSearchParser:
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
            domain = parsed.netloc.lower().lstrip("www.")
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

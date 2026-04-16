# SERP Locator-Based Extraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GoogleSearchParser.parse(html)` を廃止し、Playwright Locator + `evaluate_all` ベースの `GoogleSearchExtractor.extract(page)` に刷新することで、Google検索結果から title/url/snippet を確実に取得できるようにする。また将来の多エンジン対応のため抽象基底クラス `SerpExtractor` を導入する。

**Architecture:**
- `SerpExtractor` ABC（新規）: `extract(page) -> list[SearchResult]` の統一インターフェース。将来の Bing/DDG 対応はここを継承するだけで済む。
- `GoogleSearchExtractor`（新規、`google_parser.py` を置き換え）: Playwright `page.locator(...).evaluate_all(...)` で1往復DOM取得。`/url?q=` リダイレクト解決も内包。相対・絶対両形式のリダイレクトを処理する。
- `HumanSearchEngine`（修正）:
  - `_wait_and_extract()` を廃止し、承認ロジックを `_require_approval(page)` ヘルパーに共通化。
  - `search()`: 承認後に `GoogleSearchExtractor.extract(page)` を呼ぶ。フォールバックは `page.inner_text("body")` で1件返す。
  - `fetch()`: `_require_approval(page)` を呼ぶよう修正（承認の動作は変わらない）。

**Tech Stack:** Python asyncio, Playwright async API, pytest-asyncio, pytest

---

## 前提知識

### なぜ `inner_text()` では駄目か
`page.inner_text("body")` はレンダリング済みテキストのみ返す。`<a href="/url?q=...">` のような HTML 属性値は含まれない。  
→ `GoogleSearchParser` は `/url?q=` を HTML 属性値から探していたため、プレーンテキストには存在せず0件になっていた。

### なぜ Locator + evaluate_all か
`page.locator('a[href^="/url?"]').evaluate_all(...)` はブラウザ内 JS を1往復で実行し、href・title・snippet を構造化データとして返す。  
HTML全体を `page.content()` で取得して Python 側でパースする方法より：
- レンダリング後の DOM を見るため動的コンテンツに強い
- 1往復で済むためシンプル
- セレクタが壊れたときにフォールバックを組みやすい

### Google リダイレクト URL の正規化
Google の検索結果リンクは `/url?q=https://example.com/...&sa=U` 形式。`q` クエリパラメータが実際の URL。

```python
from urllib.parse import urljoin, urlparse, parse_qs

def resolve_google_href(href: str) -> str:
    if not href.startswith("/url?"):
        return href
    parsed = urlparse(urljoin("https://www.google.com", href))
    qs = parse_qs(parsed.query)
    return (qs.get("q") or qs.get("url") or [href])[0]
```

---

## ファイル構成

| ファイル | 変更内容 |
|---------|---------|
| `src/research_team/search/serp_extractor.py` | **新規作成** — `SerpExtractor` ABC |
| `src/research_team/search/google_extractor.py` | **新規作成** — `GoogleSearchExtractor(SerpExtractor)` の実装 |
| `src/research_team/search/human.py` | **修正** — `_wait_and_extract` を廃止し `_require_approval()` ヘルパーを導入。`search()` で `GoogleSearchExtractor` 使用。`fetch()` も `_require_approval()` を呼ぶよう修正 |
| `src/research_team/search/google_parser.py` | **削除** — 新実装で置き換え（Task 4 で削除、それまで残す） |
| `tests/unit/test_serp_extractor.py` | **新規作成** — ABC のインターフェーステスト |
| `tests/unit/test_google_extractor.py` | **新規作成** — `GoogleSearchExtractor` のユニットテスト |
| `tests/unit/test_search_human.py` | **修正** — `_wait_and_extract` モックを `_require_approval` + `evaluate_all` モックに更新 |
| `tests/unit/test_google_parser.py` | **削除** — Task 4 で削除（Task 3 完了後に削除） |

---

## Chunk 1: SerpExtractor ABC + GoogleSearchExtractor の新規実装

### Task 1: `SerpExtractor` ABC を作成する

**Files:**
- Create: `src/research_team/search/serp_extractor.py`
- Create: `tests/unit/test_serp_extractor.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_serp_extractor.py
import pytest
from abc import ABC
from research_team.search.serp_extractor import SerpExtractor
from research_team.search.base import SearchResult


def test_serp_extractor_is_abstract():
    """SerpExtractor は直接インスタンス化できないこと。"""
    assert issubclass(SerpExtractor, ABC)
    with pytest.raises(TypeError):
        SerpExtractor()  # type: ignore


def test_serp_extractor_concrete_subclass_works():
    """extract を実装したサブクラスはインスタンス化できること。"""

    class DummyExtractor(SerpExtractor):
        async def extract(self, page, max_results=5):
            return []

    extractor = DummyExtractor()
    assert isinstance(extractor, SerpExtractor)
```

- [ ] **Step 2: テストが失敗することを確認する**

```
pytest tests/unit/test_serp_extractor.py -v
```
Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 3: 実装を書く**

```python
# src/research_team/search/serp_extractor.py
"""SERP（検索エンジン結果ページ）からの構造化データ抽出インターフェース。

各検索エンジン固有の抽出ロジックはこのABCを継承して実装する。
将来 Bing/DuckDuckGo を追加する場合は BingSearchExtractor 等を新規作成するだけでよい。
"""

from abc import ABC, abstractmethod

from playwright.async_api import Page

from research_team.search.base import SearchResult


class SerpExtractor(ABC):
    """検索エンジン結果ページからの構造化データ抽出の抽象基底クラス。

    実装クラスは extract() を override し、
    Playwright Page オブジェクトから SearchResult のリストを返すこと。
    """

    @abstractmethod
    async def extract(self, page: Page, max_results: int = 5) -> list[SearchResult]:
        """検索結果ページから SearchResult のリストを抽出する。

        Args:
            page: 検索結果ページが開かれた Playwright Page オブジェクト。
            max_results: 返す結果の最大件数。

        Returns:
            SearchResult のリスト。抽出失敗時は空リストを返す（例外を投げない）。
        """
        ...
```

- [ ] **Step 4: テストが通ることを確認する**

```
pytest tests/unit/test_serp_extractor.py -v
```
Expected: 2 passed

- [ ] **Step 5: コミット**

```
git add src/research_team/search/serp_extractor.py tests/unit/test_serp_extractor.py
git commit -m "feat: add SerpExtractor ABC for multi-engine extensibility"
```

---

### Task 2: `GoogleSearchExtractor` を実装する

**Files:**
- Create: `src/research_team/search/google_extractor.py`
- Create: `tests/unit/test_google_extractor.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_google_extractor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from research_team.search.google_extractor import GoogleSearchExtractor
from research_team.search.base import SearchResult


JS_RESULT = [
    {"href": "/url?q=https://example.com/article1&sa=U", "title": "Article 1", "snippet": "Snippet 1"},
    {"href": "/url?q=https://example.com/article2&sa=U", "title": "Article 2", "snippet": "Snippet 2"},
    {"href": "/url?q=https://google.com/maps&sa=U",      "title": "Google Maps", "snippet": ""},
    {"href": "/url?q=https://example.com/article3&sa=U", "title": "Article 3", "snippet": "Snippet 3"},
    {"href": "/url?q=https://example.com/article4&sa=U", "title": "Article 4", "snippet": "Snippet 4"},
    {"href": "/url?q=https://example.com/article5&sa=U", "title": "Article 5", "snippet": "Snippet 5"},
]


def _make_page(js_return_value):
    """evaluate_all が js_return_value を返す Page モック。"""
    locator = MagicMock()
    locator.evaluate_all = AsyncMock(return_value=js_return_value)
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    return page


class TestGoogleSearchExtractor:

    @pytest.mark.asyncio
    async def test_extract_returns_list_of_search_results(self):
        """evaluate_all の結果を SearchResult に変換して返すこと。"""
        page = _make_page(JS_RESULT[:2])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].url == "https://example.com/article1"
        assert results[0].title == "Article 1"
        assert results[0].content == "Snippet 1"
        assert results[0].source == "human"

    @pytest.mark.asyncio
    async def test_extract_resolves_google_redirect_urls(self):
        """/url?q= 形式のリダイレクトを実際の URL に解決すること。"""
        page = _make_page([
            {"href": "/url?q=https://example.com/target%3Fid%3D1&sa=U",
             "title": "Target", "snippet": "desc"},
        ])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/target?id=1"

    @pytest.mark.asyncio
    async def test_extract_excludes_google_own_urls(self):
        """google.com ドメインの URL を除外すること。"""
        page = _make_page(JS_RESULT)  # google.com/maps が含まれる
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=10)

        urls = [r.url for r in results]
        assert not any("google.com" in u for u in urls)

    @pytest.mark.asyncio
    async def test_extract_respects_max_results(self):
        """max_results を超えた結果を返さないこと。"""
        page = _make_page(JS_RESULT)  # 6件（google除外で5件）
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_extract_returns_empty_on_evaluate_error(self):
        """evaluate_all が例外を投げた場合は空リストを返すこと。"""
        locator = MagicMock()
        locator.evaluate_all = AsyncMock(side_effect=Exception("DOM error"))
        page = MagicMock()
        page.locator = MagicMock(return_value=locator)

        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_extract_returns_empty_when_no_results(self):
        """JS が空リストを返した場合は空リストを返すこと。"""
        page = _make_page([])
        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=5)

        assert results == []
```

- [ ] **Step 2: テストが失敗することを確認する**

```
pytest tests/unit/test_google_extractor.py -v
```
Expected: `ImportError` (モジュール未存在)

- [ ] **Step 3: 実装を書く**

```python
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

        相対形式: /url?q=https://example.com/...&sa=U
        絶対形式: https://www.google.com/url?q=https://example.com/...&sa=U
        の両方を処理する。
        """
        if not href:
            return ""
        # 相対・絶対両形式のリダイレクトを処理
        parsed_href = urlparse(href)
        is_google_redirect = (
            parsed_href.path == "/url" and parsed_href.query
        )
        if href.startswith("/url?") or is_google_redirect:
            if href.startswith("/url?"):
                full = urljoin("https://www.google.com", href)
            else:
                full = href
            parsed = urlparse(full)
            qs = parse_qs(parsed.query)
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
```

- [ ] **Step 4: テストが通ることを確認する**

```
pytest tests/unit/test_google_extractor.py -v
```
Expected: 6 passed

- [ ] **Step 5: コミット**

```
git add src/research_team/search/serp_extractor.py \
        src/research_team/search/google_extractor.py \
        tests/unit/test_google_extractor.py \
        tests/unit/test_serp_extractor.py
git commit -m "feat: add GoogleSearchExtractor using Playwright locator evaluate_all"
```

---

## Chunk 2: HumanSearchEngine の修正と旧実装の削除

### Task 3: `HumanSearchEngine` を修正する（`_require_approval` ヘルパー + `GoogleSearchExtractor` 使用）

**Files:**
- Modify: `src/research_team/search/human.py`
- Modify: `tests/unit/test_search_human.py`

#### 変更の方針

`_wait_and_extract()` は `search()` と `fetch()` の両方で使われていた。
これを廃止すると `fetch()` の承認ロジックが消えてしまう（Oracle 指摘のブロッキング問題）。

解決策: 承認ロジックを `_require_approval(page)` ヘルパーに共通化し、
`search()` と `fetch()` の両方から呼ぶ。

```
新 search() フロー:
  _navigate(search_url)
  → _require_approval(page)  [承認 or skip → [] を返す]
  → GoogleSearchExtractor.extract(page)
  → (空なら) inner_text フォールバック → 1件返す

新 fetch() フロー:
  _navigate(url)
  → _require_approval(page)  [承認 or skip → 空 SearchResult を返す]
  → page.inner_text("body")  [本文取得は変わらない]
```

- [ ] **Step 1: テストを更新する**

`test_search_human.py` 全体を以下の内容で置き換える（既存のテストケースを維持しつつ、モックを新フローに合わせる）：

```python
# tests/unit/test_search_human.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.base import SearchResult
from research_team.search.human import HumanSearchEngine


def _make_search_page(evaluate_all_return=None, inner_text_return="body text"):
    """evaluate_all と inner_text を持つ search page モック。"""
    mock_locator = MagicMock()
    mock_locator.evaluate_all = AsyncMock(return_value=evaluate_all_return or [])
    page = AsyncMock()
    page.locator = MagicMock(return_value=mock_locator)
    page.inner_text = AsyncMock(return_value=inner_text_return)
    page.title = AsyncMock(return_value="Test - Google Search")
    page.close = AsyncMock()
    return page


def test_search_result_model():
    result = SearchResult(
        url="https://example.com",
        title="Example",
        content="Test content",
        source="human",
    )
    assert result.url == "https://example.com"
    assert result.source == "human"


@pytest.mark.asyncio
async def test_search_returns_multiple_results_when_extractor_finds_links():
    """GoogleSearchExtractor が結果を返した場合、複数件の SearchResult が返ること。"""
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=True)

    page = _make_search_page(evaluate_all_return=[
        {"href": "/url?q=https://example.com/article1&sa=U", "title": "Article 1", "snippet": "Snip 1"},
        {"href": "/url?q=https://example.com/article2&sa=U", "title": "Article 2", "snippet": "Snip 2"},
    ])
    page.url = "https://www.google.com/search?q=test"

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        results = await engine.search("test query", max_results=5)

    assert len(results) >= 2
    urls = [r.url for r in results]
    assert "https://example.com/article1" in urls
    assert "https://example.com/article2" in urls
    mock_ui.wait_for_capture.assert_called_once()


@pytest.mark.asyncio
async def test_search_falls_back_to_single_result_when_extractor_finds_nothing():
    """evaluate_all が空を返した場合、フォールバックで1件返すこと。"""
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=True)

    page = _make_search_page(
        evaluate_all_return=[],
        inner_text_return="Google search results content",
    )
    page.url = "https://www.google.com/search?q=python+asyncio"

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        results = await engine.search("python asyncio", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://www.google.com/search?q=python+asyncio"
    assert results[0].source == "human"
    assert "Google search results content" in results[0].content


@pytest.mark.asyncio
async def test_search_returns_empty_when_user_skips():
    """ユーザーが承認を拒否した場合、空リストを返すこと。"""
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=False)

    page = _make_search_page()
    page.url = "https://www.google.com/search?q=test"

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        results = await engine.search("test", max_results=5)

    assert results == []


@pytest.mark.asyncio
async def test_fetch_calls_approval():
    """fetch() がユーザー承認を求めること。"""
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=True)

    page = AsyncMock()
    page.url = "https://example.com/article"
    page.title = AsyncMock(return_value="Article Title")
    page.inner_text = AsyncMock(return_value="article body")
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        result = await engine.fetch("https://example.com/article")

    mock_ui.wait_for_capture.assert_called_once_with("https://example.com/article")
    assert result.url == "https://example.com/article"
    assert result.content == "article body"


@pytest.mark.asyncio
async def test_fetch_returns_empty_content_when_user_rejects():
    """fetch() でユーザーが拒否した場合、空コンテンツを返すこと。"""
    mock_ui = AsyncMock()
    mock_ui.wait_for_capture = AsyncMock(return_value=False)

    page = AsyncMock()
    page.url = "https://example.com/article"
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=mock_ui)
    with patch.object(engine, "_navigate", return_value=page):
        result = await engine.fetch("https://example.com/article")

    assert result.url == "https://example.com/article"
    assert result.content == ""


@pytest.mark.asyncio
async def test_no_approval_needed_without_ui():
    """control_ui が None の場合、承認なしで fetch できること。"""
    page = AsyncMock()
    page.url = "https://example.com/article"
    page.title = AsyncMock(return_value="Article")
    page.inner_text = AsyncMock(return_value="body text")
    page.close = AsyncMock()

    engine = HumanSearchEngine(control_ui=None)
    with patch.object(engine, "_navigate", return_value=page):
        result = await engine.fetch("https://example.com/article")

    assert result.content == "body text"
```

- [ ] **Step 2: テストが失敗することを確認する**

```
pytest tests/unit/test_search_human.py -v
```
Expected: 複数 failed（まだ実装を変えていないため）

- [ ] **Step 3: `human.py` を修正する**

`_wait_and_extract()` を廃止し、`_require_approval()` ヘルパーを追加。
`search()` と `fetch()` を新フローで書き直す。

```python
# src/research_team/search/human.py (全文)
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
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="commit", timeout=0)
            return page
        except PlaywrightError as exc:
            logger.warning("HumanSearchEngine._navigate: failed for %s: %s", url, exc)
            raise

    async def _require_approval(self, page: Page) -> bool:
        """ユーザー承認が必要な場合に wait_for_capture を呼び出す。

        control_ui が None の場合は常に True（承認済み）を返す。
        Returns:
            True: 承認された（処理を続ける）
            False: 拒否された（呼び出し元は処理を中断すること）
        """
        if self._control_ui is None:
            return True
        try:
            return await self._control_ui.wait_for_capture(page.url)
        except Exception:
            return True

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with self._lock:
            search_url = f"{self._search_engine_url}{query.replace(' ', '+')}"
            logger.debug("HumanSearchEngine.search: navigating to %s", search_url)
            try:
                page = await self._navigate(search_url)
            except PlaywrightError as e:
                logger.warning("HumanSearchEngine.search: navigation failed: %s", e)
                return []
            logger.debug("HumanSearchEngine.search: page opened, url=%s", page.url)

            approved = await self._require_approval(page)
            if not approved:
                logger.info("User skipped search results page for query: %s", query)
                try:
                    await page.close()
                except Exception:
                    pass
                return []

            # Locator ベースで構造化データを抽出
            results = await self._extractor.extract(page, max_results=max_results)
            if results:
                try:
                    await page.close()
                except Exception:
                    pass
                return results

            # フォールバック: ページテキスト全体を1件として返す
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
            try:
                await page.close()
            except Exception:
                pass
            return [SearchResult(url=search_url, title=title, content=content, source="human")]

    async def fetch(self, url: str) -> SearchResult:
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
```

- [ ] **Step 4: テストが通ることを確認する**

```
pytest tests/unit/test_search_human.py -v
```
Expected: 全件 passed

- [ ] **Step 5: 全テストスイートで確認する**

```
pytest tests/ -v
```
Expected: 全件 passed（`test_google_parser.py` は次の Task で削除するため、このタイミングで失敗していても可）

- [ ] **Step 6: コミット**

```
git add src/research_team/search/human.py tests/unit/test_search_human.py
git commit -m "feat: use GoogleSearchExtractor in HumanSearchEngine; introduce _require_approval helper"
```

---

### Task 4: 旧実装（`google_parser.py`）を削除する

**Files:**
- Delete: `src/research_team/search/google_parser.py`
- Delete: `tests/unit/test_google_parser.py`

- [ ] **Step 1: 他ファイルからの参照がないことを確認する**

```
grep -r "google_parser" src/ tests/
```
Expected: 結果なし（Task 3 で import を削除済みのため）

- [ ] **Step 2: ファイルを削除する**

```
git rm src/research_team/search/google_parser.py tests/unit/test_google_parser.py
```

- [ ] **Step 3: 全テストスイートで確認する**

```
pytest tests/ -v
```
Expected: 全件 passed

- [ ] **Step 4: LSP diagnostics を確認する**

```python
# lsp_diagnostics を src/research_team/search/ に対して実行
# Expected: 0 errors
```

- [ ] **Step 5: コミット**

```
git commit -m "refactor: remove GoogleSearchParser (replaced by GoogleSearchExtractor)"
```

---

## 完了確認チェックリスト

- [ ] `pytest tests/ -v` が全件 passed
- [ ] `lsp_diagnostics` が `src/research_team/search/` で 0 errors
- [ ] `HumanSearchEngine.search()` 内に `inner_text` の呼び出しがない（フォールバック以外）
- [ ] `google_parser.py` が削除されている
- [ ] `serp_extractor.py`・`google_extractor.py` が存在する
- [ ] 将来 Bing 対応する場合: `BingSearchExtractor(SerpExtractor)` を新規作成するだけでよい設計になっている

---

## 将来の多エンジン対応メモ

Bing を追加する場合の最小実装例（参考）：

```python
# src/research_team/search/bing_extractor.py
class BingSearchExtractor(SerpExtractor):
    _EXTRACT_JS = """
    els => els.map(a => {
      const title = (a.querySelector('h2')?.textContent || '').trim();
      const href = a.getAttribute('href') || '';
      const block = a.closest('.b_algo');
      const snippet = (block?.querySelector('.b_caption p')?.textContent || '').trim();
      return { href, title, snippet };
    })
    """

    async def extract(self, page: Page, max_results: int = 5) -> list[SearchResult]:
        # Bing のリンクは直接 URL なのでリダイレクト解決不要
        ...
```

`HumanSearchEngine` にエンジン選択を渡す場合は `__init__` に `extractor: SerpExtractor | None = None` を追加し、`None` 時は `GoogleSearchExtractor()` をデフォルトとすればよい。

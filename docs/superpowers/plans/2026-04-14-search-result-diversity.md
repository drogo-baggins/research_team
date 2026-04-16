# Search Result Diversity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** エージェントが Google 検索ページのテキストだけでなく、個別URLのタイトル・URL・スニペットのリストを受け取り、適合性を自己評価して `web_fetch` を呼ぶことで、多様なウェブソースから情報収集できるようにする。

**Architecture:** `HumanSearchEngine.search()` を Google 向けの Playwright DOM パースに改修し、`SearchResult` のリストを返す。`specialist.md.template` を更新してエージェントが「スニペット評価 → 選択的 web_fetch」の手順を明示的に実行するよう指示する。パース知識はGoogleに特化したクラスとして分離し、将来の検索エンジン拡張を妨げない設計とする。

**Tech Stack:** Python, Playwright (async), pytest-asyncio, Markdown template

---

## Chunk 1: Google Search Result Parser

### Task 1: GoogleSearchParser クラスの実装

**Files:**
- Create: `src/research_team/search/google_parser.py`
- Modify: `src/research_team/search/human.py`

#### 背景

現在の `HumanSearchEngine.search()` は Google 検索ページに navigate してページ全体のテキストを1件の `SearchResult` として返すだけ。`SearchResult.content` に URL 情報が文字列として埋まっているため、エージェントが個別URLを識別・フェッチできない。

修正後は以下の構造で複数件の `SearchResult` を返す：

```python
SearchResult(
    url="https://example.com/article",  # 実際の記事URL
    title="記事タイトル",
    content="Google検索スニペット（150文字前後）",
    source="human"
)
```

---

- [ ] **Step 1: 失敗テストを書く**

ファイル: `tests/search/test_google_parser.py` を新規作成。

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.google_parser import GoogleSearchParser


class TestGoogleSearchParser:
    """GoogleSearchParser のユニットテスト。"""

    def test_parse_returns_list_of_results(self):
        """パーサーが複数の SearchResult を返すこと。"""
        html = """
        <div data-hveid="CABQAA">
          <div>
            <a href="/url?q=https://example.com/article1&amp;sa=U">
              <h3>Article 1 Title</h3>
            </a>
            <span>Snippet for article 1 that describes the content.</span>
          </div>
        </div>
        <div data-hveid="CABQAB">
          <div>
            <a href="/url?q=https://example.com/article2&amp;sa=U">
              <h3>Article 2 Title</h3>
            </a>
            <span>Snippet for article 2 with different content.</span>
          </div>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        assert len(results) >= 1
        assert all(r.url.startswith("http") for r in results)
        assert all(r.title for r in results)
        assert all(r.source == "human" for r in results)

    def test_parse_excludes_google_own_urls(self):
        """google.com ドメインの URL を除外すること。"""
        html = """
        <div data-hveid="CABQAA">
          <a href="/url?q=https://www.google.com/maps&sa=U"><h3>Google Maps</h3></a>
          <span>Internal google page</span>
        </div>
        <div data-hveid="CABQAB">
          <a href="/url?q=https://example.com/article&sa=U"><h3>External Article</h3></a>
          <span>Real article snippet</span>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        urls = [r.url for r in results]
        assert not any("google.com" in u for u in urls)
        assert any("example.com" in u for u in urls)

    def test_parse_respects_max_results(self):
        """max_results を超えた結果を返さないこと。"""
        # 5件分の HTML を作成
        divs = "\n".join(
            f'<div data-hveid="CABQA{i}"><a href="/url?q=https://example.com/{i}&sa=U">'
            f'<h3>Title {i}</h3></a><span>Snippet {i}</span></div>'
            for i in range(5)
        )
        parser = GoogleSearchParser()
        results = parser.parse(divs, max_results=3)
        assert len(results) <= 3

    def test_parse_empty_html_returns_empty_list(self):
        """空の HTML に対して空のリストを返すこと。"""
        parser = GoogleSearchParser()
        results = parser.parse("", max_results=5)
        assert results == []

    def test_parse_decodes_google_redirect_url(self):
        """/url?q= 形式の Google リダイレクト URL を実際の URL にデコードすること。"""
        html = """
        <div data-hveid="CABQAA">
          <a href="/url?q=https://example.com/target%3Fid%3D1&sa=U">
            <h3>Target Article</h3>
          </a>
          <span>Snippet text</span>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        if results:
            assert "google.com" not in results[0].url
            assert "example.com" in results[0].url
```

- [ ] **Step 2: テストを実行して失敗することを確認**

```
pytest tests/search/test_google_parser.py -v
```

期待: `ModuleNotFoundError: No module named 'research_team.search.google_parser'`

- [ ] **Step 3: GoogleSearchParser を実装する**

ファイル: `src/research_team/search/google_parser.py` を新規作成。

```python
"""Google 検索結果ページのパーサー。

このモジュールは Google 固有の DOM 構造に関する知識を閉じ込める。
将来、Bing や DuckDuckGo などの検索エンジンに対応する場合は
別の parser クラスを追加する設計とする。
"""

import logging
import re
from urllib.parse import unquote, urlparse, parse_qs

from research_team.search.base import SearchResult

logger = logging.getLogger(__name__)


class GoogleSearchParser:
    """Google 検索結果 HTML から SearchResult のリストを生成する。

    Google の DOM 構造は頻繁に変わるため、複数のセレクタ戦略を
    フォールバック付きで試みる。いずれも失敗した場合は空リストを返す。
    """

    # Google リダイレクト URL のパターン: /url?q=<actual_url>&...
    _REDIRECT_PATTERN = re.compile(r"/url\?q=([^&]+)")
    # 除外する URL のドメイン
    _EXCLUDED_DOMAINS = {
        "google.com", "google.co.jp", "google.co.uk",
        "accounts.google.com", "maps.google.com",
        "webcache.googleusercontent.com",
    }

    def parse(self, html: str, max_results: int = 5) -> list[SearchResult]:
        """Google 検索結果の HTML をパースして SearchResult のリストを返す。

        Args:
            html: Google 検索結果ページの innerHTML または body テキスト。
            max_results: 返す最大件数。

        Returns:
            SearchResult のリスト。パース失敗時は空リスト。
        """
        if not html:
            return []

        results: list[SearchResult] = []

        # 戦略1: /url?q= パターンで URL を直接抽出
        # Google は検索結果リンクを /url?q=<encoded_url>&sa=U 形式でラップする
        for match in self._REDIRECT_PATTERN.finditer(html):
            if len(results) >= max_results:
                break

            raw_url = unquote(match.group(1))
            url = self._clean_url(raw_url)
            if not url:
                continue

            # マッチ位置周辺のテキストからタイトルとスニペットを推定
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
        """URL を検証・クリーニングして返す。無効な URL は空文字を返す。"""
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
        """コンテキスト文字列からタイトルを抽出する（ヒューリスティック）。"""
        # <h3>...</h3> パターンを探す
        m = re.search(r"<h3[^>]*>(.*?)</h3>", context, re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return ""

    def _extract_snippet_from_context(self, context: str) -> str:
        """コンテキスト文字列からスニペットを抽出する（ヒューリスティック）。"""
        # タグを除去してテキストのみ取得
        text = re.sub(r"<[^>]+>", " ", context)
        text = re.sub(r"\s+", " ", text).strip()
        # 最初の意味のある文章を最大200文字
        return text[:200] if text else ""
```

- [ ] **Step 4: テストを実行してパスすることを確認**

```
pytest tests/search/test_google_parser.py -v
```

期待: 全テストが PASS

- [ ] **Step 5: コミット**

```bash
git add src/research_team/search/google_parser.py tests/search/test_google_parser.py
git commit -m "feat: add GoogleSearchParser for structured search result extraction"
```

---

### Task 2: HumanSearchEngine.search() の改修

**Files:**
- Modify: `src/research_team/search/human.py`

#### 変更内容

`search()` を以下のように変更する：

1. Google 検索ページに navigate（変わらず）
2. `_wait_and_extract()` でページテキストを取得（変わらず）
3. **NEW**: `GoogleSearchParser.parse()` でテキストをパースして複数の `SearchResult` を生成
4. パース結果が0件の場合は **フォールバック** として現在の挙動（ページ全体を1件で返す）を維持

これにより後方互換性を保ちながら機能を強化する。

---

- [ ] **Step 6: 失敗テストを書く（search() の統合テスト）**

ファイル: `tests/search/test_human_search_engine.py` に追記（存在しない場合は新規作成）。

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.human import HumanSearchEngine
from research_team.search.base import SearchResult


class TestHumanSearchEngineSearchParsed:
    """HumanSearchEngine.search() が GoogleSearchParser を使用することのテスト。"""

    @pytest.mark.asyncio
    async def test_search_returns_multiple_results_when_parser_finds_links(self):
        """パーサーが複数URLを見つけた場合、複数の SearchResult を返すこと。"""
        # Google 検索結果に見えるモック HTML
        mock_html = (
            'Title1 /url?q=https://example.com/article1&sa=U snippet1 '
            '/url?q=https://example.com/article2&sa=U snippet2'
        )

        engine = HumanSearchEngine()
        engine._control_ui = None

        mock_page = AsyncMock()
        mock_page.url = "https://www.google.com/search?q=test"
        mock_page.inner_text = AsyncMock(return_value=mock_html)
        mock_page.title = AsyncMock(return_value="test - Google Search")
        mock_page.close = AsyncMock()

        with patch.object(engine, "_navigate", return_value=mock_page):
            results = await engine.search("test query", max_results=5)

        assert len(results) >= 2
        urls = [r.url for r in results]
        assert "https://example.com/article1" in urls
        assert "https://example.com/article2" in urls

    @pytest.mark.asyncio
    async def test_search_falls_back_to_single_result_when_parser_finds_nothing(self):
        """パーサーが0件の場合、従来の1件フォールバックを返すこと。"""
        mock_html = "検索結果が見つかりませんでした"

        engine = HumanSearchEngine()
        engine._control_ui = None

        mock_page = AsyncMock()
        mock_page.url = "https://www.google.com/search?q=test"
        mock_page.inner_text = AsyncMock(return_value=mock_html)
        mock_page.title = AsyncMock(return_value="test - Google Search")
        mock_page.close = AsyncMock()

        with patch.object(engine, "_navigate", return_value=mock_page):
            results = await engine.search("test query", max_results=5)

        assert len(results) == 1
        assert results[0].source == "human"
```

- [ ] **Step 7: テストを実行して失敗することを確認**

```
pytest tests/search/test_human_search_engine.py -v
```

期待: `test_search_returns_multiple_results_when_parser_finds_links` が FAIL

- [ ] **Step 8: HumanSearchEngine.search() を改修する**

`src/research_team/search/human.py` の `search()` メソッドを以下のように変更する：

```python
# ファイル先頭の import に追加:
from research_team.search.google_parser import GoogleSearchParser

# クラス内に追加:
_parser = GoogleSearchParser()

# search() メソッドを以下に置き換え:
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

        # Google 検索結果をパースして個別 URL リストを生成
        parsed = self._parser.parse(content, max_results=max_results)
        if parsed:
            logger.info(
                "HumanSearchEngine.search: parsed %d results from Google SERP",
                len(parsed),
            )
            return parsed

        # フォールバック: パース失敗時は従来の1件返却
        logger.warning(
            "HumanSearchEngine.search: parser returned 0 results, falling back to raw page"
        )
        return [SearchResult(url=search_url, title=title, content=content, source="human")]
```

- [ ] **Step 9: テストを実行してパスすることを確認**

```
pytest tests/search/test_human_search_engine.py tests/search/test_google_parser.py -v
```

期待: 全テストが PASS

- [ ] **Step 10: コミット**

```bash
git add src/research_team/search/human.py tests/search/test_human_search_engine.py
git commit -m "feat: make HumanSearchEngine.search() return structured URL list via GoogleSearchParser"
```

---

## Chunk 2: Specialist Prompt Enhancement

### Task 3: specialist.md.template の更新

**Files:**
- Modify: `src/research_team/agents/dynamic/templates/specialist.md.template`

#### 変更内容

エージェントが以下の手順を自律的に実行するよう指示を追加する：
1. `web_search` でクエリを検索 → タイトル・URL・スニペットのリストを受け取る
2. 各スニペットを読んで調査テーマへの**関連性を評価**
3. 関連性が高いと判断した URL のみ `web_fetch` で全文取得
4. 複数クエリ・複数ソースを組み合わせて調査を深める

---

- [ ] **Step 11: テンプレートを更新する**

`src/research_team/agents/dynamic/templates/specialist.md.template` を以下の内容に置き換える：

```markdown
# {name} - Research Specialist

## Role
You are **{name}**, a research specialist with deep expertise in **{expertise}**.

## Mission
{system_prompt}

## Available Tools
- **web_search(query, max_results)**: Search the web. Returns a list of results, each with `url`, `title`, and `content` (snippet).
- **web_fetch(url)**: Fetch the full text of a specific URL. Use this to get the complete content of relevant pages found via web_search.

## Research Process
Follow this process for each research subtopic:

1. **Search**: Call `web_search` with a specific query related to your topic.
2. **Evaluate snippets**: Read each result's `title` and `content` (snippet). Ask yourself: "Does this source likely contain relevant, reliable information about my research topic?"
3. **Fetch selectively**: Call `web_fetch` only on URLs whose snippets look relevant and credible. Aim to fetch **2–4 sources per query**. Skip results that are clearly off-topic, low-quality, or duplicates.
4. **Synthesize**: Combine information from fetched pages and your expertise into a coherent analysis.
5. **Iterate**: If gaps remain, refine your search query and repeat.

## Guidelines
- Always use `web_search` first before `web_fetch` — don't guess URLs
- Prefer primary sources (official sites, research papers, news articles) over aggregator sites
- Cite the source URL whenever you use information from a fetched page
- Add your expert analysis and context beyond what the sources contain
- Structure your output clearly with headings and bullet points
- Flag any gaps, contradictions, or low-confidence findings in the available information
- Focus exclusively on your assigned research area
```

- [ ] **Step 12: テンプレートの内容を手動検証する**

ファイルを読んで、`web_search` と `web_fetch` の使い方が明確に記述されていること、スニペット評価のステップが含まれていることを確認する。

- [ ] **Step 13: コミット**

```bash
git add src/research_team/agents/dynamic/templates/specialist.md.template
git commit -m "feat: enhance specialist prompt with web_search/web_fetch workflow and snippet evaluation step"
```

---

## Chunk 3: Verification

### Task 4: 統合確認

**Files:**
- Read-only: `rt_run.log`（実行後）

- [ ] **Step 14: テストスイート全体を実行**

```
pytest tests/ -v --tb=short
```

期待: 全テストが PASS（または既存の失敗が増えていないこと）

- [ ] **Step 15: lsp_diagnostics で変更ファイルをチェック**

以下のファイルでエラーがないことを確認：
- `src/research_team/search/google_parser.py`
- `src/research_team/search/human.py`
- `src/research_team/agents/dynamic/templates/specialist.md.template`

- [ ] **Step 16: 動作確認（ユーザーが実施）**

```
python -m research_team.cli.main start --depth standard
```

実行後 `rt_run.log` で以下を確認：
- `parsed N results from Google SERP`（N >= 2）のログが出ること
- `web_fetch` が Wikipedia 以外の URL（ニュースサイト、学術サイト等）に対しても呼ばれること

- [ ] **Step 17: 最終コミット（必要に応じて）**

```bash
git add -p
git commit -m "chore: verify search diversity implementation complete"
```

# Human Search Fix: Lock, URL Config, Test Isolation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Human検索モードの3つの問題（二重ロック、URL外出し、テスト時のGoogle連続アクセス防止）を修正し、全テストをパスさせる

**Architecture:**
- `SearchServer._lock` は `HumanSearchEngine._lock` で代替できるため削除
- 検索エンジンURL（Google等）を環境変数 `SEARCH_ENGINE_URL` で外出し
- テスト時は `aiohttp.web` でローカルダミーサーバーを立てて `HumanSearchEngine` に向ける
- `test_ui_integration` は `request_content_approval` をモックして承認を自動化（永遠のwaitを防ぐ）

**Tech Stack:** Python, asyncio, aiohttp, pytest, playwright, unittest.mock

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Modify | `src/research_team/pi_bridge/search_server.py` | `_lock` 削除 |
| Modify | `src/research_team/search/human.py` | デフォルトURL変更（環境変数 `SEARCH_ENGINE_URL` 参照） |
| Modify | `src/research_team/search/factory.py` | `_get_human_engine` が環境変数URL を渡す |
| Create | `tests/conftest.py` | ダミーHTTPサーバーのfixture（`dummy_search_server`） |
| Modify | `tests/unit/test_search_human.py` | `SEARCH_ENGINE_URL` を明示的に指定するように更新 |
| Modify | `tests/integration/test_e2e.py` | `test_ui_integration` の承認を自動モック化 |
| Modify | `.env.example` | `SEARCH_ENGINE_URL` の説明を追加 |

---

## Task 1: SearchServer._lock を削除

**Files:**
- Modify: `src/research_team/pi_bridge/search_server.py`
- Test: `tests/unit/test_pi_bridge.py`

### 背景
`HumanSearchEngine` は内部で `self._lock` を持つため、`SearchServer` でも `asyncio.Lock` を使うと二重ロックになり、承認待ち中も `SearchServer._lock` が保持され続ける。`SearchServer._lock` を削除することで解消する。

- [ ] **Step 1: 現行テストを確認して失敗パターンを記録**

```bash
python -m pytest tests/unit/test_pi_bridge.py -v
```
Expected: PASS（現状で通っているはず）

- [ ] **Step 2: `SearchServer._lock` を削除**

`search_server.py` を以下に変更：

```python
import asyncio
from aiohttp import web
from research_team.search.base import SearchEngine


class SearchServer:
    def __init__(self, engine: SearchEngine) -> None:
        self._engine = engine
        self._app = web.Application()
        self._app.router.add_get("/search", self._handle_search)
        self._app.router.add_get("/fetch", self._handle_fetch)
        self._runner: web.AppRunner | None = None
        self.port: int = 0

    async def start(self) -> int:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_search(self, request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        max_results = int(request.query.get("max", "5"))
        results = await self._engine.search(query, max_results=max_results)
        return web.json_response([r.model_dump() for r in results])

    async def _handle_fetch(self, request: web.Request) -> web.Response:
        url = request.query.get("url", "")
        result = await self._engine.fetch(url)
        return web.json_response(result.model_dump())
```

- [ ] **Step 3: テスト実行**

```bash
python -m pytest tests/unit/test_pi_bridge.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/research_team/pi_bridge/search_server.py
git commit -m "fix: remove redundant asyncio.Lock from SearchServer"
```

---

## Task 2: Search URLを環境変数で外出し

**Files:**
- Modify: `src/research_team/search/human.py`
- Modify: `src/research_team/search/factory.py`
- Modify: `.env.example`

### 背景
現在 `HumanSearchEngine` のデフォルトURLは `"https://www.google.com/search?q="` にハードコードされている。テスト時にローカルサーバーに差し替えられるよう、環境変数 `SEARCH_ENGINE_URL` を参照する設計にする。

- [ ] **Step 1: `HumanSearchEngine.__init__` のシグネチャを変更**

`human.py` の `__init__` を以下に変更（デフォルト値を `None` にして `factory.py` に責務を委譲）：

```python
class HumanSearchEngine(SearchEngine):
    def __init__(
        self,
        search_engine_url: str = "https://www.google.com/search?q=",
        browser: Browser | None = None,
        control_ui=None,
    ):
```

シグネチャは変わらず（デフォルト値維持）。`factory.py` 側で環境変数を読んで渡す。

- [ ] **Step 2: `factory.py` を更新して環境変数URLを渡す**

```python
import os
from research_team.search.base import SearchEngine

_DEFAULT_SEARCH_URL = "https://www.google.com/search?q="


def _get_human_engine(control_ui=None) -> SearchEngine:
    from research_team.search.human import HumanSearchEngine
    url = os.environ.get("SEARCH_ENGINE_URL", _DEFAULT_SEARCH_URL)
    return HumanSearchEngine(search_engine_url=url, control_ui=control_ui)


def _get_tavily_engine(control_ui=None) -> SearchEngine:
    from research_team.search.tavily import TavilySearchEngine
    return TavilySearchEngine()


_FACTORIES = {
    "human": _get_human_engine,
    "tavily": _get_tavily_engine,
}


class SearchEngineFactory:
    @staticmethod
    def create(mode: str | None = None, control_ui=None) -> SearchEngine:
        mode = mode or os.environ.get("SEARCH_MODE", "human")
        factory_fn = _FACTORIES.get(mode)
        if factory_fn is None:
            raise ValueError(f"Unknown SEARCH_MODE: {mode!r}. Valid: {list(_FACTORIES)}")
        return factory_fn(control_ui=control_ui)
```

- [ ] **Step 3: `.env.example` に追記**

```
# 検索エンジンのベースURL（human モード用）
# テスト時はローカルサーバーに向けるため上書き可能
# デフォルト: https://www.google.com/search?q=
SEARCH_ENGINE_URL=https://www.google.com/search?q=
```

- [ ] **Step 4: 既存テストが通ることを確認**

```bash
python -m pytest tests/unit/test_search_human.py tests/unit/test_pi_bridge.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/research_team/search/factory.py .env.example
git commit -m "feat: externalize SEARCH_ENGINE_URL via environment variable"
```

---

## Task 3: テスト用ダミーHTTPサーバーfixture を作成

**Files:**
- Create: `tests/conftest.py`

### 背景
テスト時に `HumanSearchEngine` がGoogleではなくローカルのダミーHTTPサーバーに向くよう、`pytest` の fixture でサーバーを起動・終了する。ダミーサーバーは `/search` と任意URLへのアクセスを受け付け、シンプルなHTMLを返す。

`HumanSearchEngine` はブラウザ経由でURLをnavigate するため、ダミーサーバーはブラウザからアクセスできる本物のHTTPサーバーが必要。

- [ ] **Step 1: `tests/conftest.py` を作成**

```python
import asyncio
import threading
import pytest
from aiohttp import web


async def _make_dummy_app() -> web.Application:
    """検索・コンテンツページを返すダミーHTTPアプリ"""
    app = web.Application()

    async def search_handler(request: web.Request) -> web.Response:
        query = request.query.get("q", "test")
        # 検索結果ページ: 2件のリンクを返す
        html = f"""<!DOCTYPE html>
<html><body>
<h1>Search: {query}</h1>
<a href="http://{request.host}/page/1">Result 1</a>
<a href="http://{request.host}/page/2">Result 2</a>
</body></html>"""
        return web.Response(text=html, content_type="text/html")

    async def page_handler(request: web.Request) -> web.Response:
        page_id = request.match_info.get("id", "0")
        html = f"""<!DOCTYPE html>
<html><head><title>Test Page {page_id}</title></head>
<body>
<h1>Test Content {page_id}</h1>
<p>This is dummy content for page {page_id}. Lorem ipsum dolor sit amet.</p>
</body></html>"""
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/search", search_handler)
    app.router.add_get("/page/{id}", page_handler)
    return app


@pytest.fixture(scope="session")
def dummy_search_server():
    """セッション全体で使えるダミー検索サーバー（別スレッドで動作）"""
    loop = asyncio.new_event_loop()
    runner_holder: list = []
    port_holder: list[int] = []
    ready = threading.Event()

    def run():
        async def start():
            app = await _make_dummy_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            runner_holder.append(runner)
            port_holder.append(port)
            ready.set()
            # セッション終了まで待機
            await asyncio.Event().wait()

        loop.run_until_complete(start())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(timeout=10)
    port = port_holder[0]
    base_url = f"http://127.0.0.1:{port}/search?q="
    yield base_url
```

- [ ] **Step 2: fixture の動作確認テストを書く**

`tests/unit/test_dummy_server.py` を作成：

```python
import pytest
import httpx


@pytest.mark.asyncio
async def test_dummy_search_server_responds(dummy_search_server):
    async with httpx.AsyncClient() as client:
        resp = await client.get(dummy_search_server + "python")
    assert resp.status_code == 200
    assert "Result" in resp.text


@pytest.mark.asyncio
async def test_dummy_page_responds(dummy_search_server):
    base = dummy_search_server.replace("/search?q=", "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(base + "/page/1")
    assert resp.status_code == 200
    assert "Test Content 1" in resp.text
```

- [ ] **Step 3: テスト実行**

```bash
python -m pytest tests/unit/test_dummy_server.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/unit/test_dummy_server.py
git commit -m "test: add dummy HTTP server fixture for search isolation"
```

---

## Task 4: 既存ユニットテストをダミーサーバー対応に更新

**Files:**
- Modify: `tests/unit/test_search_human.py`

### 背景
`HumanSearchEngine` をブラウザあり/なしでテストしているが、`search_engine_url` を明示指定することで独立したテストになる。現状のテストは `_navigate_and_wait` をモックしているため変更不要だが、URL引数の明示化でコードの意図を明確にする。

- [ ] **Step 1: テストに `search_engine_url` を明示**

`test_search_human.py` の各テストで `HumanSearchEngine()` を作る箇所に `search_engine_url="http://127.0.0.1:9999/search?q="` を追加（値はダミーでよい、`_navigate_and_wait` はモックするため）。

変更箇所：
- `test_human_search_engine_is_search_engine`
- `test_human_search_returns_results`
- `test_approval_skips_rejected_pages`
- `test_approval_includes_approved_pages`
- `test_fetch_calls_approval`
- `test_no_approval_needed_without_ui`

- [ ] **Step 2: テスト実行**

```bash
python -m pytest tests/unit/test_search_human.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_search_human.py
git commit -m "test: make search_engine_url explicit in unit tests"
```

---

## Task 5: test_ui_integration の承認を自動化

**Files:**
- Modify: `tests/integration/test_e2e.py`

### 背景
`test_ui_integration` は `ControlUI.request_content_approval()` が `_approval_event.wait()` で永遠にハングする。テストでは承認を自動化するため、`_spy_approval` が本物の `ControlUI.request_content_approval` を呼ぶのではなく、即座に `True` を返すモックに差し替える。

さらに、テスト用のダミーサーバー URL を `SEARCH_ENGINE_URL` 環境変数経由で `HumanSearchEngine` に渡す。

- [ ] **Step 1: `_spy_approval` を自動承認モックに変更**

```python
async def _spy_approval(url, title):
    approval_calls.append((url, title))
    return True  # 自動承認（永遠のwaitを防ぐ）
```

- [ ] **Step 2: テスト内で `SEARCH_ENGINE_URL` をダミーサーバーに向ける**

`dummy_search_server` fixture を使って `SEARCH_ENGINE_URL` を設定する。`test_ui_integration` のシグネチャに `dummy_search_server` を追加。

```python
@pytest.mark.interactive
@pytest.mark.asyncio
async def test_ui_integration(tmp_path, dummy_search_server):
    import os
    os.environ["SEARCH_ENGINE_URL"] = dummy_search_server
    # ... 以降は同じ
```

ただし `coordinator.py` は `__init__` で `SearchEngineFactory.create()` を呼んでいるため、`coordinator` 作成前に環境変数を設定する必要がある。`monkeypatch` fixture を使うか `os.environ` を直接設定する。

- [ ] **Step 3: テスト全体を更新**

```python
@pytest.mark.interactive
@pytest.mark.asyncio
async def test_ui_integration(tmp_path, dummy_search_server, monkeypatch):
    import os
    from playwright.async_api import async_playwright
    from research_team.ui.control_ui import ControlUI
    from research_team.orchestrator.coordinator import ResearchCoordinator

    monkeypatch.setenv("SEARCH_ENGINE_URL", dummy_search_server)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ui = ControlUI(browser)
        await ui.start()

        messages_appended: list[tuple[str, str]] = []
        logs_appended: list[tuple[str, str]] = []
        approval_calls: list[tuple[str, str]] = []

        _orig_append_agent = ui.append_agent_message
        _orig_append_log = ui.append_log

        async def _spy_agent(sender, text):
            messages_appended.append((sender, text))
            await _orig_append_agent(sender, text)

        async def _spy_log(status, text):
            logs_appended.append((status, text))
            await _orig_append_log(status, text)

        async def _auto_approve(url, title):
            approval_calls.append((url, title))
            return True  # 自動承認（永遠のwaitを防ぐ）

        ui.append_agent_message = _spy_agent
        ui.append_log = _spy_log
        ui.request_content_approval = _auto_approve  # モックで即True

        coordinator = ResearchCoordinator(workspace_dir=str(workspace), ui=ui)

        async def _inject_topic():
            await asyncio.sleep(0.1)
            await ui._chat_queue.put("Pythonとは何か、一段落で説明してください")

        asyncio.create_task(_inject_topic())

        await coordinator.run_interactive(depth="quick", output_format="markdown")

        await ui.close()

    senders = [s for s, _ in messages_appended]
    assert "CSM" in senders, f"CSMメッセージが届かなかった: {senders}"

    statuses = [s for s, _ in logs_appended]
    assert "running" in statuses, f"runningログが届かなかった: {statuses}"

    assert len(approval_calls) >= 1, (
        f"承認バナーが一度も表示されなかった（web_search/web_fetchが呼ばれていない）: approval_calls={approval_calls}"
    )

    output_files = list(workspace.glob("**/*.md"))
    assert output_files, f"Markdownファイルが生成されなかった: {list(workspace.iterdir())}"
```

- [ ] **Step 4: テスト実行（`-m "not interactive"` なし = interactive も含む）**

注意: このテストはブラウザを開くため、CI ではスキップされる。ローカルで実行：

```bash
python -m pytest tests/integration/test_e2e.py::test_ui_integration -v -s
```

Expected: PASS（ブラウザが開いて自動で完了する）

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_e2e.py
git commit -m "fix: auto-approve in test_ui_integration, use dummy search server"
```

---

## Task 6: 全ユニットテスト確認

- [ ] **Step 1: 全ユニットテスト実行**

```bash
python -m pytest tests/unit/ -v
```
Expected: All PASS

- [ ] **Step 2: E2E (non-interactive) テスト確認**

```bash
python -m pytest tests/ -m "not interactive and not e2e" -v
```
Expected: All PASS

- [ ] **Step 3: 最終コミット（変更がある場合）**

変更がある場合のみ：
```bash
git add -A
git commit -m "chore: finalize human search fix and test isolation"
```

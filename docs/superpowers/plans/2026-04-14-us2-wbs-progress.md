# US-2: WBS・進捗可視化 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WBS 構造をUIに表示し、マイルストン到達時に中間成果物を共有し、調査中に追加リクエストを受け付けるループを実装する。

**Architecture:**
- Task 2-3: `coordinator.py` の PM 出力をテキストのまま `ControlUI.append_agent_message` でそのまま表示する。PM は既存のマークダウン WBS テキストを生成しているため、UI パースは不要。ControlUI の既存 `append_agent_message` をそのまま使う。
- Task 2-4: `_run_specialist_pass()` 完了後に `ProjectManager.create_checkpoint()` を呼び出し、チェックポイントパスを CSM 経由でユーザーに通知する。
- Task 2-5: `run_interactive()` の調査完了後に `wait_for_user_message()` で追加リクエストを受け付け、ループを継続する。

**Tech Stack:** Python (asyncio), Playwright (page.evaluate), pytest-asyncio

---

## Chunk 1: Task 2-3 — WBS を UI に表示

**Context:** `coordinator.py` の `_run_research()` は PM エージェントを呼び出して WBS テキストを生成しているが、結果を `_stream_agent_output()` 経由で表示しているのみ。WBS が `append_agent_message("PM", wbs_text)` で表示される理由は `_stream_agent_output` の末尾にある `await self._notify(agent_name, text)` の呼び出しである。

**問題の確認:** `_stream_agent_output` は既に `append_agent_message` を呼ぶため、PM テキストはすでにチャットに表示されているはずである。しかし WBS の内容が "📋 WBS:" プレフィックスで強調表示されていない可能性がある。

**変更方針:** 追加のコードより既存フローの確認と最小の強調表示を優先する。

### Files:
- Modify: `src/research_team/orchestrator/coordinator.py:230-235`
- Modify: `tests/unit/test_coordinator.py`（テスト追加）

---

- [ ] **Step 1: 現在の WBS 表示状態を確認するテストを書く**

`tests/unit/test_coordinator.py` に追加:

```python
@pytest.mark.asyncio
async def test_wbs_is_displayed_via_ui(tmp_path):
    """PM の WBS 出力がチャットUIに表示されることを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    
    notify_calls: list[tuple[str, str]] = []
    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))
    coord._notify = fake_notify
    coord._log = AsyncMock()

    async def fake_pm_run(message, workspace_dir=None, search_port=0):
        yield make_text_event("# WBS\n\n## マイルストン1: 情報収集\n- タスク1.1: web_search\n")
        yield make_end_event()

    coord._pm_agent.run = fake_pm_run

    async def fake_team_run(message, workspace_dir=None, search_port=0):
        yield make_text_event('[{"name": "調査員", "expertise": "テスト"}]')
        yield make_end_event()

    coord._team_builder.run = fake_team_run

    from research_team.agents.dynamic.factory import DynamicSpecialistAgent
    async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
        yield make_text_event("専門家調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
        await coord.run(ResearchRequest(topic="テストテーマ"))

    # PM の WBS テキストがUIに表示されたか確認
    pm_msgs = [msg for agent, msg in notify_calls if agent == "PM"]
    assert len(pm_msgs) >= 1
    assert "WBS" in pm_msgs[0] or "マイルストン" in pm_msgs[0]
```

- [ ] **Step 2: テストを実行して現在の状態を確認する**

```
cd C:\Users\paled\dev\tools\research_team
python -m pytest tests/unit/test_coordinator.py::test_wbs_is_displayed_via_ui -v
```

期待: テストが通れば WBS はすでに表示されている（タスク 2-3 完了）。失敗すれば Step 3 で修正が必要。

- [ ] **Step 3: テストが失敗した場合のみ — coordinator.py を修正**

`_run_research()` で PM 出力後に明示的に notify:

```python
# coordinator.py の _run_research の PM 呼び出し後（L235 の後）に追加
if pm_output:
    await self._notify("PM", f"📋 **WBS:**\n\n{pm_output}")
```

- [ ] **Step 4: テストを再実行してパスを確認**

```
python -m pytest tests/unit/test_coordinator.py::test_wbs_is_displayed_via_ui -v
```

期待: PASS

- [ ] **Step 5: 全ユニットテストを実行してリグレッションなしを確認**

```
python -m pytest tests/unit/ -v
```

期待: 全テスト PASS

- [ ] **Step 6: コミット**

```
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat(us2): WBS output displayed in UI via PM agent message (2-3)"
```

---

## Chunk 2: Task 2-4 — マイルストン到達時に中間成果物をユーザーに共有

**Context:**
- `ProjectManager.create_checkpoint(project_id, label)` が既に実装済み（`src/research_team/project/manager.py`）
- `coordinator.py` の `_run_research()` はアクティブプロジェクトIDを `_project_manager.get_active_id()` で取得できる
- 現在は調査完了後に最終成果物のみ保存している
- スペシャリスト全員の調査完了後（`_run_specialist_pass()` 後）にチェックポイントを作成し、CSM 経由でユーザーに通知する

**変更方針:** `_run_research()` の `combined_content` 算出後（L260直後）に `create_checkpoint` と `_notify` を追加。アクティブプロジェクトが存在しない場合は何もしない（スキップ）。

### Files:
- Modify: `src/research_team/orchestrator/coordinator.py:255-275`
- Modify: `tests/unit/test_coordinator.py`（テスト追加）

---

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_coordinator.py` に追加:

```python
@pytest.mark.asyncio
async def test_checkpoint_created_after_specialist_pass(tmp_path):
    """スペシャリストパス完了後にチェックポイントが作成されることを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    
    # プロジェクトを作成してアクティブにする
    project = coord._project_manager.init("テストプロジェクト")
    coord._project_manager.switch(project.id)

    notify_calls: list[tuple[str, str]] = []
    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))
    coord._notify = fake_notify
    coord._log = AsyncMock()

    async def fake_agent_run(message, workspace_dir=None, search_port=0):
        yield make_text_event("調査結果 " * 100)
        yield make_end_event()

    coord._pm_agent.run = fake_agent_run
    coord._team_builder.run = fake_agent_run

    from research_team.agents.dynamic.factory import DynamicSpecialistAgent
    async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
        yield make_text_event("専門家調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
        await coord.run(ResearchRequest(topic="テストテーマ"))

    # チェックポイントが作成されたか確認
    checkpoints_dir = coord._project_manager._workspace / "projects" / project.id / "checkpoints"
    checkpoint_files = list(checkpoints_dir.glob("*.json")) if checkpoints_dir.exists() else []
    assert len(checkpoint_files) >= 1, "チェックポイントが作成されていない"

    # CSM 経由で中間成果物の通知がされたか確認
    csm_msgs = [msg for agent, msg in notify_calls if agent == "CSM"]
    assert any("中間" in msg or "チェックポイント" in msg or "draft" in msg.lower() for msg in csm_msgs), \
        f"中間成果物通知がない。notify_calls={notify_calls}"
```

- [ ] **Step 2: テストを実行して失敗を確認**

```
python -m pytest tests/unit/test_coordinator.py::test_checkpoint_created_after_specialist_pass -v
```

期待: FAIL（チェックポイントが作成されていない）

- [ ] **Step 3: coordinator.py を修正 — チェックポイント作成とユーザー通知を追加**

`_run_research()` の `combined_content = await self._run_specialist_pass(...)` の直後（L260直後）に以下を追加:

```python
# 中間成果物チェックポイントを作成
active_id = self._project_manager.get_active_id()
if active_id:
    try:
        checkpoint_path = self._project_manager.create_checkpoint(
            active_id, f"draft_pass1"
        )
        await self._notify(
            "CSM",
            f"📁 中間成果物を保存しました。\nチェックポイント: {checkpoint_path}",
        )
    except Exception as exc:
        logger.warning("create_checkpoint failed: %s", exc)
```

- [ ] **Step 4: テストを実行してパスを確認**

```
python -m pytest tests/unit/test_coordinator.py::test_checkpoint_created_after_specialist_pass -v
```

期待: PASS

- [ ] **Step 5: 全ユニットテストを実行**

```
python -m pytest tests/unit/ -v
```

期待: 全テスト PASS

- [ ] **Step 6: コミット**

```
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat(us2): create checkpoint and notify user after specialist pass (2-4)"
```

---

## Chunk 3: Task 2-5 — 追加リクエストループ

**Context:**
- `run_interactive()` は現在、テーマ確認後に `await self.run(request)` を一度だけ呼んで終了する
- 調査完了後に CSM がユーザーに「追加の調査や修正はありますか？」と問い、ユーザーが肯定的な返答をすれば新しいリクエストとして続行するループを実装する
- 追加リクエストの「いいえ」や「終了」などの否定で終了する
- `_is_affirmative()` 関数（`はい/yes/ok` 判定）と並んで `_is_negative()` 関数を追加する
- UI がない（CLI モード）場合は追加ループなしで終了（既存挙動を維持）

**変更方針:** `run_interactive()` に追加ループを実装する。`run()` 完了後に CSM が継続確認メッセージを送り、ユーザー返答に応じてループするか終了する。

### Files:
- Modify: `src/research_team/orchestrator/coordinator.py`
- Modify: `tests/unit/test_coordinator.py`（テスト追加）
- Modify: `tests/unit/test_us1.py`（既存テストへの影響確認のみ）

---

- [ ] **Step 1: `_is_negative()` 関数の失敗テストを書く**

`tests/unit/test_coordinator.py` に追加:

```python
from research_team.orchestrator.coordinator import _is_negative

def test_is_negative_recognizes_no():
    assert _is_negative("いいえ") is True
    assert _is_negative("no") is True
    assert _is_negative("終了") is True
    assert _is_negative("終わり") is True
    assert _is_negative("完了") is True

def test_is_negative_does_not_match_affirmative():
    assert _is_negative("はい") is False
    assert _is_negative("yes") is False
    assert _is_negative("追加調査してほしい") is False
```

- [ ] **Step 2: テストを実行して失敗を確認**

```
python -m pytest tests/unit/test_coordinator.py::test_is_negative_recognizes_no tests/unit/test_coordinator.py::test_is_negative_does_not_match_affirmative -v
```

期待: FAIL（`_is_negative` が存在しない）

- [ ] **Step 3: `_is_negative()` 関数を coordinator.py に追加**

`_is_affirmative()` 関数の直後（L64の後）に追加:

```python
def _is_negative(text: str) -> bool:
    normalized = text.strip().lower()
    negatives = {"いいえ", "no", "n", "終了", "終わり", "完了", "やめる", "stop", "quit", "exit"}
    if normalized in negatives:
        return True
    if normalized.startswith(("いいえ", "no ", "終了", "終わり")):
        return True
    return False
```

- [ ] **Step 4: `_is_negative` テストをパスさせる**

```
python -m pytest tests/unit/test_coordinator.py::test_is_negative_recognizes_no tests/unit/test_coordinator.py::test_is_negative_does_not_match_affirmative -v
```

期待: PASS

- [ ] **Step 5: 追加リクエストループのテストを書く**

`tests/unit/test_coordinator.py` に追加:

```python
@pytest.mark.asyncio
async def test_run_interactive_additional_request_loop(tmp_path):
    """調査完了後に追加リクエストを受け付けるループが動作することを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    # UIモック
    messages_sent: list[tuple[str, str]] = []
    async def fake_notify(agent: str, message: str) -> None:
        messages_sent.append((agent, message))
    coord._notify = fake_notify
    coord._log = AsyncMock()

    # ユーザーメッセージのシーケンス:
    # 1回目: テーマ入力
    # 2回目: 確認 → "はい"
    # 3回目: 調査完了後の追加リクエスト確認 → "別のテーマも調査して"
    # 4回目: 確認 → "はい"
    # 5回目: 追加調査完了後の継続確認 → "いいえ"
    user_inputs = [
        "テストテーマA",
        "はい",
        "別のテーマも調査して",  # 追加リクエスト
        "はい",                   # 確認
        "いいえ",                 # 終了
    ]
    input_iter = iter(user_inputs)
    async def fake_wait_for_user_message() -> str:
        return next(input_iter)

    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.wait_for_user_message = fake_wait_for_user_message
    coord._ui = mock_ui

    # run() をモック（実際の調査は行わない）
    run_calls: list[ResearchRequest] = []
    async def fake_run(request: ResearchRequest) -> ResearchResult:
        run_calls.append(request)
        return ResearchResult(
            content="調査結果",
            output_path=str(tmp_path / "report.md"),
            quality_score=1.0,
            iterations=1,
        )
    coord.run = fake_run

    await coord.run_interactive(depth="standard")

    # run() が2回呼ばれたことを確認（初回 + 追加リクエスト1回）
    assert len(run_calls) == 2, f"run() が{len(run_calls)}回呼ばれた（期待: 2回）"
    assert run_calls[0].topic == "テストテーマA"
    # 2回目は追加リクエストのテーマ
    assert "別のテーマ" in run_calls[1].topic or run_calls[1].topic != "テストテーマA"
```

- [ ] **Step 6: テストを実行して失敗を確認**

```
python -m pytest tests/unit/test_coordinator.py::test_run_interactive_additional_request_loop -v
```

期待: FAIL（現在のループは追加リクエストを受け付けない）

- [ ] **Step 7: `run_interactive()` に追加リクエストループを実装**

`coordinator.py` の `run_interactive()` を以下のように変更する（L330-L372）:

```python
async def run_interactive(
    self,
    depth: str = "standard",
    output_format: str = "markdown",
) -> None:
    if self._ui:
        depth_label = {"quick": "簡易", "standard": "標準", "deep": "詳細"}.get(depth, depth)
        # 初回テーマ入力ループ
        while True:
            await self._ui.append_agent_message(
                "CSM",
                "こんにちは！リサーチするテーマを入力してください。"
            )
            topic = await self._ui.wait_for_user_message()
            await self._log("running", f"テーマ: {topic}")

            await self._ui.append_agent_message(
                "CSM",
                f"テーマ「{topic}」、深さ「{depth_label}」で調査します。よろしいですか？（はい／いいえ）"
            )
            answer = await self._ui.wait_for_user_message()
            if _is_affirmative(answer):
                break
            await self._ui.append_agent_message(
                "CSM",
                "承知しました。もう一度テーマを入力してください。"
            )
    else:
        topic = input("テーマを入力してください: ")

    # 調査ループ（初回 + 追加リクエスト）
    while True:
        request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
        try:
            result = await self.run(request)
            if self._ui:
                await self._log("done", f"完了: {result.output_path}")
        except Exception as exc:
            err_msg = f"エラーが発生しました: {exc}"
            tb = traceback.format_exc()
            logger.error("run_interactive error:\n%s", tb)
            await self._notify("System", err_msg)
            await self._log("running", err_msg)
            if self._ui:
                await self._ui.append_log("running", tb)
            raise

        # UI がない場合は追加ループなし
        if not self._ui:
            break

        # 追加リクエスト確認
        await self._ui.append_agent_message(
            "CSM",
            "調査が完了しました。追加の調査や修正はありますか？（内容を入力するか、「いいえ」で終了）"
        )
        additional = await self._ui.wait_for_user_message()

        if _is_negative(additional):
            await self._ui.append_agent_message("CSM", "ありがとうございました。調査を終了します。")
            break

        # 追加リクエストを確認
        await self._ui.append_agent_message(
            "CSM",
            f"追加リクエスト「{additional}」を受け付けました。続けますか？（はい／いいえ）"
        )
        confirm = await self._ui.wait_for_user_message()
        if not _is_affirmative(confirm):
            await self._ui.append_agent_message("CSM", "承知しました。調査を終了します。")
            break

        topic = additional
```

- [ ] **Step 8: テストを実行してパスを確認**

```
python -m pytest tests/unit/test_coordinator.py::test_run_interactive_additional_request_loop -v
```

期待: PASS

- [ ] **Step 9: 既存テストが壊れていないか確認**

```
python -m pytest tests/unit/ -v
```

期待: 全テスト PASS（特に test_us1.py の run_interactive 関連テスト）

- [ ] **Step 10: コミット**

```
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat(us2): add additional request loop after research completion (2-5)"
```

---

## Chunk 4: 統合確認

- [ ] **Step 1: 全テストスイートを実行**

```
python -m pytest tests/unit/ tests/integration/ -v --tb=short
```

期待: 全テスト PASS（既存テスト含む）

- [ ] **Step 2: tasks.md の US-2 状態を更新**

`docs/tasks.md` の US-2 テーブルを更新:

```markdown
| 2-3 | WBS 構造（マイルストン・タスク）を UI に表示 | ✅ 実装済 |
| 2-4 | マイルストン到達時に中間成果物をユーザーに共有する | ✅ 実装済 |
| 2-5 | 調査中いつでも CSM への追加リクエスト（テーマ変更・追加指示）を受け付けるループ | ✅ 実装済 |
```

- [ ] **Step 3: コミット**

```
git add docs/tasks.md
git commit -m "docs: mark US-2 tasks 2-3, 2-4, 2-5 as complete"
```

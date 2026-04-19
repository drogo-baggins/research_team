# US-5-2 Specialist Discussion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ペルソナ付き専門家エージェントがターン制ディスカッションを行い、対談トランスクリプトをMDファイルとして保存・最終成果物に組み込み、WBSペインにリンク表示する。

**Architecture:** `DiscussionOrchestrator` クラスを `src/research_team/orchestrator/discussion.py` に独立実装し、 `coordinator.py` から `style in {"magazine_column", "book_chapter"}` のときのみ呼び出す。対談エージェントは既存の `DynamicSpecialistAgent` パターンを踏襲しペルソナテンプレートで上書き。WBSリンク表示は `control_ui.py` に `show_artifact_link()` を、`control_page.html` に `addArtifactLink()` JS関数を追加して実現する。

**Tech Stack:** Python asyncio, Playwright (UIリンク表示), PiAgentClient (エージェント呼び出し), Jinja2不使用 (str.format テンプレート)

---

## Chunk 1: テンプレート + DiscussionOrchestrator コアロジック

### Task 1: ペルソナテンプレートファイルの作成

**Files:**
- Create: `src/research_team/agents/dynamic/templates/discussion_persona.md.template`

- [ ] **Step 1: テンプレートファイルを作成する**

```markdown
# {name} — ディスカッション参加者

## あなたの人物像
- 肩書: {expertise} の専門家
- 性格: {personality}
- 口調: {speaking_style}
- 確固たる持論: {core_belief}
- 批判の矛先: {pet_peeve}

## 発言ルール（厳守）
- 直前の発言者の主張を1文で要約してから反応する
- 同意するときも「ただし〜」「一方で〜」という留保を必ず付ける
- 賛成し続けることは禁止。毎ターン最低1つ異論・疑問・補足を出す
- 200〜300文字程度で発言する（長すぎず短すぎず）
- 自分の名前で始めず、発言内容だけを返す

## 現在の議論の流れ
{discussion_so_far}

## あなたの調査結果（参照用・内部知識として使う）
{own_research}

## Output Rules (CRITICAL - NO EXCEPTIONS)
- Return ONLY your spoken contribution as plain text
- Do NOT include your name, labels, or markdown headers
- Do NOT say "I saved" or reference files
- Respond in Japanese
```

- [ ] **Step 2: テンプレートのプレースホルダーを確認する**

プレースホルダーが `{name}`, `{expertise}`, `{personality}`, `{speaking_style}`, `{core_belief}`, `{pet_peeve}`, `{discussion_so_far}`, `{own_research}` の8つだけであること、余分な `{` `}` がないことを目視確認する。

---

### Task 2: DiscussionOrchestrator の実装（TDD）

**Files:**
- Create: `tests/unit/test_discussion.py`
- Create: `src/research_team/orchestrator/discussion.py`

- [ ] **Step 1: テストファイルを作成する**

```python
# tests/unit/test_discussion.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas


# ── generate_personas ──────────────────────────────────────────────

def test_generate_personas_returns_one_per_specialist():
    specialists = [
        {"name": "Alice", "expertise": "経済学", "research": "GDP成長..."},
        {"name": "Bob", "expertise": "社会学", "research": "格差拡大..."},
    ]
    personas = generate_personas(specialists)
    assert len(personas) == 2


def test_generate_personas_has_required_keys():
    specialists = [{"name": "Alice", "expertise": "経済学", "research": "..."}]
    persona = generate_personas(specialists)[0]
    for key in ("name", "expertise", "personality", "speaking_style", "core_belief", "pet_peeve"):
        assert key in persona, f"missing key: {key}"


def test_generate_personas_name_matches_specialist():
    specialists = [{"name": "TaroSato", "expertise": "物理学", "research": "量子..."}]
    persona = generate_personas(specialists)[0]
    assert persona["name"] == "TaroSato"


# ── DiscussionOrchestrator ─────────────────────────────────────────

@pytest.fixture
def specialists():
    return [
        {"name": "Alice", "expertise": "経済学", "research": "GDP..."},
        {"name": "Bob", "expertise": "社会学", "research": "格差..."},
    ]


@pytest.fixture
def personas(specialists):
    from research_team.orchestrator.discussion import generate_personas
    return generate_personas(specialists)


@pytest.mark.asyncio
async def test_run_returns_non_empty_transcript(specialists, personas):
    """DiscussionOrchestrator.run() は非空のMarkdown文字列を返す。"""
    async def fake_stream(agent, message, agent_name, **kwargs):
        return f"{agent_name}の発言サンプル"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="AIの未来")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_run_includes_speaker_names(specialists, personas):
    """トランスクリプトに各エージェント名が含まれる。"""
    async def fake_stream(agent, message, agent_name, **kwargs):
        return "テスト発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="テスト")
    assert "Alice" in result
    assert "Bob" in result


@pytest.mark.asyncio
async def test_run_calls_stream_fn_correct_times(specialists, personas):
    """turns=2, specialists=2 なら stream_fn が 2*2=4 回呼ばれる。"""
    call_count = 0

    async def fake_stream(agent, message, agent_name, **kwargs):
        nonlocal call_count
        call_count += 1
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=2)
    await orch.run(specialists=specialists, personas=personas, topic="テスト")
    assert call_count == 4


@pytest.mark.asyncio
async def test_run_respects_env_turns(specialists, personas, monkeypatch):
    """RT_DISCUSSION_TURNS 環境変数が turns を上書きする。"""
    monkeypatch.setenv("RT_DISCUSSION_TURNS", "3")
    call_count = 0

    async def fake_stream(agent, message, agent_name, **kwargs):
        nonlocal call_count
        call_count += 1
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    await orch.run(specialists=specialists, personas=personas, topic="テスト")
    # 3 turns * 2 specialists = 6
    assert call_count == 6


@pytest.mark.asyncio
async def test_run_transcript_has_markdown_header(specialists, personas):
    """トランスクリプトはMarkdownの見出しで始まる。"""
    async def fake_stream(agent, message, agent_name, **kwargs):
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="AIの未来")
    assert result.startswith("#")


@pytest.mark.asyncio
async def test_run_handles_empty_stream_response(specialists, personas):
    """stream_fn が空文字を返しても例外が出ない。"""
    async def fake_stream(agent, message, agent_name, **kwargs):
        return ""

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="テスト")
    assert isinstance(result, str)
```

- [ ] **Step 2: テストが失敗することを確認する**

```
python -m pytest tests/unit/test_discussion.py -x -q
```

Expected: `ModuleNotFoundError` または `ImportError`（実装がないため）

- [ ] **Step 3: `discussion.py` を実装する**

```python
# src/research_team/orchestrator/discussion.py
from __future__ import annotations

import os
from collections.abc import Callable, Awaitable
from pathlib import Path

from research_team.agents.dynamic.factory import DynamicSpecialistAgent

_TEMPLATE_PATH = Path(__file__).parent.parent / "agents" / "dynamic" / "templates" / "discussion_persona.md.template"

_PERSONALITY_MAP = [
    ("懐疑的・批判的思考家", "具体例や反例から入る", "「データなき主張は仮説に過ぎない」", "根拠のない楽観論"),
    ("楽観的・ビジョン思考家", "大局観・未来像から入る", "「テクノロジーは必ず人間を解放する」", "短期的・局所的な悲観論"),
    ("実務家・現場重視", "現場の実例・コスト感覚から入る", "「理論より実装が真実を語る」", "現場を知らない理想論"),
    ("歴史家・文脈重視", "歴史的先例・パターンから入る", "「新しい問題の90%は既に解かれている」", "歴史を無視した断絶論"),
    ("倫理学者・社会影響重視", "価値観・社会的影響から入る", "「技術の目的は人間の尊厳を守ること」", "倫理を後回しにする効率優先論"),
]


def generate_personas(specialists: list[dict]) -> list[dict]:
    personas = []
    for i, spec in enumerate(specialists):
        p = _PERSONALITY_MAP[i % len(_PERSONALITY_MAP)]
        personas.append({
            "name": spec["name"],
            "expertise": spec["expertise"],
            "personality": p[0],
            "speaking_style": p[1],
            "core_belief": p[2],
            "pet_peeve": p[3],
        })
    return personas


class DiscussionOrchestrator:
    def __init__(
        self,
        stream_fn: Callable[..., Awaitable[str]],
        turns: int = 2,
    ) -> None:
        self._stream_fn = stream_fn
        self._default_turns = turns

    async def run(
        self,
        specialists: list[dict],
        personas: list[dict],
        topic: str,
    ) -> str:
        turns = int(os.environ.get("RT_DISCUSSION_TURNS", str(self._default_turns)))
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")

        discussion_log: list[str] = []
        lines: list[str] = [
            f"# スペシャリスト対談: {topic}",
            "",
        ]

        persona_map = {p["name"]: p for p in personas}

        for turn_idx in range(turns):
            for spec in specialists:
                name = spec["name"]
                persona = persona_map.get(name, {})
                discussion_so_far = (
                    "\n".join(discussion_log) if discussion_log else "（まだ発言はありません。最初の発言者としてテーマを提起してください）"
                )
                system_prompt = template.format(
                    name=name,
                    expertise=persona.get("expertise", spec.get("expertise", "")),
                    personality=persona.get("personality", ""),
                    speaking_style=persona.get("speaking_style", ""),
                    core_belief=persona.get("core_belief", ""),
                    pet_peeve=persona.get("pet_peeve", ""),
                    discussion_so_far=discussion_so_far,
                    own_research=spec.get("research", ""),
                )
                agent = DynamicSpecialistAgent(
                    name=name,
                    expertise=persona.get("expertise", spec.get("expertise", "")),
                    system_prompt=system_prompt,
                )
                utterance = await self._stream_fn(
                    agent,
                    f"テーマ「{topic}」について発言してください。",
                    name,
                )
                utterance = utterance.strip() if utterance else ""
                entry = f"**{name}**: {utterance}" if utterance else f"**{name}**: （発言なし）"
                discussion_log.append(entry)
                lines.append(entry)
                lines.append("")

        return "\n".join(lines)
```

- [ ] **Step 4: テストを実行して全件パスを確認する**

```
python -m pytest tests/unit/test_discussion.py -x -q
```

Expected: 全テストがパス。

- [ ] **Step 5: コミットする**

```bash
git add src/research_team/agents/dynamic/templates/discussion_persona.md.template
git add src/research_team/orchestrator/discussion.py
git add tests/unit/test_discussion.py
git commit -m "feat: add DiscussionOrchestrator with persona-based turn system (US-5-2)"
```

---

## Chunk 2: ArtifactWriter + ControlUI 拡張

### Task 3: ArtifactWriter に write_discussion() を追加

**Files:**
- Modify: `src/research_team/output/artifact_writer.py`
- Modify: `tests/unit/test_discussion.py` （テスト追記）

- [ ] **Step 1: テストを追記する**

`tests/unit/test_discussion.py` の末尾に以下を追加：

```python
# ── ArtifactWriter.write_discussion ───────────────────────────────

from research_team.output.artifact_writer import ArtifactWriter


def test_write_discussion_creates_file(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_discussion(run_id=1, transcript="# 対談\n\n**Alice**: テスト発言")
    assert Path(path).exists()


def test_write_discussion_file_contains_transcript(tmp_path):
    writer = ArtifactWriter(tmp_path)
    transcript = "# 対談\n\n**Alice**: テスト発言"
    path = writer.write_discussion(run_id=1, transcript=transcript)
    content = Path(path).read_text(encoding="utf-8")
    assert "Alice" in content
    assert "テスト発言" in content


def test_write_discussion_filename_contains_run_id(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_discussion(run_id=42, transcript="# 対談")
    assert "run42" in Path(path).name
```

- [ ] **Step 2: テストが失敗することを確認する**

```
python -m pytest tests/unit/test_discussion.py::test_write_discussion_creates_file -x -q
```

Expected: `AttributeError: 'ArtifactWriter' object has no attribute 'write_discussion'`

- [ ] **Step 3: `artifact_writer.py` に `write_discussion()` を追加する**

`write_specialist_draft` メソッドの直後（L98の後）に以下を追加：

```python
    def write_discussion(self, run_id: int, transcript: str) -> str:
        """対談トランスクリプトをMDファイルとして保存する。"""
        date_str = datetime.now().strftime("%Y%m%d")
        path = self._dir / f"discussion_run{run_id}_{date_str}.md"
        path.write_text(transcript, encoding="utf-8")
        return str(path)
```

- [ ] **Step 4: テストを実行して全件パスを確認する**

```
python -m pytest tests/unit/test_discussion.py -x -q
```

Expected: 全テストがパス。

---

### Task 4: ControlUI に show_artifact_link() を追加

**Files:**
- Modify: `src/research_team/ui/control_ui.py`
- Modify: `src/research_team/ui/control_page.html`
- Modify: `tests/unit/test_discussion.py` （テスト追記）

- [ ] **Step 1: control_page.html に CSS + HTML + JS を追加する**

HTML の WBSペイン（`<div class="wbs-pane">` 内、 `<div class="wbs-approval-panel"` の直前）に以下を追加：

```html
        <div class="artifact-links" id="artifactLinks"></div>
```

CSS の `.wbs-approval-panel` スタイル定義の直前（~L196付近）に以下を追加：

```css
    /* ── 成果物リンク ── */
    .artifact-links { padding: 6px 12px; flex-shrink: 0; }
    .artifact-link-item { display: flex; align-items: center; gap: 6px; font-size: 11px; margin-bottom: 4px; }
    .artifact-link-item a { color: #60a5fa; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .artifact-link-item a:hover { text-decoration: underline; }
    .artifact-link-badge { background: #1e3a5a; color: #93c5fd; border-radius: 3px; padding: 1px 5px; font-size: 10px; flex-shrink: 0; }
```

JS の `showWbsApproval` 関数の直前（~L436）に以下を追加：

```javascript
    function addArtifactLink(label, filePath) {
      const container = document.getElementById('artifactLinks');
      if (!container) return;
      const href = 'file:///' + filePath.replace(/\\/g, '/');
      const item = document.createElement('div');
      item.className = 'artifact-link-item';
      item.innerHTML = `<span class="artifact-link-badge">📄</span><a href="${href}" target="_blank" title="${filePath}">${label}</a>`;
      container.appendChild(item);
    }
```

- [ ] **Step 2: control_ui.py に show_artifact_link() を追加する**

`close` メソッドの直前（L193）に以下を追加：

```python
    async def show_artifact_link(self, label: str, path: str) -> None:
        if not self._is_alive():
            return
        assert self._page
        try:
            await self._page.evaluate(
                f"addArtifactLink({json.dumps(label)}, {json.dumps(path)})"
            )
        except Exception:
            pass
```

- [ ] **Step 3: テストを追記する**

`tests/unit/test_discussion.py` の末尾に以下を追加：

```python
# ── ControlUI.show_artifact_link ──────────────────────────────────

@pytest.mark.asyncio
async def test_show_artifact_link_calls_evaluate(tmp_path):
    """show_artifact_link は page.evaluate を呼ぶ。"""
    from research_team.ui.control_ui import ControlUI
    from unittest.mock import AsyncMock, MagicMock, PropertyMock

    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate = AsyncMock()

    ui = ControlUI.__new__(ControlUI)
    ui._page = mock_page

    await ui.show_artifact_link("対談トランスクリプト", "/tmp/discussion.md")
    mock_page.evaluate.assert_called_once()
    call_arg = mock_page.evaluate.call_args[0][0]
    assert "addArtifactLink" in call_arg
    assert "対談トランスクリプト" in call_arg


@pytest.mark.asyncio
async def test_show_artifact_link_noop_when_page_closed(tmp_path):
    """ページが閉じているとき show_artifact_link は例外を出さない。"""
    from research_team.ui.control_ui import ControlUI
    from unittest.mock import MagicMock

    mock_page = MagicMock()
    mock_page.is_closed.return_value = True

    ui = ControlUI.__new__(ControlUI)
    ui._page = mock_page

    await ui.show_artifact_link("ラベル", "/tmp/test.md")
```

- [ ] **Step 4: テストを実行して全件パスを確認する**

```
python -m pytest tests/unit/test_discussion.py -x -q
```

Expected: 全テストがパス。

- [ ] **Step 5: コミットする**

```bash
git add src/research_team/output/artifact_writer.py
git add src/research_team/ui/control_ui.py
git add src/research_team/ui/control_page.html
git add tests/unit/test_discussion.py
git commit -m "feat: add write_discussion to ArtifactWriter and show_artifact_link to ControlUI (US-5-2)"
```

---

## Chunk 3: coordinator.py への統合

### Task 5: coordinator.py に対談フローを組み込む

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`
- Modify: `tests/unit/test_discussion.py` （テスト追記）

対談フローの挿入位置：`combined_content = await self._run_specialist_pass(...)` の直後（L541〜549）、`if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:` ブロックの直前。

- [ ] **Step 1: テストを追記する**

`tests/unit/test_discussion.py` の末尾に以下を追加：

```python
# ── coordinator discussion integration ────────────────────────────

@pytest.mark.asyncio
async def test_coordinator_calls_discussion_for_magazine_style(tmp_path, monkeypatch):
    """magazine_column スタイルで DiscussionOrchestrator.run が呼ばれる。"""
    from research_team.orchestrator.coordinator import ResearchCoordinator
    from unittest.mock import AsyncMock, patch, MagicMock

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    discussion_called = []

    async def fake_discussion_run(specialists, personas, topic):
        discussion_called.append(True)
        return "# 対談\n\n**Alice**: テスト"

    with patch("research_team.orchestrator.coordinator.DiscussionOrchestrator") as MockOrch:
        instance = MagicMock()
        instance.run = AsyncMock(side_effect=fake_discussion_run)
        MockOrch.return_value = instance

        # _run_specialist_pass と他の重い処理をモックで短絡
        coord._run_specialist_pass = AsyncMock(return_value="調査内容")
        coord._run_audit = AsyncMock(return_value={"decision": "PASS", "overall_score": 0.9})
        coord._wbs_approval_loop = AsyncMock(return_value=True)
        coord._push_wbs = AsyncMock()
        coord._run_pm = AsyncMock(return_value=({"depth": "standard", "style": "magazine_column"}, [{"name": "Alice", "expertise": "経済学"}]))
        coord._run_team_builder = AsyncMock(return_value=[{"name": "Alice", "expertise": "経済学"}])

        from research_team.orchestrator.coordinator import ResearchRequest
        request = ResearchRequest(topic="テスト", depth="standard", style="magazine_column")

        with patch.object(coord, "_stream_agent_output", AsyncMock(return_value="フォーマット済みコンテンツ")):
            with patch.object(coord, "_start_search_server", AsyncMock()):
                with patch.object(coord, "_stop_search_server", AsyncMock()):
                    try:
                        await coord.run_research(request)
                    except Exception:
                        pass  # WBS・UI依存のエラーは無視

        assert len(discussion_called) > 0, "DiscussionOrchestrator.run が呼ばれなかった"


@pytest.mark.asyncio
async def test_coordinator_skips_discussion_for_research_report_style(tmp_path):
    """research_report スタイルでは DiscussionOrchestrator.run が呼ばれない。"""
    from research_team.orchestrator.coordinator import ResearchCoordinator
    from unittest.mock import AsyncMock, patch, MagicMock

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    discussion_called = []

    with patch("research_team.orchestrator.coordinator.DiscussionOrchestrator") as MockOrch:
        instance = MagicMock()
        instance.run = AsyncMock(side_effect=lambda **kw: discussion_called.append(True) or "# 対談")
        MockOrch.return_value = instance

        coord._run_specialist_pass = AsyncMock(return_value="調査内容")
        coord._run_audit = AsyncMock(return_value={"decision": "PASS", "overall_score": 0.9})
        coord._wbs_approval_loop = AsyncMock(return_value=True)
        coord._push_wbs = AsyncMock()
        coord._run_pm = AsyncMock(return_value=({"depth": "standard", "style": "research_report"}, [{"name": "Alice", "expertise": "経済学"}]))
        coord._run_team_builder = AsyncMock(return_value=[{"name": "Alice", "expertise": "経済学"}])

        from research_team.orchestrator.coordinator import ResearchRequest
        request = ResearchRequest(topic="テスト", depth="standard", style="research_report")

        with patch.object(coord, "_stream_agent_output", AsyncMock(return_value="サマリー")):
            with patch.object(coord, "_start_search_server", AsyncMock()):
                with patch.object(coord, "_stop_search_server", AsyncMock()):
                    try:
                        await coord.run_research(request)
                    except Exception:
                        pass

        assert len(discussion_called) == 0, "research_report で DiscussionOrchestrator.run が呼ばれた"
```

- [ ] **Step 2: テストが失敗することを確認する**

```
python -m pytest tests/unit/test_discussion.py::test_coordinator_calls_discussion_for_magazine_style -x -q
```

Expected: `ImportError` または `AssertionError`（DiscussionOrchestrator が coordinator でまだ使われていないため）

- [ ] **Step 3: coordinator.py に import を追加する**

ファイル冒頭のimport群に以下を追加（`from research_team.orchestrator.quality_loop` の後あたり）：

```python
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas
```

- [ ] **Step 4: coordinator.py に `_run_discussion` メソッドを追加する**

`_stream_agent_output` メソッドの直前付近に以下のメソッドを追加する：

```python
    async def _run_discussion(
        self,
        specialists: list[dict],
        topic: str,
        artifact_writer: "ArtifactWriter | None",
        run_id: int,
    ) -> str:
        personas = generate_personas(specialists)
        orch = DiscussionOrchestrator(stream_fn=self._stream_agent_output, turns=2)
        transcript = await orch.run(specialists=specialists, personas=personas, topic=topic)
        if artifact_writer:
            try:
                discussion_path = artifact_writer.write_discussion(run_id=run_id, transcript=transcript)
                if self._ui and hasattr(self._ui, "show_artifact_link"):
                    await self._ui.show_artifact_link("対談トランスクリプト", discussion_path)
            except Exception as exc:
                logger.warning("write_discussion failed: %s", exc)
        return transcript
```

- [ ] **Step 5: `run_research` 内で `_run_discussion` を呼び出す**

`combined_content = await self._run_specialist_pass(...)` ブロック（L541〜549）の直後、`if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:` の直前に以下を挿入する：

```python
        if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:
            discussion_transcript = await self._run_discussion(
                specialists=factory.agents_as_list() if hasattr(factory, "agents_as_list") else [
                    {"name": name, "expertise": ag._expertise, "research": ""}
                    for name, ag in factory.agents.items()
                ],
                topic=topic,
                artifact_writer=artifact_writer,
                run_id=run_id,
            )
            combined_content = combined_content + "\n\n---\n\n" + discussion_transcript
```

> **注意**: `_STYLES_WITHOUT_EXEC_SUMMARY` のチェックがこの後にも登場するので、二重にならないよう確認すること。元の `if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:` ブロック（CSMフォーマット処理）はそのまま残す。追加するのはその直前のみ。

実際の挿入位置は coordinator.py の以下のパターンを探して直前に挿入：

```python
        if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:
            format_prompt = self._build_format_prompt(
```

- [ ] **Step 6: factory からスペシャリスト情報を取得する方法を確認する**

`coordinator.py` の `_run_specialist_pass` の呼び出し前後で `factory` オブジェクトの型と `agents` プロパティを確認する（`DynamicAgentFactory.agents` は `dict[str, DynamicSpecialistAgent]`）。

`_run_discussion` に渡す `specialists` リストは以下のように構築する（`_run_specialist_pass` 呼び出し後、researchテキストは空文字列で渡す — ディスカッション用エージェントが自身の調査結果を `system_prompt` として持つため）：

```python
discussion_specialists = [
    {"name": name, "expertise": ag._expertise, "research": combined_content}
    for name, ag in factory.agents.items()
]
```

`research` に `combined_content` を渡すことで、各専門家が自分の専門知識ベースとして調査結果全体を参照できる。

- [ ] **Step 7: テストを実行して全件パスを確認する**

```
python -m pytest tests/unit/test_discussion.py -x -q
```

Expected: 全テストがパス。

- [ ] **Step 8: ユニットテスト全件を実行する**

```
python -m pytest tests/unit/ -x -q
```

Expected: 全テストがパス（既存テストが壊れていないこと）。

- [ ] **Step 9: tasks.md の US-5-2 を完了にする**

`docs/tasks.md` の US-5-2 の `❌` を `✅` に変更する。

- [ ] **Step 10: コミットする**

```bash
git add src/research_team/orchestrator/coordinator.py
git add docs/tasks.md
git commit -m "feat: integrate DiscussionOrchestrator into coordinator for magazine/book styles (US-5-2)"
```

---

## Final Verification

- [ ] `python -m pytest tests/unit/ -x -q` を実行し、全件パスを確認する
- [ ] 出力をレスポンスに含める（AGENTS.md 必須要件）

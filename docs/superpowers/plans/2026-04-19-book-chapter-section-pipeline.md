# Book Chapter Section Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `book_chapter` スタイル選択時のみ、PMが章・セクション構造を先に設計し、専門家がセクション単位で執筆するパイプラインを追加する。

**Architecture:** WBS承認後、PMが「セクション分解プロンプト」で章→節の階層構造（JSON）を生成する。Coordinatorはその構造をイテレートして専門家を逐次呼び出し、前節の内容を文脈として引き継ぎながら節テキストを積み上げる。既存の `research_report` 等のフローは一切変更しない。

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, pytest

---

## 変更ファイル一覧

| ファイル | 種別 | 変更内容 |
|---|---|---|
| `src/research_team/orchestrator/book_pipeline.py` | **新規作成** | セクション分解・セクション執筆ロジック |
| `src/research_team/orchestrator/coordinator.py` | **修正** | `book_chapter` 時に新パイプラインへ分岐 |
| `src/research_team/output/artifact_writer.py` | **修正** | `write_book_section()` メソッド追加 |
| `src/research_team/agents/skills/pm/SKILL.md` | **修正** | セクション分解の出力フォーマットを記述 |
| `tests/unit/test_book_pipeline.py` | **新規作成** | book_pipeline のユニットテスト |
| `tests/unit/test_artifact_writer.py` | **修正** | `write_book_section` のテスト追加 |

---

## Chunk 1: データ構造とArtifactWriter拡張

### Task 1: BookSection / BookOutline モデル定義

**Files:**
- Create: `src/research_team/orchestrator/book_pipeline.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_book_pipeline.py
from research_team.orchestrator.book_pipeline import BookSection, BookOutline

def test_book_section_fields():
    sec = BookSection(
        chapter_index=1,
        section_index=2,
        chapter_title="第1章 市場概観",
        section_title="1-2 競合動向",
        key_points=["A社の動向", "B社の戦略"],
        specialist_hint="経済アナリスト",
    )
    assert sec.section_id == "ch01_sec02"
    assert sec.chapter_index == 1
    assert sec.section_index == 2

def test_book_outline_all_sections():
    outline = BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "第1章",
            "sections": [
                {"section_index": 1, "section_title": "1-1", "key_points": [], "specialist_hint": ""},
                {"section_index": 2, "section_title": "1-2", "key_points": [], "specialist_hint": ""},
            ],
        }
    ])
    sections = outline.all_sections()
    assert len(sections) == 2
    assert sections[0].section_id == "ch01_sec01"
    assert sections[1].section_id == "ch01_sec02"
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q
```
期待: `ModuleNotFoundError` または `ImportError`

- [ ] **Step 3: 最小実装**

```python
# src/research_team/orchestrator/book_pipeline.py
from __future__ import annotations
from pydantic import BaseModel, Field, computed_field


class BookSection(BaseModel):
    chapter_index: int
    section_index: int
    chapter_title: str
    section_title: str
    key_points: list[str] = Field(default_factory=list)
    specialist_hint: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def section_id(self) -> str:
        return f"ch{self.chapter_index:02d}_sec{self.section_index:02d}"


class BookOutline(BaseModel):
    chapters: list[dict]

    def all_sections(self) -> list[BookSection]:
        result: list[BookSection] = []
        for ch in self.chapters:
            ch_idx = ch["chapter_index"]
            ch_title = ch["chapter_title"]
            for sec in ch.get("sections", []):
                result.append(BookSection(
                    chapter_index=ch_idx,
                    section_index=sec["section_index"],
                    chapter_title=ch_title,
                    section_title=sec["section_title"],
                    key_points=sec.get("key_points", []),
                    specialist_hint=sec.get("specialist_hint", ""),
                ))
        return result
```

- [ ] **Step 4: テストパスを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q
```
期待: `2 passed`

- [ ] **Step 5: 全ユニットテストがパスすることを確認**

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/book_pipeline.py tests/unit/test_book_pipeline.py
git commit -m "feat: add BookSection/BookOutline models for book chapter pipeline"
```

---

### Task 2: ArtifactWriter に write_book_section() 追加

**Files:**
- Modify: `src/research_team/output/artifact_writer.py`
- Modify: `tests/unit/test_artifact_writer.py`

- [ ] **Step 1: テストを書く**

既存の `tests/unit/test_artifact_writer.py` を開いてパターンを確認し、末尾に追加：

```python
def test_write_book_section(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_book_section(
        run_id=1,
        section_id="ch01_sec02",
        chapter_title="第1章 市場概観",
        section_title="1-2 競合動向",
        content="## 競合動向\n\nA社は...",
    )
    assert Path(path).exists()
    text = Path(path).read_text(encoding="utf-8")
    assert "ch01_sec02" in text
    assert "競合動向" in text
    # ファイル名にセクションIDが含まれること
    assert "ch01_sec02" in Path(path).name
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/unit/test_artifact_writer.py -x -q -k "test_write_book_section"
```
期待: `AttributeError: 'ArtifactWriter' object has no attribute 'write_book_section'`

- [ ] **Step 3: 実装**

`artifact_writer.py` の `write_specialist_draft` の直後に追加：

```python
def write_book_section(
    self,
    run_id: int,
    section_id: str,
    chapter_title: str,
    section_title: str,
    content: str,
) -> str:
    """書籍セクション単位の執筆結果を保存する。"""
    date_str = datetime.now().strftime("%Y%m%d")
    path = self._dir / f"book_{section_id}_run{run_id}_{date_str}.md"
    header = (
        f"# 書籍セクション — {section_id} / Run {run_id} ({date_str})\n\n"
        f"**章:** {chapter_title}  \n"
        f"**節:** {section_title}\n\n"
        "---\n\n"
    )
    path.write_text(header + content, encoding="utf-8")
    return str(path)
```

- [ ] **Step 4: テストパスを確認**

```bash
pytest tests/unit/test_artifact_writer.py -x -q
```

- [ ] **Step 5: 全ユニットテストがパスすることを確認**

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 6: コミット**

```bash
git add src/research_team/output/artifact_writer.py tests/unit/test_artifact_writer.py
git commit -m "feat: add write_book_section() to ArtifactWriter"
```

---

## Chunk 2: PMスキル拡張とセクション分解関数

### Task 3: PM SKILL.md にセクション分解フォーマット追記

**Files:**
- Modify: `src/research_team/agents/skills/pm/SKILL.md`

- [ ] **Step 1: 末尾に追記**

```markdown
## 書籍チャプター向けセクション分解

`book_chapter` スタイルが指定された場合、WBS承認後に以下のJSON形式でセクション構造を出力してください。
必ず ```json ``` ブロックで囲み、他のテキストは含めないでください。

```json
[
  {
    "chapter_index": 1,
    "chapter_title": "第1章 タイトル",
    "sections": [
      {
        "section_index": 1,
        "section_title": "1-1 節タイトル",
        "key_points": ["論点A", "論点B", "論点C"],
        "specialist_hint": "この節に最適な専門家の専門分野（例: 経済・金融）"
      }
    ]
  }
]
```

### セクション分解の指針
- 1章あたり3〜5節を目安とする
- 1節は単一のテーマ・論点を扱う（執筆量: 1,500〜3,000字相当）
- key_points は節の中で必ず触れるべき具体的な論点を3点以上列挙する
- specialist_hint は調査生データから最も関連性の高い専門分野を指定する
- 章・節の順序は読者が論理的に理解できる流れにする
```

- [ ] **Step 2: 全ユニットテストがパスすることを確認**（スキルファイルのみの変更なので回帰確認）

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 3: コミット**

```bash
git add src/research_team/agents/skills/pm/SKILL.md
git commit -m "feat: add book chapter section decomposition format to PM skill"
```

---

### Task 4: book_pipeline.py にセクション分解パーサーと実行関数を追加

**Files:**
- Modify: `src/research_team/orchestrator/book_pipeline.py`
- Modify: `tests/unit/test_book_pipeline.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_book_pipeline.py に追加
from research_team.orchestrator.book_pipeline import parse_outline_from_pm_output

def test_parse_outline_valid_json():
    raw = '''
    考えてみます。
    ```json
    [
      {
        "chapter_index": 1,
        "chapter_title": "第1章 概観",
        "sections": [
          {"section_index": 1, "section_title": "1-1 背景", "key_points": ["A", "B"], "specialist_hint": "歴史"}
        ]
      }
    ]
    ```
    以上です。
    '''
    outline = parse_outline_from_pm_output(raw)
    assert outline is not None
    sections = outline.all_sections()
    assert len(sections) == 1
    assert sections[0].chapter_title == "第1章 概観"
    assert sections[0].key_points == ["A", "B"]

def test_parse_outline_invalid_returns_none():
    outline = parse_outline_from_pm_output("JSONがありません")
    assert outline is None

def test_parse_outline_wrong_schema_returns_none():
    # chapter_index が欠けているケース
    raw = '```json\n[{"chapter_title": "章"}]\n```'
    outline = parse_outline_from_pm_output(raw)
    assert outline is None
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q -k "parse_outline"
```

- [ ] **Step 3: 実装**

`book_pipeline.py` に追加：

```python
import json
import re
import logging

logger = logging.getLogger(__name__)


def parse_outline_from_pm_output(raw: str) -> BookOutline | None:
    """PMの出力テキストから ```json``` ブロックを抽出してBookOutlineを返す。失敗時はNone。"""
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if not match:
        # フォールバック: 裸のJSON配列
        match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if not match:
        logger.warning("parse_outline_from_pm_output: no JSON block found")
        return None
    try:
        data = json.loads(match.group(1))
        if not isinstance(data, list):
            return None
        # 最低限のスキーマ検証
        for ch in data:
            if "chapter_index" not in ch or "chapter_title" not in ch or "sections" not in ch:
                return None
        return BookOutline(chapters=data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("parse_outline_from_pm_output: JSON parse failed: %s", exc)
        return None
```

- [ ] **Step 4: テストパスを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q
```

- [ ] **Step 5: 全ユニットテストがパスすることを確認**

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/book_pipeline.py tests/unit/test_book_pipeline.py
git commit -m "feat: add parse_outline_from_pm_output() to book_pipeline"
```

---

## Chunk 3: BookChapterPipeline クラス（コア実行ロジック）

### Task 5: セクション単位執筆ロジック

**Files:**
- Modify: `src/research_team/orchestrator/book_pipeline.py`
- Modify: `tests/unit/test_book_pipeline.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_book_pipeline.py に追加
import asyncio
from unittest.mock import AsyncMock, MagicMock
from research_team.orchestrator.book_pipeline import (
    BookChapterPipeline,
    BookSection,
    BookOutline,
)

def _make_outline() -> BookOutline:
    return BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "第1章",
            "sections": [
                {"section_index": 1, "section_title": "1-1", "key_points": ["A"], "specialist_hint": "経済"},
                {"section_index": 2, "section_title": "1-2", "key_points": ["B"], "specialist_hint": "技術"},
            ],
        }
    ])

def test_build_section_prompt_contains_key_points():
    pipeline = BookChapterPipeline(
        stream_fn=AsyncMock(return_value="text"),
        specialists=[{"name": "経済アナリスト", "expertise": "経済・金融"}],
    )
    section = BookSection(
        chapter_index=1, section_index=1,
        chapter_title="第1章", section_title="1-1",
        key_points=["論点X", "論点Y"],
        specialist_hint="経済",
    )
    prompt = pipeline._build_section_prompt(
        topic="テスト",
        section=section,
        raw_data="調査データ...",
        previous_sections_summary="前節の要約",
    )
    assert "論点X" in prompt
    assert "論点Y" in prompt
    assert "前節の要約" in prompt

def test_run_returns_combined_text():
    call_count = 0

    async def mock_stream(agent, prompt, name, **kwargs):
        nonlocal call_count
        call_count += 1
        return f"section_text_{call_count}"

    pipeline = BookChapterPipeline(
        stream_fn=mock_stream,
        specialists=[
            {"name": "経済アナリスト", "expertise": "経済・金融"},
            {"name": "技術者", "expertise": "技術"},
        ],
    )
    outline = _make_outline()
    result = asyncio.get_event_loop().run_until_complete(
        pipeline.run(
            topic="テスト",
            outline=outline,
            raw_data="調査生データ",
            agents={"経済アナリスト": MagicMock(), "技術者": MagicMock()},
        )
    )
    assert "section_text_1" in result
    assert "section_text_2" in result
    assert call_count == 2
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q -k "section_prompt or returns_combined"
```

- [ ] **Step 3: 実装**

`book_pipeline.py` に追加：

```python
from typing import Any, Callable, Awaitable


class BookChapterPipeline:
    """book_chapter スタイル専用のセクション分解→逐次執筆パイプライン。"""

    def __init__(
        self,
        stream_fn: Callable[..., Awaitable[str]],
        specialists: list[dict],
    ) -> None:
        self._stream_fn = stream_fn
        self._specialists = specialists

    def _pick_agent(self, section: BookSection, agents: dict[str, Any]) -> tuple[str, Any]:
        """specialist_hint に最も近い専門家を選ぶ。マッチしない場合は先頭を返す。"""
        hint = section.specialist_hint.lower()
        for name, agent in agents.items():
            expertise = getattr(agent, "_expertise", "").lower()
            if hint and hint in expertise:
                return name, agent
        # fallback: 先頭
        first_name = next(iter(agents))
        return first_name, agents[first_name]

    def _build_section_prompt(
        self,
        topic: str,
        section: BookSection,
        raw_data: str,
        previous_sections_summary: str,
    ) -> str:
        key_points_text = "\n".join(f"  - {p}" for p in section.key_points)
        prev_context = (
            f"【前節までの内容（重複・矛盾を避けること）】\n{previous_sections_summary}\n\n"
            if previous_sections_summary
            else ""
        )
        return (
            f"あなたは「{topic}」について書籍の一章を執筆しています。\n\n"
            f"【担当節】{section.chapter_title} ＞ {section.section_title}\n\n"
            f"【必ず触れるべき論点】\n{key_points_text}\n\n"
            f"{prev_context}"
            f"【調査生データ（参照・引用可）】\n{raw_data[:8000]}\n\n"
            f"上記をもとに、節「{section.section_title}」を1,500〜3,000字で詳細かつ叙述的に執筆してください。\n"
            f"節見出し（### レベル）から始めてください。説明文・前置きは不要です。"
        )

    async def run(
        self,
        topic: str,
        outline: BookOutline,
        raw_data: str,
        agents: dict[str, Any],
        artifact_writer: Any | None = None,
        run_id: int = 0,
        notify_fn: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        sections = outline.all_sections()
        written: list[str] = []
        previous_summary = ""

        for section in sections:
            agent_name, agent = self._pick_agent(section, agents)
            prompt = self._build_section_prompt(
                topic=topic,
                section=section,
                raw_data=raw_data,
                previous_sections_summary=previous_summary,
            )
            text = await self._stream_fn(agent, prompt, agent_name)
            if text:
                written.append(f"### {section.section_title}\n\n{text}")
                # 前節要約を更新（全文は長すぎるので冒頭300字）
                previous_summary += f"\n- {section.section_title}: {text[:300]}..."
                if artifact_writer:
                    try:
                        artifact_writer.write_book_section(
                            run_id=run_id,
                            section_id=section.section_id,
                            chapter_title=section.chapter_title,
                            section_title=section.section_title,
                            content=text,
                        )
                    except Exception as exc:
                        logger.warning("write_book_section failed: %s", exc)
                if notify_fn:
                    await notify_fn(
                        "CSM",
                        f"📝 {section.section_id} 「{section.section_title}」執筆完了",
                    )

        return "\n\n".join(written)
```

- [ ] **Step 4: テストパスを確認**

```bash
pytest tests/unit/test_book_pipeline.py -x -q
```

- [ ] **Step 5: 全ユニットテストがパスすることを確認**

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/book_pipeline.py tests/unit/test_book_pipeline.py
git commit -m "feat: implement BookChapterPipeline with per-section writing"
```

---

## Chunk 4: Coordinator への分岐組み込み

### Task 6: coordinator.py に book_chapter 分岐を追加

**重要:** `_run_research` の既存フローは一切変更しない。`book_chapter` のみ新パスに分岐する。

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`
- Modify: `tests/unit/test_coordinator.py`

- [ ] **Step 1: テストを書く**

```python
# tests/unit/test_coordinator.py に追加
# 既存のfixture/mock構造に合わせて追加すること

async def test_book_chapter_calls_pm_for_outline(coordinator, mock_stream):
    """book_chapter スタイル時、PMにセクション分解を依頼することを確認する。"""
    # PMがセクション分解JSONを返すようにモック
    outline_json = json.dumps([{
        "chapter_index": 1,
        "chapter_title": "第1章",
        "sections": [
            {"section_index": 1, "section_title": "1-1", "key_points": ["A"], "specialist_hint": "経済"}
        ]
    }])
    pm_calls = []

    async def mock_stream_fn(agent, prompt, name, **kwargs):
        if name == "PM" and "セクション" in prompt:
            pm_calls.append(prompt)
            return f"```json\n{outline_json}\n```"
        return f"mock output for {name}"

    # stream_fn を差し替えてrun_researchを呼ぶ
    # （既存テストの構造に合わせて調整すること）
    ...
    assert len(pm_calls) >= 1
```

> **Note:** 既存テストファイルのfixture構造を確認してから、同パターンで追加すること。モック差し替えが困難な場合は、`_run_book_chapter_pipeline` のユニットテストを優先する。

- [ ] **Step 2: coordinator.py に `_decompose_book_sections` メソッドを追加**

`_run_specialist_pass` の直後に追加：

```python
async def _decompose_book_sections(
    self,
    topic: str,
    raw_content: str,
) -> "BookOutline | None":
    """PMにセクション分解を依頼し、BookOutlineを返す。失敗時はNone。"""
    from research_team.orchestrator.book_pipeline import parse_outline_from_pm_output
    prompt = (
        f"テーマ「{topic}」の書籍チャプターを執筆します。\n"
        f"以下の調査データをもとに、章・節構造をJSON形式で設計してください。\n\n"
        f"【調査データ（抜粋）】\n{raw_content[:5000]}\n\n"
        f"SKILL.mdに記載のJSON形式で出力してください。"
    )
    raw = await self._stream_agent_output(self._pm_agent, prompt, "PM (セクション分解)")
    return parse_outline_from_pm_output(raw)
```

- [ ] **Step 3: `_run_research` の book_chapter 分岐を追加**

`_run_research` 内、`combined_content = await self._run_specialist_pass(...)` の直後（line 585付近）で、`if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:` の前に挿入：

```python
# book_chapter 専用: セクション分解 → 逐次執筆
if request.style == "book_chapter":
    from research_team.orchestrator.book_pipeline import BookChapterPipeline
    outline = await self._decompose_book_sections(topic, combined_content)
    if outline and outline.all_sections():
        await self._notify("CSM", f"📚 セクション構造を設計しました（{len(outline.all_sections())}節）")
        pipeline = BookChapterPipeline(
            stream_fn=self._stream_agent_output,
            specialists=specialists,
        )
        book_content = await pipeline.run(
            topic=topic,
            outline=outline,
            raw_data=combined_content,
            agents=factory.agents,
            artifact_writer=artifact_writer,
            run_id=run_id,
            notify_fn=self._notify,
        )
        if book_content:
            combined_content = book_content
    else:
        logger.warning("book_chapter: outline decomposition failed, falling back to standard flow")
        await self._notify("CSM", "⚠️ セクション分解に失敗しました。標準フローで続行します。")
```

- [ ] **Step 4: `_evaluate_content` の book_chapter 用閾値を追加**

```python
def _evaluate_content(self, content: str, depth: str, style: str = "") -> QualityFeedback:
    issues: list[str] = []
    if style == "book_chapter":
        min_length = {"quick": 3000, "standard": 8000, "deep": 15000}.get(depth, 8000)
    else:
        min_length = {"quick": 300, "standard": 800, "deep": 2000}.get(depth, 800)
    if len(content) < min_length:
        issues.append(f"内容が不十分です（{len(content)}文字 / 目標{min_length}文字）")
    if issues:
        return QualityFeedback(
            passed=False,
            score=max(0.1, 1.0 - len(issues) * 0.2),
            improvements=issues,
        )
    return QualityFeedback(passed=True, score=1.0)
```

`evaluate()` 内の呼び出しも更新：
```python
deterministic = self._evaluate_content(content, request.depth, style=request.style)
```

- [ ] **Step 5: 全ユニットテストがパスすることを確認**

```bash
pytest tests/unit/ -x -q
```

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat: add book_chapter section pipeline branch in coordinator"
```

---

## Chunk 5: 統合・最終確認

### Task 7: 手動スモークテスト準備と最終確認

- [ ] **Step 1: 全テストパスを確認**

```bash
pytest tests/unit/ -x -q
```
期待: `全件 passed`

- [ ] **Step 2: lintチェック（存在すれば）**

```bash
ruff check src/research_team/orchestrator/book_pipeline.py src/research_team/orchestrator/coordinator.py src/research_team/output/artifact_writer.py
```

- [ ] **Step 3: 最終コミット（必要な場合）**

```bash
git add -A
git commit -m "feat: book_chapter section pipeline - complete implementation"
```

- [ ] **Step 4: 手動確認事項（自動化不可）**

```
⚠️ 手動確認が必要: book_chapter スタイルの実行で以下を確認すること
1. テーマ選択後 book_chapter スタイルを選択
2. WBS承認後に「セクション構造を設計しました（N節）」の通知が出ること
3. 各節の執筆完了通知（📝 ch01_sec01 「節タイトル」執筆完了）が出ること
4. 最終レポートに複数節が含まれ、research_report より大幅に長いこと
5. Artifactディレクトリに book_ch01_sec01_run*.md が保存されていること
6. PMのセクション分解JSONが見当たらない場合、標準フローにフォールバックすること
```

---

## フォールバック設計について

PMのセクション分解が失敗した場合（JSONパース失敗・空応答等）、**既存の標準フロー（CSM 1発整形）に自動フォールバック**する。これにより：

- 既存の `research_report` 等のスタイルは完全に無影響
- `book_chapter` でもワーストケースは現状と同等

---

## 実装後の期待効果

| 指標 | 変更前 | 変更後（期待値） |
|---|---|---|
| book_chapter 出力文字数 | 〜3,000字 | 15,000〜30,000字 |
| セクション単位のArtifact | なし | あり（各節ごとに保存） |
| 情報の積み上げ | なし（1回整形） | あり（前節を文脈として継承） |
| フォールバック | なし | あり（分解失敗時は標準フロー） |

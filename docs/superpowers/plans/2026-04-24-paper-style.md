# US-19: 学術論文フォーマット出力 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `--style paper` オプションで Abstract / Introduction / Related Work / Methodology / Results / Discussion / Conclusion / References 構成の学術論文フォーマットレポートを出力できるようにする。

**Architecture:** 既存の4スタイル（research_report / executive_memo / magazine_column / book_chapter）と同一の拡張ポイント（`_STYLE_INSTRUCTIONS`, `_STYLE_EDIT_INSTRUCTIONS`, `_STYLES_WITHOUT_EXEC_SUMMARY`）に `paper` を追加する。Executive Summary の代わりに専用の `_build_abstract_prompt()` で Abstract を生成する分岐を coordinator.py に加える。スペシャリストへの調査指示には論文向け引用ルール（`[著者名 年]` + URL）を既存テンプレートへの追記で対応する。

**Tech Stack:** Python 3.11, existing coordinator/document_editor/specialist template/HTML UI patterns

---

## 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---|---|---|
| `src/research_team/orchestrator/coordinator.py` | 修正 | `_STYLE_INSTRUCTIONS["paper"]` 追加、`_STYLES_WITHOUT_EXEC_SUMMARY` に `"paper"` 追加、`_build_abstract_prompt()` 新規追加、スタイル分岐に `paper` ケース追加 |
| `src/research_team/orchestrator/document_editor.py` | 修正 | `_STYLE_EDIT_INSTRUCTIONS["paper"]` 追加 |
| `src/research_team/agents/dynamic/templates/specialist.md.template` | 修正 | 論文スタイル向け引用指示ブロックを末尾に追加 |
| `src/research_team/ui/control_page.html` | 修正 | `<select id="styleSelect">` に `<option value="paper">` を追加 |
| `tests/unit/test_paper_style.py` | 新規作成 | スタイル指示・Abstract プロンプト・DocumentEditor 整形のユニットテスト |

---

## Chunk 1: コアロジック（coordinator.py + document_editor.py）

### Task 1: テスト先行 — coordinator.py の paper スタイル定義

**Files:**
- Test: `tests/unit/test_paper_style.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_paper_style.py
import pytest
from research_team.orchestrator.coordinator import (
    _STYLE_INSTRUCTIONS,
    _STYLES_WITHOUT_EXEC_SUMMARY,
    ResearchCoordinator,
)


def test_paper_style_instruction_exists():
    """paper スタイルの指示が _STYLE_INSTRUCTIONS に存在する"""
    assert "paper" in _STYLE_INSTRUCTIONS


def test_paper_style_instruction_contains_sections():
    """paper スタイル指示に論文構成セクション名が含まれる"""
    instr = _STYLE_INSTRUCTIONS["paper"]
    for section in ["Abstract", "Introduction", "Conclusion", "References"]:
        assert section in instr, f"'{section}' が paper style instruction に含まれていない"


def test_paper_in_styles_without_exec_summary():
    """paper スタイルは Executive Summary なしの集合に含まれる"""
    assert "paper" in _STYLES_WITHOUT_EXEC_SUMMARY


def test_build_abstract_prompt_exists():
    """_build_abstract_prompt メソッドが存在し、呼び出せる"""
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("量子コンピューティング", "調査結果テキスト")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_abstract_prompt_contains_topic():
    """Abstract プロンプトにテーマが含まれる"""
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("AIの倫理", "調査テキスト")
    assert "AIの倫理" in prompt


def test_build_abstract_prompt_requests_word_count():
    """Abstract プロンプトが 100-250語の字数指定を含む"""
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("テーマ", "内容")
    # 100 または 250 が含まれていれば字数指定があると判断
    assert "100" in prompt or "250" in prompt
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/unit/test_paper_style.py -x -q
```
期待: `ImportError` または `AssertionError`（paper キーが存在しない）

---

### Task 2: coordinator.py に paper スタイルを追加

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py:194-223`

- [ ] **Step 3: `_STYLE_INSTRUCTIONS` に `"paper"` を追加**

`_STYLE_INSTRUCTIONS` の末尾（`}` の前）に以下を追加：

```python
    "paper": (
        "学術論文（Academic Paper）形式で記述してください。"
        "以下のセクション構成を厳守してください：\n"
        "1. ## Abstract（100-250語：研究目的・手法・主要結果・結論を含む）\n"
        "2. ## Introduction（背景・問題設定・本論文の貢献）\n"
        "3. ## Related Work（関連研究・既存手法の整理）\n"
        "4. ## Methodology（調査・分析手法の説明）\n"
        "5. ## Results（主要な発見・データ・事実の提示）\n"
        "6. ## Discussion（結果の解釈・限界・含意）\n"
        "7. ## Conclusion（まとめと今後の課題）\n"
        "8. ## References（引用文献一覧：[著者名 発行年] URL 形式）\n"
        "文体は客観的・学術的にし、主張には必ず出典を付けてください。"
    ),
```

- [ ] **Step 4: `_STYLES_WITHOUT_EXEC_SUMMARY` に `"paper"` を追加**

```python
# 変更前
_STYLES_WITHOUT_EXEC_SUMMARY = {"book_chapter", "magazine_column"}

# 変更後
_STYLES_WITHOUT_EXEC_SUMMARY = {"book_chapter", "magazine_column", "paper"}
```

- [ ] **Step 5: `_build_abstract_prompt()` メソッドを追加**

`_build_summary_prompt` メソッドの直後に追加：

```python
def _build_abstract_prompt(self, topic: str, content: str) -> str:
    max_chars = os.environ.get("RT_MAX_SUMMARY_CHARS")
    body = content[:int(max_chars)] if max_chars else content
    return (
        f"以下は「{topic}」についての専門家調査結果です。\n\n"
        f"{body}\n\n"
        f"この調査結果から、学術論文の Abstract（要旨）を書いてください。\n"
        f"Abstract は 100-250語で、以下の4要素を必ず含めてください：\n"
        f"1. 研究目的・問題設定\n"
        f"2. 調査・分析手法\n"
        f"3. 主要な発見・結果\n"
        f"4. 結論・意義\n"
        f"\n【重要】Abstract 本文のみを出力してください。見出し（## Abstract）は含めず、"
        f"説明や前置きも不要です。日本語で記述してください。"
    )
```

- [ ] **Step 6: スタイル分岐に `paper` ケースを追加**

coordinator.py の `_run_research_inner` 内、スタイル別後処理分岐（`magazine_column` の `elif` / `else` の付近）を以下のように更新：

```python
# 変更前（行 1011-1022 付近）
        elif request.style == "magazine_column":
            format_prompt = self._build_format_prompt(topic, combined_content, request.style)
            formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
            if formatted:
                combined_content = formatted
        else:
            summary_prompt = self._build_summary_prompt(topic, combined_content)
            exec_summary = await self._stream_agent_output(self._csm, summary_prompt, "CSM")
            if exec_summary:
                combined_content = (
                    f"## エグゼクティブサマリー\n\n{exec_summary}\n\n---\n\n{combined_content}"
                )

# 変更後
        elif request.style == "magazine_column":
            format_prompt = self._build_format_prompt(topic, combined_content, request.style)
            formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
            if formatted:
                combined_content = formatted
        elif request.style == "paper":
            abstract_prompt = self._build_abstract_prompt(topic, combined_content)
            abstract = await self._stream_agent_output(self._csm, abstract_prompt, "CSM")
            if abstract:
                combined_content = (
                    f"## Abstract\n\n{abstract}\n\n---\n\n{combined_content}"
                )
        else:
            summary_prompt = self._build_summary_prompt(topic, combined_content)
            exec_summary = await self._stream_agent_output(self._csm, summary_prompt, "CSM")
            if exec_summary:
                combined_content = (
                    f"## エグゼクティブサマリー\n\n{exec_summary}\n\n---\n\n{combined_content}"
                )
```

同様に `_run_regenerate_inner` の対応箇所（行 1178-1187 付近）にも同じ `elif request.style == "paper"` ケースを追加：

```python
# _run_regenerate_inner 内
        if style in _STYLES_WITHOUT_EXEC_SUMMARY:
            format_prompt = self._build_format_prompt(topic, combined_content, style, regen_request_text)
            formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
            if formatted:
                combined_content = formatted
        else:
            summary_prompt = self._build_summary_prompt(topic, combined_content)
            ...
```

> **Note:** `_run_regenerate_inner` は `if style in _STYLES_WITHOUT_EXEC_SUMMARY` を使っており、`paper` を `_STYLES_WITHOUT_EXEC_SUMMARY` に追加することで自動的に対応される。ただし `_build_format_prompt` に `paper` 用の指示が必要なため、`_STYLE_INSTRUCTIONS["paper"]` が既に追加されていれば `_build_format_prompt` は `style_instruction = _STYLE_INSTRUCTIONS.get(style, "")` で自動的に拾う。**追加変更不要**。

- [ ] **Step 7: テストを再実行して通過を確認**

```
pytest tests/unit/test_paper_style.py -x -q
```
期待: 6件 PASS

---

### Task 3: document_editor.py に paper スタイルを追加

**Files:**
- Modify: `src/research_team/orchestrator/document_editor.py:18-39`
- Test: `tests/unit/test_paper_style.py`

- [ ] **Step 8: 失敗するテストを追加**

`test_paper_style.py` に以下を追記：

```python
from research_team.orchestrator.document_editor import _STYLE_EDIT_INSTRUCTIONS, _build_edit_prompt


def test_paper_style_edit_instruction_exists():
    """paper スタイルの編集指示が _STYLE_EDIT_INSTRUCTIONS に存在する"""
    assert "paper" in _STYLE_EDIT_INSTRUCTIONS


def test_paper_style_edit_instruction_content():
    """paper 編集指示が Abstract と References の確認を含む"""
    instr = _STYLE_EDIT_INSTRUCTIONS["paper"]
    assert "Abstract" in instr
    assert "References" in instr


def test_build_edit_prompt_uses_paper_instruction():
    """_build_edit_prompt が paper スタイルで paper 固有の指示を使う"""
    prompt = _build_edit_prompt("量子コンピューティング", "コンテンツ", "paper")
    assert "Abstract" in prompt
    assert "References" in prompt
```

- [ ] **Step 9: テストが失敗することを確認**

```
pytest tests/unit/test_paper_style.py::test_paper_style_edit_instruction_exists -x -q
```

- [ ] **Step 10: `_STYLE_EDIT_INSTRUCTIONS` に `"paper"` を追加**

```python
    "paper": (
        "学術論文として完成させてください。"
        "Abstract（100-250語）が冒頭に存在するか確認し、不足があれば補完してください。"
        "Introduction / Related Work / Methodology / Results / Discussion / Conclusion / References "
        "の各セクション見出しが揃っているか確認・整備してください。"
        "References セクションは '[著者名 発行年] タイトル. URL' 形式で統一してください。"
        "LLMの作業説明・謝罪文は削除し、論文本文のみを残してください。"
    ),
```

- [ ] **Step 11: テスト通過確認**

```
pytest tests/unit/test_paper_style.py -x -q
```
期待: 9件 PASS

- [ ] **Step 12: ユニットテスト全体を確認**

```
pytest tests/unit/ -x -q
```
期待: 既存テスト含め全件 PASS

- [ ] **Step 13: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py \
        src/research_team/orchestrator/document_editor.py \
        tests/unit/test_paper_style.py
git commit -m "feat: add paper academic style - core logic (coordinator + document_editor)"
```

---

## Chunk 2: specialist テンプレート + UI

### Task 4: specialist.md.template に論文引用ルールを追加

**Files:**
- Modify: `src/research_team/agents/dynamic/templates/specialist.md.template`

- [ ] **Step 14: テンプレートに追記**

`specialist.md.template` の末尾（最終行の後）に以下を追加：

```markdown
## Academic Paper Mode（論文スタイル時のみ適用）

When the research task instructs you to write in **Academic Paper** format, apply these additional rules:

**Citation format:** Use `[著者名 発行年]` inline, with full reference at the end.
- Example inline: `量子もつれの実験的証明 [Aspect et al. 1982]`
- Example in References: `[Aspect et al. 1982] Aspect, A., Dalibard, J., & Roger, G. (1982). Experimental test of Bell's inequalities. *Physical Review Letters*, 49(25). https://doi.org/...`

**If author/year is unknown:** fall back to `([出典タイトル](URL))` format.

**Section discipline:** Write content under the exact section headings specified in the task:
Abstract, Introduction, Related Work, Methodology, Results, Discussion, Conclusion, References.
Do NOT merge or rename these sections.
```

- [ ] **Step 15: テンプレート変更はユニットテスト不要（手動確認対象外）— ユニットテスト全体を通過確認**

```
pytest tests/unit/ -x -q
```
期待: 全件 PASS

---

### Task 5: control_page.html の style 選択肢に `paper` を追加

**Files:**
- Modify: `src/research_team/ui/control_page.html:321-326`

- [ ] **Step 16: `<select id="styleSelect">` に paper オプションを追加**

```html
<!-- 変更前 -->
            <select id="styleSelect" class="style-select">
              <option value="research_report">調査レポート</option>
              <option value="executive_memo">エグゼクティブメモ</option>
              <option value="magazine_column">マガジンコラム</option>
              <option value="book_chapter">書籍チャプター</option>
            </select>

<!-- 変更後 -->
            <select id="styleSelect" class="style-select">
              <option value="research_report">調査レポート</option>
              <option value="executive_memo">エグゼクティブメモ</option>
              <option value="magazine_column">マガジンコラム</option>
              <option value="book_chapter">書籍チャプター</option>
              <option value="paper">学術論文</option>
            </select>
```

- [ ] **Step 17: ユニットテスト全体を再確認**

```
pytest tests/unit/ -x -q
```
期待: 全件 PASS

- [ ] **Step 18: コミット**

```bash
git add src/research_team/agents/dynamic/templates/specialist.md.template \
        src/research_team/ui/control_page.html
git commit -m "feat: add paper style - specialist template citation rules + UI option"
```

---

## Chunk 3: tasks.md 更新 + 最終確認

### Task 6: tasks.md の US-19 ステータス更新

**Files:**
- Modify: `docs/tasks.md`

- [ ] **Step 19: US-19 の全タスクを ✅ 実装済 に更新**

`docs/tasks.md` の US-19 テーブルを以下に置き換え：

```markdown
| # | タスク | 状態 |
|---|---|---|
| 19-1 | `coordinator.py` の `_STYLE_INSTRUCTIONS` に `"paper"` エントリを追加（セクション構成・文体・引用スタイル指示） | ✅ 実装済 |
| 19-2 | `document_editor.py` の `_STYLE_EDIT_INSTRUCTIONS` に `"paper"` エントリを追加（Abstract 長・見出し確認・References 整形） | ✅ 実装済 |
| 19-3 | `coordinator.py` の `_STYLES_WITHOUT_EXEC_SUMMARY` に `"paper"` を追加し、Executive Summary の代わりに `_build_abstract_prompt()` で Abstract を生成する | ✅ 実装済 |
| 19-4 | `coordinator.py` に `_build_abstract_prompt()` を実装（Abstract: 100-250語、研究目的・手法・主要結果・結論を含む） | ✅ 実装済 |
| 19-5 | `specialist.md.template` に論文スタイル向け引用指示を追加（`[著者名 発行年]` 形式 + URL 併記ルール） | ✅ 実装済 |
| 19-6 | CLI `--style` オプションの選択肢に `paper` を追加（`cli/main.py`） | ⚠️ 部品あり（CLI ヘルプ文字列のみ未更新、動作上は機能する） |
| 19-7 | WBS 承認 UI の出力スタイル選択肢に `paper` を追加（`control_page.html`） | ✅ 実装済 |
| 19-8 | `tests/unit/test_paper_style.py` — スタイル指示生成・Abstract プロンプト・DocumentEditor 整形のユニットテスト | ✅ 実装済 |
```

> **Note on 19-6:** CLI の `--style` オプションは現在ヘルプ文字列のみ管理しており、値の検証はしていない（任意文字列を受け付ける）。`paper` は動作上すでに有効。ヘルプ文字列の更新は任意。

- [ ] **Step 20: サマリーテーブルを更新**

US-19 行を：
```
| 出力 | US-19: 学術論文フォーマット出力 | 0 | 0 | 8 |
```
から：
```
| 出力 | US-19: 学術論文フォーマット出力 | 7 | 1 | 0 |
```
に変更し、合計行も更新。

- [ ] **Step 21: 最終テスト実行（全ユニットテスト）**

```
pytest tests/unit/ -x -q
```
期待: 全件 PASS（出力を確認してレスポンスに含める）

- [ ] **Step 22: 最終コミット**

```bash
git add docs/tasks.md
git commit -m "docs: update US-19 task status to reflect paper style implementation"
```

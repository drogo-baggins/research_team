# Book Assembly Template-Driven Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken `_assemble_book_from_outline` (which calls non-existent `_strip_section_preamble` / `_strip_section_suffix` methods) with a `BookAssembleTool` class that owns all heading generation (`#` / `##` / `###`), while LLMs write only body text.

**Architecture:** A new standalone `book_assembler.py` module encapsulates all assembly logic. `coordinator.py` delegates to it. `book_pipeline.py` prompt is updated so LLMs no longer write `###` headings. Sources are aggregated into a single deduplicated section at the document end.

**Tech Stack:** Python 3.11, pytest, existing artifact file conventions (`book_ch01_sec01_run1_YYYYMMDD.md`)

---

## Chunk 1: BookAssembleTool

### Task 1: Write failing tests for BookAssembleTool

**Files:**
- Create: `tests/unit/test_book_assembler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_book_assembler.py
import textwrap
from pathlib import Path

import pytest

from research_team.orchestrator.book_assembler import BookAssembleTool
from research_team.orchestrator.book_outline import BookOutline


# ── helpers ──────────────────────────────────────────────────────────────────

def make_outline(n_chapters: int = 2, sections_per_chapter: int = 2) -> BookOutline:
    chapters = []
    for ci in range(1, n_chapters + 1):
        sections = []
        for si in range(1, sections_per_chapter + 1):
            sections.append({
                "section_index": si,
                "section_title": f"節タイトル{ci}-{si}",
                "key_points": [],
                "specialist_hint": "",
            })
        chapters.append({
            "chapter_index": ci,
            "chapter_title": f"第{ci}章タイトル",
            "sections": sections,
        })
    return BookOutline(topic="テストトピック", chapters=chapters)


ARTIFACT_TEMPLATE = """\
# 書籍セクション — {section_id} / Run 1 (20260426)

**章:** 第{ci}章タイトル
**節:** 節タイトル{ci}-{si}

---

### 節タイトル{ci}-{si}

ここが本文テキストです。とても重要な内容が書いてあります。

## Sources
- https://example.com/source{ci}{si}
"""

DISCUSSION_CONTENT = """\
# 対談トランスクリプト — Run 1 (20260426)

対談の内容がここに入ります。
"""


def write_artifacts(tmp_path: Path, outline: BookOutline) -> dict[str, dict]:
    section_paths: dict[str, dict] = {}
    for ch in outline.chapters:
        ci = ch["chapter_index"]
        for sec in ch["sections"]:
            si = sec["section_index"]
            section_id = f"ch{ci:02d}_sec{si:02d}"
            content = ARTIFACT_TEMPLATE.format(section_id=section_id, ci=ci, si=si)
            p = tmp_path / f"book_{section_id}_run1_20260426.md"
            p.write_text(content, encoding="utf-8")
            section_paths[section_id] = {"artifact_path": str(p)}
    return section_paths


# ── tests ─────────────────────────────────────────────────────────────────────

class TestStripArtifactHeader:
    def test_strips_metadata_block(self):
        tool = BookAssembleTool()
        raw = "# 書籍セクション — ch01_sec01\n\n**章:** ...\n\n---\n\n本文テキスト"
        assert tool._strip_artifact_header(raw) == "本文テキスト"

    def test_no_separator_returns_whole(self):
        tool = BookAssembleTool()
        raw = "本文だけ"
        assert tool._strip_artifact_header(raw) == "本文だけ"


class TestStripSectionHeading:
    def test_strips_h3_first_line(self):
        tool = BookAssembleTool()
        content = "### 節タイトル1-1\n\n本文テキスト"
        assert tool._strip_section_heading(content) == "本文テキスト"

    def test_no_heading_unchanged(self):
        tool = BookAssembleTool()
        content = "本文テキスト"
        assert tool._strip_section_heading(content) == "本文テキスト"

    def test_strips_h1_or_h2_first_line(self):
        tool = BookAssembleTool()
        for prefix in ("# ", "## "):
            content = f"{prefix}見出し\n\n本文"
            assert tool._strip_section_heading(content) == "本文"


class TestStripSourcesSuffix:
    def test_strips_sources_section(self):
        tool = BookAssembleTool()
        content = "本文テキスト\n\n## Sources\n- https://example.com\n"
        result = tool._strip_sources_suffix(content)
        assert "## Sources" not in result
        assert "本文テキスト" in result

    def test_no_sources_unchanged(self):
        tool = BookAssembleTool()
        content = "本文テキスト"
        assert tool._strip_sources_suffix(content) == "本文テキスト"


class TestExtractSources:
    def test_extracts_urls(self):
        tool = BookAssembleTool()
        content = "本文\n\n## Sources\n- https://example.com/a\n- https://example.com/b\n"
        sources = tool._extract_sources(content)
        assert "https://example.com/a" in sources
        assert "https://example.com/b" in sources

    def test_empty_when_no_sources(self):
        tool = BookAssembleTool()
        assert tool._extract_sources("本文だけ") == []


class TestAssemble:
    def test_h1_is_topic(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="テストトピック")
        lines = result.splitlines()
        assert lines[0] == "# テストトピック"

    def test_chapter_headings_are_h2(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(2, 1)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        assert "## 第1章" in result
        assert "## 第2章" in result

    def test_section_headings_are_h3(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 2)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        assert "### 節タイトル1-1" in result
        assert "### 節タイトル1-2" in result

    def test_llm_h3_heading_not_duplicated(self, tmp_path):
        """LLM が ### を書いていても二重見出しにならない"""
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        # 節タイトル1-1 は ### で一度だけ現れる
        count = result.count("### 節タイトル1-1")
        assert count == 1

    def test_body_text_present(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        assert "ここが本文テキストです" in result

    def test_sources_aggregated_at_end(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 2)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        # Sources section appears exactly once, at the end
        assert result.count("## Sources") == 1
        sources_idx = result.index("## Sources")
        # No body text after Sources
        after_sources = result[sources_idx:]
        assert "ここが本文テキストです" not in after_sources

    def test_discussion_appended(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        disc_path = tmp_path / "discussion.md"
        disc_path.write_text(DISCUSSION_CONTENT, encoding="utf-8")
        result = tool.assemble(outline, section_paths, discussion_path=disc_path, topic="T")
        assert "対談トランスクリプト" in result
        assert "対談の内容がここに入ります" in result

    def test_discussion_after_body(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        disc_path = tmp_path / "discussion.md"
        disc_path.write_text(DISCUSSION_CONTENT, encoding="utf-8")
        result = tool.assemble(outline, section_paths, discussion_path=disc_path, topic="T")
        body_idx = result.index("ここが本文テキストです")
        disc_idx = result.index("対談の内容がここに入ります")
        assert disc_idx > body_idx

    def test_missing_section_skipped_gracefully(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        # Pass empty section_paths → no artifact file
        result = tool.assemble(outline, {}, topic="T")
        assert "# T" in result  # still generates structure

    def test_toc_present(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(2, 2)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        assert "## 目次" in result
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
pytest tests/unit/test_book_assembler.py -x -q
```
Expected: `ImportError` or `ModuleNotFoundError` (class doesn't exist yet)

---

### Task 2: Implement BookAssembleTool

**Files:**
- Create: `src/research_team/orchestrator/book_assembler.py`

- [ ] **Step 3: Write the implementation**

```python
# src/research_team/orchestrator/book_assembler.py
"""
BookAssembleTool — Python-controlled book assembly.

Responsibility split:
  Python (this module) : #  title
                         ## chapter headings
                         ### section headings
                         ## 目次  table-of-contents
                         ## Sources  (aggregated, deduplicated)
                         discussion block (fixed position after body)
  LLM                  : section body text (#### and below only)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^#{1,3}\s+.+", re.MULTILINE)
_SOURCES_HEADER_RE = re.compile(r"^##\s+Sources\s*$", re.MULTILINE | re.IGNORECASE)


class BookAssembleTool:
    # ── low-level text helpers ────────────────────────────────────────────────

    def _strip_artifact_header(self, raw: str) -> str:
        """Strip artifact metadata block (everything up to and including '---\\n\\n')."""
        sep_idx = raw.find("---\n\n")
        if sep_idx == -1:
            return raw.strip()
        return raw[sep_idx + 5:].strip()

    def _strip_section_heading(self, content: str) -> str:
        """Remove a leading #/##/### heading line that the LLM may have written."""
        stripped = content.lstrip()
        lines = stripped.splitlines()
        if not lines:
            return content
        if re.match(r"^#{1,3}\s+", lines[0]):
            rest = "\n".join(lines[1:]).lstrip()
            return rest
        return stripped

    def _strip_sources_suffix(self, content: str) -> str:
        """Remove ## Sources section and everything after it."""
        m = _SOURCES_HEADER_RE.search(content)
        if m:
            return content[: m.start()].rstrip()
        return content

    def _extract_sources(self, content: str) -> list[str]:
        """Return URL strings from the ## Sources section."""
        m = _SOURCES_HEADER_RE.search(content)
        if not m:
            return []
        sources_block = content[m.end():]
        urls: list[str] = []
        for line in sources_block.splitlines():
            line = line.strip().lstrip("-").strip()
            if line.startswith("http"):
                urls.append(line)
        return urls

    def _read_section(self, artifact_path: str) -> tuple[str, list[str]]:
        """
        Read section artifact. Returns (body_text, [source_urls]).
        body_text has the artifact header, leading ### heading, and Sources suffix stripped.
        """
        try:
            raw = Path(artifact_path).read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("BookAssembleTool: failed to read %s: %s", artifact_path, exc)
            return "", []

        content = self._strip_artifact_header(raw)
        sources = self._extract_sources(content)
        content = self._strip_sources_suffix(content)
        content = self._strip_section_heading(content)
        return content.strip(), sources

    # ── chapter prefix normalisation ─────────────────────────────────────────

    @staticmethod
    def _strip_chapter_prefix(title: str) -> str:
        """Remove leading '第N章' / '第N部' prefix if present."""
        return re.sub(r"^第\d+[章部]\s*[　\s]?", "", title).strip()

    # ── main assembly ─────────────────────────────────────────────────────────

    def assemble(
        self,
        outline: "BookOutline",
        section_paths: dict[str, dict],
        discussion_path: Path | None = None,
        topic: str = "",
    ) -> str:
        """
        Assemble the full book document.

        Returns a Markdown string with:
          # <topic>
          ## 目次
          ---
          ## 第N章 <title>
          ### <section title>
          <body>
          ...
          ## Sources   (aggregated)
          ---
          <discussion> (if provided)
        """
        all_sources: list[str] = []

        # ── table of contents ─────────────────────────────────────────────────
        toc_lines = ["## 目次", ""]
        for ch in outline.chapters:
            ci = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            toc_lines.append(f"**第{ci}章　{ch_title}**")
            for sec in ch.get("sections", []):
                si = sec["section_index"]
                sec_title = sec["section_title"]
                toc_lines.append(f"　　第{ci}.{si}節　{sec_title}")
            toc_lines.append("")

        # ── chapter / section body ────────────────────────────────────────────
        chapter_parts: list[str] = []
        for ch in outline.chapters:
            ci = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            ch_lines: list[str] = [f"## 第{ci}章　{ch_title}", ""]
            for sec in ch.get("sections", []):
                si = sec["section_index"]
                sec_title = sec["section_title"]
                section_id = f"ch{ci:02d}_sec{si:02d}"
                entry = section_paths.get(section_id, {})
                artifact_path = entry.get("artifact_path", "")

                ch_lines.append(f"### {sec_title}")
                ch_lines.append("")

                if artifact_path:
                    body, sources = self._read_section(artifact_path)
                    all_sources.extend(sources)
                    if body:
                        ch_lines.append(body)
                        ch_lines.append("")

            chapter_parts.append("\n".join(ch_lines))

        # ── build document ────────────────────────────────────────────────────
        title_line = f"# {topic.split(chr(10))[0].strip()}\n\n" if topic else ""
        toc = "\n".join(toc_lines)
        body = "\n\n".join(chapter_parts)

        # Deduplicate sources preserving order
        seen: set[str] = set()
        unique_sources: list[str] = []
        for s in all_sources:
            if s not in seen:
                seen.add(s)
                unique_sources.append(s)

        sources_section = ""
        if unique_sources:
            sources_lines = ["## Sources", ""] + [f"- {s}" for s in unique_sources]
            sources_section = "\n\n" + "\n".join(sources_lines)

        result = f"{title_line}{toc}\n\n---\n\n{body}{sources_section}"

        # ── discussion ────────────────────────────────────────────────────────
        if discussion_path is not None:
            try:
                disc = Path(discussion_path).read_text(encoding="utf-8").strip()
                result += f"\n\n---\n\n{disc}"
            except Exception as exc:
                logger.warning("BookAssembleTool: failed to read discussion %s: %s", discussion_path, exc)

        return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_book_assembler.py -x -q
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_book_assembler.py src/research_team/orchestrator/book_assembler.py
git commit -m "feat: add BookAssembleTool with Python-controlled headings"
```

---

## Chunk 2: Wire BookAssembleTool into coordinator + fix prompt

### Task 3: Write failing tests for coordinator integration

**Files:**
- Modify: `tests/unit/test_book_chapter_fix.py` (add new test cases)

Look at the file first:
```bash
# check existing test structure
pytest tests/unit/test_book_chapter_fix.py -x -q
```

- [ ] **Step 1: Add integration tests**

Add these tests to `tests/unit/test_book_chapter_fix.py` (after reading the file to understand existing style):

```python
# Add to tests/unit/test_book_chapter_fix.py

# Import at top if not already present:
# from research_team.orchestrator.book_assembler import BookAssembleTool

class TestAssembleBookFromOutlineViaCoordinator:
    """Verify coordinator._assemble_book_from_outline delegates to BookAssembleTool."""

    def _make_outline(self):
        # reuse or inline make_outline helper (see test_book_assembler.py)
        from research_team.orchestrator.book_outline import BookOutline
        chapters = [{
            "chapter_index": 1,
            "chapter_title": "第1章タイトル",
            "sections": [{
                "section_index": 1,
                "section_title": "節タイトル1-1",
                "key_points": [],
                "specialist_hint": "",
            }],
        }]
        return BookOutline(topic="T", chapters=chapters)

    def test_no_attribute_error(self, tmp_path):
        """coordinator._assemble_book_from_outline must not raise AttributeError."""
        from unittest.mock import MagicMock, patch
        from research_team.orchestrator import coordinator as coord_module

        outline = self._make_outline()
        # Write a minimal artifact
        p = tmp_path / "book_ch01_sec01_run1_20260426.md"
        p.write_text(
            "# 書籍セクション — ch01_sec01\n\n**章:** ...\n\n---\n\n### 節タイトル1-1\n\n本文テキスト\n\n## Sources\n- https://example.com\n",
            encoding="utf-8",
        )
        section_paths = {"ch01_sec01": {"artifact_path": str(p)}}

        # Build a minimal coordinator without full init
        coord = object.__new__(coord_module.ResearchCoordinator)
        result = coord._assemble_book_from_outline(
            outline=outline,
            section_paths=section_paths,
            topic="テストトピック",
        )
        assert isinstance(result, str)
        assert "# テストトピック" in result

    def test_discussion_included(self, tmp_path):
        from unittest.mock import MagicMock
        from research_team.orchestrator import coordinator as coord_module

        outline = self._make_outline()
        p = tmp_path / "book_ch01_sec01_run1_20260426.md"
        p.write_text("# h\n\n---\n\n本文\n", encoding="utf-8")
        disc_p = tmp_path / "discussion.md"
        disc_p.write_text("# 対談トランスクリプト — Run 1 (20260426)\n\n対談内容\n", encoding="utf-8")
        section_paths = {"ch01_sec01": {"artifact_path": str(p)}}

        coord = object.__new__(coord_module.ResearchCoordinator)
        result = coord._assemble_book_from_outline(
            outline=outline,
            section_paths=section_paths,
            discussion_artifact_path=str(disc_p),
            topic="T",
        )
        assert "対談内容" in result
```

- [ ] **Step 2: Run to confirm existing behavior**

```bash
pytest tests/unit/test_book_chapter_fix.py -x -q
```
Note: `test_no_attribute_error` will FAIL with `AttributeError: 'ResearchCoordinator' object has no attribute '_strip_section_preamble'` — this confirms the bug.

---

### Task 4: Refactor coordinator._assemble_book_from_outline to use BookAssembleTool

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py` (lines ~720-778)

- [ ] **Step 3: Replace `_assemble_book_from_outline` body**

Find the method (lines 720-778) and replace its body:

```python
    def _assemble_book_from_outline(
        self,
        outline: "BookOutline",
        section_paths: dict[str, dict],
        discussion_artifact_path: str | None = None,
        topic: str = "",
    ) -> str:
        from pathlib import Path as _Path
        from research_team.orchestrator.book_assembler import BookAssembleTool

        disc_path = _Path(discussion_artifact_path) if discussion_artifact_path else None
        return BookAssembleTool().assemble(
            outline=outline,
            section_paths=section_paths,
            discussion_path=disc_path,
            topic=topic,
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_book_chapter_fix.py -x -q
```
Expected: new tests PASS

- [ ] **Step 5: Run full unit suite**

```bash
pytest tests/unit/ -x -q
```
Expected: all PASS

---

### Task 5: Fix LLM prompt — remove ### instruction

**Files:**
- Modify: `src/research_team/orchestrator/book_pipeline.py` line ~138

- [ ] **Step 6: Update prompt**

Change line 138 from:
```python
f"節見出し（### レベル）から始めてください。説明文・前置きは不要です。\n"
```
to:
```python
f"見出し行は書かないでください。本文のみを出力してください。小見出しが必要な場合は #### 以下を使用してください。説明文・前置きは不要です。\n"
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/ -x -q
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/research_team/orchestrator/coordinator.py src/research_team/orchestrator/book_pipeline.py
git commit -m "fix: delegate book assembly to BookAssembleTool, fix LLM heading prompt"
```

---

## Done Criteria

- [ ] `pytest tests/unit/ -x -q` → 0 failures
- [ ] `# テストトピック` appears as the first line of assembled book
- [ ] No `### heading` duplication (LLM-written heading stripped, Python heading inserted)
- [ ] Discussion content appears after body when discussion artifact exists
- [ ] `## Sources` appears exactly once, at end of body (before discussion)
- [ ] `_assemble_book_from_outline` no longer calls non-existent `_strip_section_preamble` / `_strip_section_suffix`

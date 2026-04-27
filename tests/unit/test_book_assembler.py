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
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
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
        assert result.count("## Sources") == 1
        sources_idx = result.index("## Sources")
        after_sources = result[sources_idx:]
        assert "ここが本文テキストです" not in after_sources

    def test_discussion_appended(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        disc_path = tmp_path / "discussion.md"
        disc_path.write_text(DISCUSSION_CONTENT, encoding="utf-8")
        result = tool.assemble(outline, section_paths, discussion_path=disc_path, topic="T")
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
        result = tool.assemble(outline, {}, topic="T")
        assert "# T" in result

    def test_toc_present(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(2, 2)
        section_paths = write_artifacts(tmp_path, outline)
        result = tool.assemble(outline, section_paths, topic="T")
        assert "## 目次" in result

    def test_discussion_top_h1_stripped(self, tmp_path):
        tool = BookAssembleTool()
        outline = make_outline(1, 1)
        section_paths = write_artifacts(tmp_path, outline)
        disc_path = tmp_path / "discussion.md"
        disc_path.write_text(DISCUSSION_CONTENT, encoding="utf-8")
        result = tool.assemble(outline, section_paths, discussion_path=disc_path, topic="T")
        lines = result.splitlines()
        h1_lines = [l for l in lines if l.startswith("# ")]
        assert len(h1_lines) == 1
        assert h1_lines[0] == "# T"

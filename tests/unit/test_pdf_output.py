import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from research_team.output.pdf import (
    PDFOutput,
    _markdown_to_html,
    _pdf_path_from_md,
    _preprocess_mermaid,
)


def test_preprocess_mermaid_converts_fence_to_div():
    content = "前のテキスト\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\n後のテキスト"
    result = _preprocess_mermaid(content)
    assert '<div class="mermaid">' in result
    assert "flowchart LR" in result
    assert "```mermaid" not in result


def test_preprocess_mermaid_preserves_non_mermaid_fences():
    content = "```python\nprint('hello')\n```"
    result = _preprocess_mermaid(content)
    assert "```python" in result
    assert '<div class="mermaid">' not in result


def test_preprocess_mermaid_multiple_blocks():
    content = "```mermaid\nflowchart LR\n  A --> B\n```\n\ntext\n\n```mermaid\npie\n  title X\n  A: 60\n  B: 40\n```"
    result = _preprocess_mermaid(content)
    assert result.count('<div class="mermaid">') == 2


def test_markdown_to_html_includes_mermaid_cdn():
    html = _markdown_to_html("# タイトル\n\n本文")
    assert "mermaid" in html
    assert "cdn.jsdelivr.net" in html


def test_markdown_to_html_renders_heading():
    html = _markdown_to_html("# AIの未来\n\n本文テキスト")
    assert "<h1>" in html
    assert "AIの未来" in html


def test_markdown_to_html_converts_mermaid_block():
    content = "# タイトル\n\n```mermaid\nflowchart LR\n  A --> B\n```"
    html = _markdown_to_html(content)
    assert '<div class="mermaid">' in html
    assert "flowchart LR" in html


def test_markdown_to_html_renders_table():
    content = "| A | B |\n|---|---|\n| 1 | 2 |"
    html = _markdown_to_html(content)
    assert "<table>" in html


def test_pdf_path_from_md():
    assert _pdf_path_from_md("/workspace/report_test_20260422.md") == Path("/workspace/report_test_20260422.pdf")
    assert _pdf_path_from_md("report.md") == Path("report.pdf")


@pytest.mark.asyncio
async def test_pdf_output_save_async_calls_render(tmp_path):
    md_file = tmp_path / "report_test.md"
    md_file.write_text("# テスト\n\n本文", encoding="utf-8")

    with patch("research_team.output.pdf._render_pdf", new_callable=AsyncMock) as mock_render:
        output = PDFOutput(str(tmp_path))
        result = await output.save_async("# テスト\n\n本文", str(md_file))

    mock_render.assert_awaited_once()
    html_arg = mock_render.call_args[0][0]
    assert "テスト" in html_arg
    assert result == str(tmp_path / "report_test.pdf")


@pytest.mark.asyncio
async def test_pdf_output_save_async_passes_html_with_mermaid(tmp_path):
    md_file = tmp_path / "report.md"
    content = "# レポート\n\n```mermaid\nflowchart LR\n  A --> B\n```"

    with patch("research_team.output.pdf._render_pdf", new_callable=AsyncMock) as mock_render:
        output = PDFOutput(str(tmp_path))
        await output.save_async(content, str(md_file))

    html_arg = mock_render.call_args[0][0]
    assert '<div class="mermaid">' in html_arg

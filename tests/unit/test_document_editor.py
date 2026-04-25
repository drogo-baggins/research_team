import pytest
from unittest.mock import AsyncMock
from research_team.orchestrator.document_editor import (
    DocumentEditorAgent,
    edit_document,
    _build_edit_prompt,
    _FALLBACK_RATIO,
)


def test_document_editor_agent_name():
    agent = DocumentEditorAgent()
    assert agent.name == "DocumentEditor"


def test_document_editor_skill_path_exists():
    agent = DocumentEditorAgent()
    assert (agent.skill_path / "SKILL.md").exists()


def test_build_edit_prompt_contains_topic():
    prompt = _build_edit_prompt("AI倫理", "本文内容", "research_report")
    assert "AI倫理" in prompt


def test_build_edit_prompt_contains_content():
    prompt = _build_edit_prompt("AI倫理", "本文内容サンプル", "research_report")
    assert "本文内容サンプル" in prompt


def test_build_edit_prompt_contains_style_instruction_book():
    prompt = _build_edit_prompt("AI倫理", "本文", "book_chapter")
    assert "前書き" in prompt or "後書き" in prompt


def test_build_edit_prompt_contains_style_instruction_magazine():
    prompt = _build_edit_prompt("AI倫理", "本文", "magazine_column")
    assert "マガジンコラム" in prompt


def test_build_edit_prompt_contains_style_instruction_executive():
    prompt = _build_edit_prompt("AI倫理", "本文", "executive_memo")
    assert "エグゼクティブメモ" in prompt


def test_build_edit_prompt_unknown_style_falls_back():
    prompt = _build_edit_prompt("AI倫理", "本文", "unknown_style")
    assert "AI倫理" in prompt
    assert "本文" in prompt


@pytest.mark.asyncio
async def test_edit_document_returns_result():
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50
    edited = "編集済みの内容。" * 40

    async def mock_stream(ag, prompt, name):
        return edited

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result == edited


@pytest.mark.asyncio
async def test_edit_document_fallback_on_empty_output():
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50

    async def mock_stream(ag, prompt, name):
        return ""

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result == original


@pytest.mark.asyncio
async def test_edit_document_fallback_on_too_short_output():
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50

    async def mock_stream(ag, prompt, name):
        return "短い"

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result == original


@pytest.mark.asyncio
async def test_edit_document_fallback_on_exception():
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50

    async def mock_stream(ag, prompt, name):
        raise RuntimeError("pi-agent failed")

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result == original


@pytest.mark.asyncio
async def test_edit_document_empty_content_passthrough():
    agent = DocumentEditorAgent()

    async def mock_stream(ag, prompt, name):
        return "should not be called"

    result = await edit_document(mock_stream, agent, "テスト", "", "research_report")
    assert result == ""


@pytest.mark.asyncio
async def test_edit_document_accepts_sufficient_length_output():
    agent = DocumentEditorAgent()
    original = "あ" * 100
    edited = "い" * 31

    async def mock_stream(ag, prompt, name):
        return edited

    result = await edit_document(mock_stream, agent, "テスト", original, "book_chapter")
    assert result == edited


@pytest.mark.asyncio
async def test_edit_document_strips_leading_commentary():
    """LLMが作業説明を冒頭に出力した場合、# 見出し前の行が除去される"""
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50
    # LLM output that starts with commentary, then actual markdown
    llm_output = (
        "ファイルの内容を確認してから校正を進めます。校正が完了しました。以下の整形を行いました：\n\n"
        "## 実施した校正内容\n\n"
        "### 1. LLMのメタ発言除去\n\n"
        "---\n\n"
        "整形済みのMarkdown本文は以下の通りです：\n\n"
        + "# 本物のタイトル\n\n" + "本文内容。" * 40
    )

    async def mock_stream(ag, prompt, name):
        return llm_output

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result.startswith("# 本物のタイトル")


@pytest.mark.asyncio
async def test_edit_document_no_strip_when_starts_with_heading():
    """出力が最初から # 見出しで始まる場合はそのまま返す"""
    agent = DocumentEditorAgent()
    original = "元の内容。" * 50
    llm_output = "# 正常なタイトル\n\n" + "本文内容。" * 40

    async def mock_stream(ag, prompt, name):
        return llm_output

    result = await edit_document(mock_stream, agent, "テスト", original, "research_report")
    assert result.startswith("# 正常なタイトル")


def test_strip_leading_commentary_removes_preamble():
    from research_team.orchestrator.document_editor import _strip_leading_commentary
    text = "作業説明文です。\n\n## 実施内容\n\n---\n\n# 本文タイトル\n\n本文"
    result = _strip_leading_commentary(text)
    assert result.startswith("# 本文タイトル")


def test_strip_leading_commentary_no_change_when_clean():
    from research_team.orchestrator.document_editor import _strip_leading_commentary
    text = "# タイトル\n\n本文内容"
    result = _strip_leading_commentary(text)
    assert result == text


def test_strip_leading_commentary_no_heading_returns_original():
    from research_team.orchestrator.document_editor import _strip_leading_commentary
    text = "見出しのないテキスト\n本文"
    result = _strip_leading_commentary(text)
    assert result == text

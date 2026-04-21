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

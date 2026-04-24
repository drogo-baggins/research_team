import pytest
from research_team.orchestrator.coordinator import (
    _STYLE_INSTRUCTIONS,
    _STYLES_WITHOUT_EXEC_SUMMARY,
    ResearchCoordinator,
)


def test_paper_style_instruction_exists():
    assert "paper" in _STYLE_INSTRUCTIONS


def test_paper_style_instruction_contains_sections():
    instr = _STYLE_INSTRUCTIONS["paper"]
    for section in ["Abstract", "Introduction", "Conclusion", "References"]:
        assert section in instr, f"'{section}' が paper style instruction に含まれていない"


def test_paper_style_instruction_contains_yoshi():
    instr = _STYLE_INSTRUCTIONS["paper"]
    assert "要旨" in instr, "paper style instruction に '要旨' セクションが含まれていない"


def test_paper_style_instruction_specifies_english_abstract():
    instr = _STYLE_INSTRUCTIONS["paper"]
    assert "English" in instr or "英語" in instr, "Abstract は英語と明記されていない"


def test_paper_NOT_in_styles_without_exec_summary():
    assert "paper" not in _STYLES_WITHOUT_EXEC_SUMMARY


def test_build_abstract_prompt_exists():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("量子コンピューティング", "調査結果テキスト")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_abstract_prompt_contains_topic():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("AIの倫理", "調査テキスト")
    assert "AIの倫理" in prompt


def test_build_abstract_prompt_requests_word_count():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("テーマ", "内容")
    assert "100" in prompt or "250" in prompt


def test_build_abstract_prompt_requests_english_and_japanese():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_abstract_prompt("テーマ", "内容")
    assert "---ABSTRACT---" in prompt
    assert "---YOSHI---" in prompt


def test_parse_abstract_output_with_separators():
    raw = "---ABSTRACT---\nThis is the English abstract.\n---YOSHI---\nこれは日本語の要旨です。"
    en, ja = ResearchCoordinator._parse_abstract_output(raw)
    assert en == "This is the English abstract."
    assert ja == "これは日本語の要旨です。"


def test_parse_abstract_output_fallback_no_separators():
    raw = "This is just raw output without separators."
    en, ja = ResearchCoordinator._parse_abstract_output(raw)
    assert en == raw.strip()
    assert ja == ""


from research_team.orchestrator.document_editor import _STYLE_EDIT_INSTRUCTIONS, _build_edit_prompt


def test_paper_style_edit_instruction_exists():
    assert "paper" in _STYLE_EDIT_INSTRUCTIONS


def test_paper_style_edit_instruction_content():
    instr = _STYLE_EDIT_INSTRUCTIONS["paper"]
    assert "Abstract" in instr
    assert "References" in instr
    assert "要旨" in instr


def test_paper_style_edit_instruction_specifies_languages():
    instr = _STYLE_EDIT_INSTRUCTIONS["paper"]
    assert "英語" in instr
    assert "日本語" in instr


def test_build_edit_prompt_uses_paper_instruction():
    prompt = _build_edit_prompt("量子コンピューティング", "コンテンツ", "paper")
    assert "Abstract" in prompt
    assert "References" in prompt

import pytest
from pathlib import Path
from research_team.output.markdown import MarkdownOutput, _extract_title_from_content, _slugify


def test_save_with_existing_path_overwrites(tmp_path):
    existing = tmp_path / "existing_report.md"
    existing.write_text("古いコンテンツ", encoding="utf-8")

    output = MarkdownOutput(tmp_path)
    path = output.save("新しいコンテンツ", "テスト", output_path=existing)

    assert path == str(existing)
    assert "新しいコンテンツ" in existing.read_text(encoding="utf-8")
    assert "古いコンテンツ" not in existing.read_text(encoding="utf-8")


def test_extract_title_from_content_returns_h1():
    content = "# AIの未来\n\n本文テキストです。"
    assert _extract_title_from_content(content) == "AIの未来"


def test_extract_title_from_content_no_h1_returns_none():
    content = "## サブセクション\n\n本文テキストです。"
    assert _extract_title_from_content(content) is None


def test_extract_title_from_content_skips_empty_h1():
    content = "# \n\n## サブ\n\n本文"
    assert _extract_title_from_content(content) is None


def test_save_uses_h1_title_for_filename(tmp_path):
    output = MarkdownOutput(tmp_path)
    content = "# 量子コンピュータの現状\n\n本文テキストです。"
    path = output.save(content, "全く別の依頼文テキスト")

    filename = Path(path).name
    assert "量子コンピュータの現状" in filename
    assert "全く別の依頼文テキスト" not in filename


def test_save_falls_back_to_topic_when_no_h1(tmp_path):
    output = MarkdownOutput(tmp_path)
    content = "## サブセクションのみのレポート\n\n本文です。"
    path = output.save(content, "フォールバックテスト用トピック")

    filename = Path(path).name
    assert "フォールバックテスト用トピック" in filename


def test_slugify_replaces_spaces_and_special_chars():
    assert _slugify("AIの未来 2026") == "AIの未来_2026"
    assert _slugify("レポート/特集") == "レポート-特集"


def test_slugify_truncates_long_title():
    long_title = "あ" * 60
    assert len(_slugify(long_title)) <= 50

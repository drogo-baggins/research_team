import pytest
from pathlib import Path
from research_team.output.markdown import MarkdownOutput


def test_save_with_existing_path_overwrites(tmp_path):
    existing = tmp_path / "existing_report.md"
    existing.write_text("古いコンテンツ", encoding="utf-8")

    output = MarkdownOutput(tmp_path)
    path = output.save("新しいコンテンツ", "テスト", output_path=existing)

    assert path == str(existing)
    assert "新しいコンテンツ" in existing.read_text(encoding="utf-8")
    assert "古いコンテンツ" not in existing.read_text(encoding="utf-8")

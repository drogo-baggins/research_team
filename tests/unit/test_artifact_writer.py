import pytest
from pathlib import Path
from research_team.output.artifact_writer import ArtifactWriter


def test_write_specialist_draft_creates_file(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_specialist_draft(
        run_id=1,
        specialist_name="経済アナリスト",
        content="## 経済動向\n\n内容サンプル",
    )
    assert Path(path).exists()
    assert "specialist_経済アナリスト" in path or "specialist_" in path
    assert "run1" in path


def test_write_specialist_draft_content_is_correct(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_specialist_draft(
        run_id=2,
        specialist_name="技術専門家",
        content="## 技術分析\n\nサンプルコンテンツ",
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "技術専門家" in text
    assert "技術分析" in text


def test_write_specialist_draft_multiple_specialists(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path1 = writer.write_specialist_draft(1, "専門家A", "内容A" * 50)
    path2 = writer.write_specialist_draft(1, "専門家B", "内容B" * 50)
    assert path1 != path2
    assert Path(path1).exists()
    assert Path(path2).exists()


def test_for_session_creates_artifacts_dir(tmp_path):
    writer = ArtifactWriter.for_session(tmp_path, "20260416_120000")
    assert writer._dir == tmp_path / "sessions" / "20260416_120000" / "artifacts"
    assert writer._dir.exists()


def test_for_session_write_creates_file(tmp_path):
    writer = ArtifactWriter.for_session(tmp_path, "20260416_120000")
    path = writer.write_specialist_draft(1, "専門家A", "内容" * 30)
    assert Path(path).exists()
    assert "sessions" in path


from pathlib import Path as _Path

def test_write_raw_tool_result_web_search(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    writer = ArtifactWriter(tmp_path / "artifacts")
    path = writer.write_raw_tool_result(
        run_id=1,
        specialist_name="地政学アナリスト",
        tool_name="web_search",
        call_index=0,
        result_data={"query": "ホルムズ海峡 2026", "results": [{"title": "test", "url": "https://example.com", "content": "snippet"}]},
    )
    saved = _Path(path)
    assert saved.exists()
    text = saved.read_text(encoding="utf-8")
    assert "web_search" in text
    assert "ホルムズ海峡 2026" in text


def test_write_raw_tool_result_web_fetch(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    writer = ArtifactWriter(tmp_path / "artifacts")
    path = writer.write_raw_tool_result(
        run_id=1,
        specialist_name="エネルギーアナリスト",
        tool_name="web_fetch",
        call_index=2,
        result_data={"url": "https://example.com", "content": "Full page content here"},
    )
    saved = _Path(path)
    assert saved.exists()
    text = saved.read_text(encoding="utf-8")
    assert "web_fetch" in text
    assert "https://example.com" in text


def test_write_raw_tool_result_creates_raw_subdir(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    writer = ArtifactWriter(tmp_path / "artifacts")
    writer.write_raw_tool_result(
        run_id=1,
        specialist_name="テスト",
        tool_name="web_search",
        call_index=0,
        result_data={"query": "test"},
    )
    raw_dir = tmp_path / "artifacts" / "raw"
    assert raw_dir.exists()
    assert any(raw_dir.iterdir())


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
    assert "ch01_sec02" in Path(path).name

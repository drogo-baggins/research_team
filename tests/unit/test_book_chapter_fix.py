from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from research_team.orchestrator.book_pipeline import BookChapterPipeline, BookOutline
from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest
from research_team.orchestrator.quality_loop import QualityFeedback
from research_team.output.artifact_writer import ArtifactWriter


def _make_single_section_outline() -> BookOutline:
    return BookOutline(
        chapters=[
            {
                "chapter_index": 1,
                "chapter_title": "第1章 市場概観",
                "sections": [
                    {
                        "section_index": 1,
                        "section_title": "1-1 市場背景",
                        "key_points": ["論点A"],
                        "specialist_hint": "経済",
                    }
                ],
            }
        ]
    )


def test_coordinator_assemble_book_from_outline_no_attribute_error(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    outline = _make_single_section_outline()
    section_path = tmp_path / "section.md"
    section_path.write_text(
        "---\n\n### 1-1 市場背景\n\n本文です。\n\n## Sources\n- https://example.com",
        encoding="utf-8",
    )

    result = coord._assemble_book_from_outline(
        outline=outline,
        section_paths={
            "ch01_sec01": {
                "artifact_path": str(section_path),
            }
        },
        topic="テストトピック",
    )

    assert "# テストトピック" in result
    assert "本文です。" in result


def test_coordinator_assemble_book_from_outline_includes_discussion(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    outline = _make_single_section_outline()
    section_path = tmp_path / "section.md"
    section_path.write_text(
        "---\n\n### 1-1 市場背景\n\n本文です。",
        encoding="utf-8",
    )
    discussion_path = tmp_path / "discussion.md"
    discussion_path.write_text("# 対談\n\n議論内容", encoding="utf-8")

    result = coord._assemble_book_from_outline(
        outline=outline,
        section_paths={
            "ch01_sec01": {
                "artifact_path": str(section_path),
            }
        },
        discussion_artifact_path=str(discussion_path),
        topic="テストトピック",
    )

    assert "議論内容" in result


def test_coordinator_assemble_book_from_outline_delegates_to_book_assembler(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    outline = _make_single_section_outline()
    section_path = tmp_path / "section.md"
    section_path.write_text("---\n\n本文です。", encoding="utf-8")
    discussion_path = tmp_path / "discussion.md"
    discussion_path.write_text("# 対談\n\n議論内容", encoding="utf-8")

    with patch("research_team.orchestrator.book_assembler.BookAssembleTool.assemble", return_value="# テストトピック\n\nassembled") as assemble_mock:
        result = coord._assemble_book_from_outline(
            outline=outline,
            section_paths={
                "ch01_sec01": {
                    "artifact_path": str(section_path),
                }
            },
            discussion_artifact_path=str(discussion_path),
            topic="テストトピック",
        )

    assert result == "# テストトピック\n\nassembled"
    assemble_mock.assert_called_once_with(
        outline=outline,
        section_paths={
            "ch01_sec01": {
                "artifact_path": str(section_path),
            }
        },
        discussion_path=discussion_path,
        topic="テストトピック",
    )


@pytest.mark.asyncio
async def test_book_chapter_run_calls_document_editor(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    request = ResearchRequest(topic="書籍テスト", style="book_chapter")
    artifact_writer = ArtifactWriter.for_session(tmp_path, "session-book")
    outline = _make_single_section_outline()
    fake_factory = MagicMock()
    fake_factory.agents = {"経済アナリスト": MagicMock(_expertise="経済")}
    assembled_book = "# 書籍タイトル\n\n" + ("十分に長い本文。" * 700)
    edited_book = "# 書籍タイトル\n\n" + ("編集済み本文。" * 700)
    edit_document_mock = AsyncMock(return_value=edited_book)

    with (
        patch("research_team.orchestrator.coordinator.DynamicAgentFactory", return_value=fake_factory),
        patch.object(coord, "_stream_agent_output", new=AsyncMock(side_effect=["pm output", '[{"name": "経済アナリスト", "expertise": "経済"}]'])),
        patch.object(coord, "_wbs_approval_loop", new=AsyncMock(return_value=True)),
        patch.object(coord, "_run_specialist_pass", new=AsyncMock(return_value=("raw specialist draft", {}))),
        patch.object(coord, "_decompose_book_sections", new=AsyncMock(return_value=outline)),
        patch.object(BookChapterPipeline, "run", new=AsyncMock(return_value=("drafted sections", {"ch01_sec01": {"chapter_title": "第1章 市場概観", "section_title": "1-1 市場背景", "artifact_path": "dummy.md"}}))),
        patch.object(coord, "_run_discussion", new=AsyncMock(return_value="# 対談トランスクリプト\n\n発言")),
        patch.object(coord, "_assemble_book_from_outline", return_value=assembled_book),
        patch("research_team.orchestrator.coordinator.edit_document", edit_document_mock),
        patch("research_team.orchestrator.coordinator.QualityLoop.run", new=AsyncMock(return_value=QualityFeedback(passed=True, score=1.0))),
        patch("research_team.orchestrator.coordinator.PDFOutput.save_async", new=AsyncMock(return_value=None)),
    ):
        result = await coord._run_research_inner(
            topic="書籍テスト",
            request=request,
            run_id=1,
            session_id="session-book",
            resume_writer=artifact_writer,
        )

    edit_document_mock.assert_awaited_once()
    call_args = edit_document_mock.call_args
    assert "対談トランスクリプト" not in call_args.args[3]


@pytest.mark.asyncio
async def test_book_pipeline_retries_short_section_and_saves_full_content(tmp_path, caplog):
    outline = _make_single_section_outline()
    short_text = "### 1-1 市場背景\n\n調査を開始いたします。"
    full_text = "### 1-1 市場背景\n\n" + ("十分な本文です。" * 80) + "\n\n## Sources\n- https://example.com"
    stream_fn = AsyncMock(side_effect=[short_text, full_text])
    pipeline = BookChapterPipeline(
        stream_fn=stream_fn,
        specialists=[{"name": "経済アナリスト", "expertise": "経済・金融"}],
    )
    artifact_writer = ArtifactWriter(tmp_path / "artifacts")
    agent = MagicMock()
    agent._expertise = "経済・金融"

    with caplog.at_level("WARNING"):
        combined, section_paths = await pipeline.run(
            topic="書籍テスト",
            outline=outline,
            raw_data="調査データ",
            agents={"経済アナリスト": agent},
            artifact_writer=artifact_writer,
            run_id=1,
        )

    assert stream_fn.await_count == 2
    assert full_text in combined
    saved_path = Path(section_paths["ch01_sec01"]["artifact_path"])
    saved_content = saved_path.read_text(encoding="utf-8")
    assert saved_content.endswith(full_text)
    assert any("too short" in record.message.lower() for record in caplog.records)

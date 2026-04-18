from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas


def test_generate_personas_returns_one_per_specialist():
    specialists = [
        {"name": "Alice", "expertise": "経済学", "research": "GDP成長..."},
        {"name": "Bob", "expertise": "社会学", "research": "格差拡大..."},
    ]
    personas = generate_personas(specialists)
    assert len(personas) == 2


def test_generate_personas_has_required_keys():
    specialists = [{"name": "Alice", "expertise": "経済学", "research": "..."}]
    persona = generate_personas(specialists)[0]
    for key in ("name", "expertise", "personality", "speaking_style", "core_belief", "pet_peeve"):
        assert key in persona, f"missing key: {key}"


def test_generate_personas_name_matches_specialist():
    specialists = [{"name": "TaroSato", "expertise": "物理学", "research": "量子..."}]
    persona = generate_personas(specialists)[0]
    assert persona["name"] == "TaroSato"


@pytest.fixture
def specialists():
    return [
        {"name": "Alice", "expertise": "経済学", "research": "GDP..."},
        {"name": "Bob", "expertise": "社会学", "research": "格差..."},
    ]


@pytest.fixture
def personas(specialists):
    from research_team.orchestrator.discussion import generate_personas
    return generate_personas(specialists)


@pytest.mark.asyncio
async def test_run_returns_non_empty_transcript(specialists, personas):
    async def fake_stream(agent, message, agent_name, **kwargs):
        return f"{agent_name}の発言サンプル"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="AIの未来")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_run_includes_speaker_names(specialists, personas):
    async def fake_stream(agent, message, agent_name, **kwargs):
        return "テスト発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="テスト")
    assert "Alice" in result
    assert "Bob" in result


@pytest.mark.asyncio
async def test_run_calls_stream_fn_correct_times(specialists, personas):
    call_count = 0

    async def fake_stream(agent, message, agent_name, **kwargs):
        nonlocal call_count
        call_count += 1
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=2)
    await orch.run(specialists=specialists, personas=personas, topic="テスト")
    n = len(specialists)
    assert call_count == n + 1 + 2 * n


@pytest.mark.asyncio
async def test_run_respects_env_turns(specialists, personas, monkeypatch):
    monkeypatch.setenv("RT_DISCUSSION_TURNS", "3")
    call_count = 0

    async def fake_stream(agent, message, agent_name, **kwargs):
        nonlocal call_count
        call_count += 1
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    await orch.run(specialists=specialists, personas=personas, topic="テスト")
    n = len(specialists)
    assert call_count == n + 1 + 3 * n


@pytest.mark.asyncio
async def test_run_transcript_has_markdown_header(specialists, personas):
    async def fake_stream(agent, message, agent_name, **kwargs):
        return "発言"

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="AIの未来")
    assert result.startswith("#")


@pytest.mark.asyncio
async def test_run_handles_empty_stream_response(specialists, personas):
    async def fake_stream(agent, message, agent_name, **kwargs):
        return ""

    orch = DiscussionOrchestrator(stream_fn=fake_stream, turns=1)
    result = await orch.run(specialists=specialists, personas=personas, topic="テスト")
    assert isinstance(result, str)


# ── ArtifactWriter.write_discussion ───────────────────────────────

from pathlib import Path
from research_team.output.artifact_writer import ArtifactWriter


def test_write_discussion_creates_file(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_discussion(run_id=1, transcript="# 対談\n\n**Alice**: テスト発言")
    assert Path(path).exists()


def test_write_discussion_file_contains_transcript(tmp_path):
    writer = ArtifactWriter(tmp_path)
    transcript = "# 対談\n\n**Alice**: テスト発言"
    path = writer.write_discussion(run_id=1, transcript=transcript)
    content = Path(path).read_text(encoding="utf-8")
    assert "Alice" in content
    assert "テスト発言" in content


def test_write_discussion_filename_contains_run_id(tmp_path):
    writer = ArtifactWriter(tmp_path)
    path = writer.write_discussion(run_id=42, transcript="# 対談")
    assert "run42" in Path(path).name


# ── ControlUI.show_artifact_link ──────────────────────────────────

@pytest.mark.asyncio
async def test_show_artifact_link_calls_evaluate(tmp_path):
    """show_artifact_link は page.evaluate を呼ぶ。"""
    from research_team.ui.control_ui import ControlUI
    from unittest.mock import AsyncMock, MagicMock

    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate = AsyncMock()

    ui = ControlUI.__new__(ControlUI)
    ui._page = mock_page

    await ui.show_artifact_link("対談トランスクリプト", "/tmp/discussion.md")
    mock_page.evaluate.assert_called_once()
    call_arg = mock_page.evaluate.call_args[0][0]
    assert "addArtifactLink" in call_arg
    assert json.dumps("対談トランスクリプト") in call_arg


@pytest.mark.asyncio
async def test_show_artifact_link_noop_when_page_closed(tmp_path):
    """ページが閉じているとき show_artifact_link は例外を出さない。"""
    from research_team.ui.control_ui import ControlUI
    from unittest.mock import MagicMock

    mock_page = MagicMock()
    mock_page.is_closed.return_value = True

    ui = ControlUI.__new__(ControlUI)
    ui._page = mock_page

    await ui.show_artifact_link("ラベル", "/tmp/test.md")


# ── coordinator discussion integration ────────────────────────────

@pytest.mark.asyncio
async def test_coordinator_calls_discussion_for_magazine_style(tmp_path):
    """magazine_column スタイルで DiscussionOrchestrator.run が呼ばれる。"""
    from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest
    from unittest.mock import AsyncMock, patch, MagicMock

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    discussion_called = []
    artifact_writer = MagicMock()
    artifact_writer.write_wbs.return_value = str(tmp_path / "wbs.md")
    artifact_writer.write_discussion.return_value = str(tmp_path / "discussion.md")
    artifact_writer.write_review.return_value = str(tmp_path / "review.md")
    artifact_writer.write_minutes.return_value = str(tmp_path / "minutes.md")

    async def fake_stream(agent, message, agent_name, **kwargs):
        if agent_name == "PM":
            return "PM output"
        if agent_name == "TeamBuilder":
            return '[{"name": "Alice", "expertise": "経済学"}]'
        if agent_name == "CSM":
            return "フォーマット済みコンテンツ"
        return ""

    with patch("research_team.orchestrator.coordinator.DiscussionOrchestrator") as MockOrch:
        instance = MagicMock()
        async def fake_run(**kwargs):
            discussion_called.append(True)
            return "# 対談\n\n**Alice**: テスト"
        instance.run = fake_run
        MockOrch.return_value = instance

        coord._run_specialist_pass = AsyncMock(return_value="調査内容" * 300)
        coord._run_audit = AsyncMock(return_value={"decision": "APPROVE", "overall_score": 0.9})
        coord._push_wbs = AsyncMock()
        coord._make_artifact_writer = MagicMock(return_value=artifact_writer)
        coord._notify = AsyncMock()
        coord._log = AsyncMock()

        request = ResearchRequest(topic="テスト", depth="standard", style="magazine_column")

        with patch.object(coord, "_stream_agent_output", side_effect=fake_stream):
            with patch.object(coord, "_start_search_server", AsyncMock()):
                with patch.object(coord, "_stop_search_server", AsyncMock()):
                    await coord.run(request)

    assert len(discussion_called) > 0, "DiscussionOrchestrator.run が呼ばれなかった"


@pytest.mark.asyncio
async def test_coordinator_skips_discussion_for_research_report_style(tmp_path):
    """research_report スタイルでは DiscussionOrchestrator.run が呼ばれない。"""
    from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest
    from unittest.mock import AsyncMock, patch, MagicMock

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    discussion_called = []
    artifact_writer = MagicMock()
    artifact_writer.write_wbs.return_value = str(tmp_path / "wbs.md")
    artifact_writer.write_review.return_value = str(tmp_path / "review.md")
    artifact_writer.write_minutes.return_value = str(tmp_path / "minutes.md")

    async def fake_stream(agent, message, agent_name, **kwargs):
        if agent_name == "PM":
            return "PM output"
        if agent_name == "TeamBuilder":
            return '[{"name": "Alice", "expertise": "経済学"}]'
        if agent_name == "CSM":
            return "サマリー"
        return ""

    with patch("research_team.orchestrator.coordinator.DiscussionOrchestrator") as MockOrch:
        instance = MagicMock()
        async def fake_run(**kwargs):
            discussion_called.append(True)
            return "# 対談"
        instance.run = fake_run
        MockOrch.return_value = instance

        coord._run_specialist_pass = AsyncMock(return_value="調査内容" * 300)
        coord._run_audit = AsyncMock(return_value={"decision": "APPROVE", "overall_score": 0.9})
        coord._push_wbs = AsyncMock()
        coord._make_artifact_writer = MagicMock(return_value=artifact_writer)
        coord._notify = AsyncMock()
        coord._log = AsyncMock()

        request = ResearchRequest(topic="テスト", depth="standard", style="research_report")

        with patch.object(coord, "_stream_agent_output", side_effect=fake_stream):
            with patch.object(coord, "_start_search_server", AsyncMock()):
                with patch.object(coord, "_stop_search_server", AsyncMock()):
                    await coord.run(request)

    assert len(discussion_called) == 0, "research_report で DiscussionOrchestrator.run が呼ばれた"

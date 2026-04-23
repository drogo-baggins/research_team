import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import tempfile
import os

from research_team.orchestrator.coordinator import ResearchCoordinator, CompletedSession, SessionState
from research_team.ui.control_ui import ControlUI, MODE_MODIFY_SENTINEL


def _make_coordinator(tmp_dir: str) -> ResearchCoordinator:
    mock_ui = MagicMock(spec=ControlUI)
    mock_ui.get_current_mode = MagicMock(return_value="new_request")
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = AsyncMock(return_value="終了")
    mock_ui.wait_for_session_selection = AsyncMock(return_value=None)
    coordinator = ResearchCoordinator(workspace_dir=tmp_dir, ui=mock_ui)
    return coordinator


def _make_completed_session(tmp_dir: str, topic: str = "テスト調査") -> CompletedSession:
    session_dir = Path(tmp_dir) / "sessions" / "20260101_120000_test" / "artifacts"
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "run_id": 1,
        "topic": topic,
        "style": "research_report",
        "specialists": [],
        "discussion_artifact_path": None,
        "report_path": str(session_dir / "report.md"),
        "book_sections": [],
    }
    manifest_path = session_dir / "manifest_run1.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    report_path = session_dir / "report.md"
    report_path.write_text("# テスト\n\n本文です。", encoding="utf-8")
    return CompletedSession(
        session_id="20260101_120000_test",
        topic=topic,
        run_id=1,
        style="research_report",
        created_at="2026-01-01 12:00",
        artifacts_dir=session_dir,
        manifest_path=manifest_path,
        report_path=str(report_path),
    )


def test_control_ui_mode_defaults_to_new_request():
    mock_browser = MagicMock()
    ui = ControlUI(mock_browser)
    assert ui.get_current_mode() == "new_request"


@pytest.mark.asyncio
async def test_control_ui_mode_selected_signal_updates_mode():
    mock_browser = MagicMock()
    ui = ControlUI(mock_browser)
    await ui._handle_signal({}, {"type": "mode_selected", "mode": "modify"})
    assert ui.get_current_mode() == "modify"


@pytest.mark.asyncio
async def test_control_ui_mode_selected_reverts_to_new_request():
    mock_browser = MagicMock()
    ui = ControlUI(mock_browser)
    await ui._handle_signal({}, {"type": "mode_selected", "mode": "modify"})
    await ui._handle_signal({}, {"type": "mode_selected", "mode": "new_request"})
    assert ui.get_current_mode() == "new_request"


def test_build_modify_prompt_contains_topic_and_request():
    prompt = ResearchCoordinator._build_modify_prompt(
        "AI倫理", "元の内容です", "図を追加してください"
    )
    assert "AI倫理" in prompt
    assert "図を追加してください" in prompt
    assert "元の内容です" in prompt


@pytest.mark.asyncio
async def test_run_modify_session_no_sessions_notifies():
    with tempfile.TemporaryDirectory() as tmp_dir:
        coordinator = _make_coordinator(tmp_dir)
        coordinator._ui.get_current_mode.return_value = "modify"
        session = SessionState()
        await coordinator._run_modify_session(session, "markdown")
        coordinator._ui.append_agent_message.assert_awaited()
        call_args = coordinator._ui.append_agent_message.call_args_list
        messages = [str(c) for c in call_args]
        assert any("修正可能な成果物が見つかりません" in m for m in messages)


@pytest.mark.asyncio
async def test_run_modify_session_cancel_on_session_selection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _make_completed_session(tmp_dir)
        coordinator = _make_coordinator(tmp_dir)
        coordinator._ui.wait_for_session_selection = AsyncMock(return_value=None)
        session = SessionState()
        await coordinator._run_modify_session(session, "markdown")
        assert session.run_count == 0


@pytest.mark.asyncio
async def test_run_modify_session_invalid_selection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _make_completed_session(tmp_dir)
        coordinator = _make_coordinator(tmp_dir)
        coordinator._ui.wait_for_session_selection = AsyncMock(return_value="nonexistent_id")
        session = SessionState()
        await coordinator._run_modify_session(session, "markdown")
        assert session.run_count == 0


@pytest.mark.asyncio
async def test_load_session_content_falls_back_to_report_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        chosen = _make_completed_session(tmp_dir, "フォールバックテスト")
        coordinator = _make_coordinator(tmp_dir)
        with patch(
            "research_team.output.artifact_reconstructor.ArtifactReconstructor.reconstruct",
            side_effect=FileNotFoundError("artifact missing"),
        ):
            content = await coordinator._load_session_content(chosen)
        assert content is not None
        assert "テスト" in content


@pytest.mark.asyncio
async def test_run_modify_session_full_flow_with_approve(tmp_path):
    session_dir = tmp_path / "sessions" / "20260101_120000_test" / "artifacts"
    session_dir.mkdir(parents=True)
    manifest_data = {
        "run_id": 1,
        "topic": "テスト",
        "style": "research_report",
        "specialists": [],
        "discussion_artifact_path": None,
        "report_path": str(session_dir / "report.md"),
        "book_sections": [],
    }
    manifest_path = session_dir / "manifest_run1.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    (session_dir / "report.md").write_text("# 元レポート\n\n元の内容。", encoding="utf-8")

    mock_ui = MagicMock(spec=ControlUI)
    mock_ui.get_current_mode = MagicMock(return_value="modify")
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_session_selection = AsyncMock(return_value="20260101_120000_test")
    mock_ui.wait_for_user_message = AsyncMock(return_value="図を追加してください")

    coordinator = ResearchCoordinator(workspace_dir=str(tmp_path), ui=mock_ui)

    with patch.object(coordinator, "_stream_agent_output", new_callable=AsyncMock, return_value="# 修正済みレポート\n\n修正内容。") as mock_stream, \
         patch.object(coordinator, "_run_audit", new_callable=AsyncMock, return_value={"decision": "APPROVE", "overall_score": 0.9}) as mock_audit, \
         patch("research_team.output.markdown.MarkdownOutput.save", return_value=str(tmp_path / "report_out.md")), \
         patch("research_team.output.pdf.PDFOutput.save_async", new_callable=AsyncMock):
        session = SessionState()
        await coordinator._run_modify_session(session, "markdown")

    assert session.run_count == 1
    mock_stream.assert_awaited_once()
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mode_selected_modify_puts_sentinel_in_queue():
    mock_browser = MagicMock()
    ui = ControlUI(mock_browser)
    await ui._handle_signal({}, {"type": "mode_selected", "mode": "modify"})
    assert not ui._chat_queue.empty()
    assert ui._chat_queue.get_nowait() == MODE_MODIFY_SENTINEL


@pytest.mark.asyncio
async def test_mode_selected_new_request_does_not_put_sentinel():
    mock_browser = MagicMock()
    ui = ControlUI(mock_browser)
    await ui._handle_signal({}, {"type": "mode_selected", "mode": "new_request"})
    assert ui._chat_queue.empty()

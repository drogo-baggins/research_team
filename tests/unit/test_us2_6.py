import pytest
from unittest.mock import AsyncMock, MagicMock
from research_team.orchestrator.coordinator import (
    ResearchCancelledError,
    ResearchCoordinator,
    ResearchRequest,
)


def _make_request(**kwargs) -> ResearchRequest:
    defaults = dict(topic="テストテーマ", depth="standard", style="research_report")
    defaults.update(kwargs)
    return ResearchRequest(**defaults)


def _make_specialists() -> list[dict]:
    return [{"name": "専門家A", "expertise": "経済"}]


def _make_coord(tmp_path, approval_side_effect):
    mock_ui = MagicMock()
    mock_ui.show_wbs_approval = AsyncMock(side_effect=approval_side_effect)

    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=mock_ui)
    coord._notify = AsyncMock()
    coord._stream_agent_output = AsyncMock(return_value="revised WBS")
    coord._push_wbs = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_wbs_approval_loop_returns_true_on_affirmative(tmp_path):
    coord = _make_coord(tmp_path, [{"approved": True}])
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is True


@pytest.mark.asyncio
async def test_wbs_approval_loop_returns_false_on_cancel(tmp_path):
    coord = _make_coord(tmp_path, [None])
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is False


@pytest.mark.asyncio
async def test_wbs_approval_loop_does_not_mutate_request_on_approval(tmp_path):
    """承認時に request の設定値を変更しないこと（設定は事前確定済み）"""
    request = _make_request(depth="deep", style="book_chapter")
    coord = _make_coord(tmp_path, [{"approved": True}])
    await coord._wbs_approval_loop("wbs", _make_specialists(), request, "テーマ", 1)
    assert request.depth == "deep"
    assert request.style == "book_chapter"


@pytest.mark.asyncio
async def test_wbs_approval_loop_calls_pm_on_revision_request(tmp_path):
    side_effect = [
        {"approved": False, "feedback": "もっと詳しく"},
        {"approved": True},
    ]
    coord = _make_coord(tmp_path, side_effect)
    result = await coord._wbs_approval_loop("元のWBS", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is True
    coord._stream_agent_output.assert_called_once()
    call_args = coord._stream_agent_output.call_args[0][1]
    assert "もっと詳しく" in call_args


@pytest.mark.asyncio
async def test_wbs_approval_loop_returns_true_when_no_ui(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=None)
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is True


@pytest.mark.asyncio
async def test_wbs_approval_loop_returns_true_after_max_revisions(tmp_path):
    side_effect = [
        {"approved": False, "feedback": "改善1"},
        {"approved": False, "feedback": "改善2"},
        {"approved": False, "feedback": "改善3"},
    ]
    coord = _make_coord(tmp_path, side_effect)
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1, max_revisions=3)
    assert result is True


@pytest.mark.asyncio
async def test_run_research_raises_cancelled_when_wbs_rejected(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    coord._wbs_approval_loop = AsyncMock(return_value=False)
    coord._stream_agent_output = AsyncMock(return_value='[{"name": "A", "expertise": "B"}]' + " " + "wbs out " * 20)
    coord._push_wbs = AsyncMock()
    coord._mark_wbs_done = AsyncMock()
    coord._make_artifact_writer = MagicMock(return_value=MagicMock(write_wbs=MagicMock(return_value="/tmp/wbs.md")))

    with pytest.raises(ResearchCancelledError):
        await coord._run_research("テーマ", _make_request(), run_id=1)


@pytest.mark.asyncio
async def test_run_interactive_shows_settings_form_before_run(tmp_path):
    """run_interactive がトピック入力後・run 呼び出し前に show_new_research_form を呼ぶこと"""
    mock_ui = MagicMock()
    mock_ui.wait_for_user_message = AsyncMock(side_effect=["テーマ", "終了"])
    mock_ui.show_new_research_form = AsyncMock(return_value=None)
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.get_current_mode = MagicMock(return_value="new_request")
    mock_ui.set_mode_change_callback = MagicMock()

    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=mock_ui)
    coord._detect_resumable_session = MagicMock(return_value=None)
    coord.run = AsyncMock()

    await coord.run_interactive()

    mock_ui.show_new_research_form.assert_called_once()
    coord.run.assert_not_called()


@pytest.mark.asyncio
async def test_run_interactive_uses_settings_from_form(tmp_path):
    """show_new_research_form の返り値で ResearchRequest を初期化して run() を呼ぶこと"""
    mock_ui = MagicMock()
    mock_ui.wait_for_user_message = AsyncMock(side_effect=["テーマ", "終了"])
    mock_ui.show_new_research_form = AsyncMock(return_value={
        "depth": "deep",
        "style": "book_chapter",
        "locales": ["ja"],
        "accessibility": "concise",
    })
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.get_current_mode = MagicMock(return_value="new_request")
    mock_ui.set_mode_change_callback = MagicMock()

    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=mock_ui)
    coord._detect_resumable_session = MagicMock(return_value=None)

    captured_request = {}

    async def fake_run(request, **kwargs):
        captured_request.update({"depth": request.depth, "style": request.style,
                                  "locales": request.locales, "accessibility": request.accessibility})
        from research_team.orchestrator.coordinator import ResearchResult
        return ResearchResult(content="", output_path="/tmp/out.md", quality_score=1.0, iterations=1)
    coord.run = fake_run

    await coord.run_interactive()

    assert captured_request["depth"] == "deep"
    assert captured_request["style"] == "book_chapter"
    assert captured_request["locales"] == ["ja"]
    assert captured_request["accessibility"] == "concise"

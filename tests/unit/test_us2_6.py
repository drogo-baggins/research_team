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
    coord = _make_coord(tmp_path, [{"approved": True, "depth": "standard", "style": "research_report"}])
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is True


@pytest.mark.asyncio
async def test_wbs_approval_loop_returns_false_on_cancel(tmp_path):
    coord = _make_coord(tmp_path, [None])
    result = await coord._wbs_approval_loop("wbs", _make_specialists(), _make_request(), "テーマ", 1)
    assert result is False


@pytest.mark.asyncio
async def test_wbs_approval_loop_updates_depth(tmp_path):
    request = _make_request(depth="standard")
    coord = _make_coord(tmp_path, [{"approved": True, "depth": "deep", "style": "research_report"}])
    await coord._wbs_approval_loop("wbs", _make_specialists(), request, "テーマ", 1)
    assert request.depth == "deep"


@pytest.mark.asyncio
async def test_wbs_approval_loop_updates_style(tmp_path):
    request = _make_request(style="research_report")
    coord = _make_coord(tmp_path, [{"approved": True, "depth": "standard", "style": "executive_memo"}])
    await coord._wbs_approval_loop("wbs", _make_specialists(), request, "テーマ", 1)
    assert request.style == "executive_memo"


@pytest.mark.asyncio
async def test_wbs_approval_loop_calls_pm_on_revision_request(tmp_path):
    side_effect = [
        {"approved": False, "feedback": "もっと詳しく", "depth": "standard", "style": "research_report"},
        {"approved": True, "depth": "standard", "style": "research_report"},
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
        {"approved": False, "feedback": "改善1", "depth": "standard", "style": "research_report"},
        {"approved": False, "feedback": "改善2", "depth": "standard", "style": "research_report"},
        {"approved": False, "feedback": "改善3", "depth": "standard", "style": "research_report"},
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

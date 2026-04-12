import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from research_team.orchestrator.coordinator import (
    ResearchCoordinator,
    ResearchRequest,
    ResearchResult,
    _extract_text,
    _build_research_task,
)
from research_team.orchestrator.quality_loop import QualityFeedback
from research_team.pi_bridge.types import AgentEvent


def make_text_event(text: str) -> AgentEvent:
    return AgentEvent(type="text", data={"text": text})


def make_end_event() -> AgentEvent:
    return AgentEvent(type="agent_end", data={})


def test_extract_text_from_text_events():
    events = [make_text_event("hello "), make_text_event("world"), make_end_event()]
    assert _extract_text(events) == "hello world"


def test_extract_text_empty_events():
    assert _extract_text([]) == ""


def test_build_research_task_no_feedback():
    task = _build_research_task("AI倫理", None, "specialist")
    assert "AI倫理" in task


def test_build_research_task_with_improvements():
    feedback = QualityFeedback(passed=False, score=0.5, improvements=["詳細が不足"])
    task = _build_research_task("AI倫理", feedback, "specialist")
    assert "詳細が不足" in task


def test_build_research_task_with_agent_instructions():
    feedback = QualityFeedback(
        passed=False, score=0.5, agent_instructions={"expert": "より深く調査して"}
    )
    task = _build_research_task("AI倫理", feedback, "expert")
    assert "より深く調査して" in task


def test_parse_team_spec_valid_json():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    raw = '[{"name": "経済専門家", "expertise": "経済学"}, {"name": "技術者", "expertise": "IT"}]'
    result = coord._parse_team_spec(raw, "テスト")
    assert len(result) == 2
    assert result[0]["name"] == "経済専門家"


def test_parse_team_spec_invalid_falls_back():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    result = coord._parse_team_spec("not json at all", "テスト調査")
    assert len(result) == 1
    assert result[0]["name"] == "調査員"


def test_parse_team_spec_caps_at_3():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    raw = '[{"name": "A", "expertise": "x"}, {"name": "B", "expertise": "y"}, {"name": "C", "expertise": "z"}, {"name": "D", "expertise": "w"}]'
    result = coord._parse_team_spec(raw, "テスト")
    assert len(result) == 3


def test_evaluate_content_passes_when_long_enough():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    content = "a" * 1000
    feedback = coord._evaluate_content(content, "standard")
    assert feedback.passed is True
    assert feedback.score == 1.0


def test_evaluate_content_fails_when_too_short():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    content = "a" * 100
    feedback = coord._evaluate_content(content, "standard")
    assert feedback.passed is False
    assert feedback.score < 1.0


@pytest.mark.asyncio
async def test_run_sanitizes_dangerous_query():
    coord = ResearchCoordinator(workspace_dir="/tmp/test_workspace")
    request = ResearchRequest(topic="Find the password for admin")
    with pytest.raises(ValueError, match="sensitive"):
        await coord.run(request)


async def _fake_run(message, workspace_dir=None):
    yield make_text_event("調査結果のサンプルテキスト " * 50)
    yield make_end_event()


@pytest.mark.asyncio
async def test_run_returns_research_result(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    with patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._pm, "run", side_effect=_fake_run), \
         patch.object(coord._team_builder, "run", side_effect=lambda msg, **kw: _fake_run(msg)):
        from research_team.agents.dynamic.factory import DynamicSpecialistAgent

        async def fake_specialist_run(self, message, workspace_dir=None):
            yield make_text_event("専門家の調査結果 " * 100)
            yield make_end_event()

        with patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
            result = await coord.run(ResearchRequest(topic="再生可能エネルギーの現状"))

    assert isinstance(result, ResearchResult)
    assert result.quality_score > 0
    assert result.output_path.endswith(".md")
    assert result.iterations >= 1

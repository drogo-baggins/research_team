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
    return AgentEvent(
        type="message_update",
        data={"assistantMessageEvent": {"type": "text_delta", "delta": text}},
    )


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


def test_build_research_task_includes_web_search_instruction():
    task = _build_research_task("AI倫理", None, "specialist")
    assert "web_search" in task


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


def make_tool_start_event(tool_name: str, args: dict) -> AgentEvent:
    return AgentEvent(type="tool_execution_start", data={"toolName": tool_name, "args": args})


def make_tool_end_event(tool_name: str, is_error: bool = False) -> AgentEvent:
    return AgentEvent(type="tool_execution_end", data={"toolName": tool_name, "isError": is_error})


def make_turn_start_event(turn_index: int) -> AgentEvent:
    return AgentEvent(type="turn_start", data={"turnIndex": turn_index})


def make_retry_event(attempt: int, error_message: str) -> AgentEvent:
    return AgentEvent(type="auto_retry_start", data={"attempt": attempt, "errorMessage": error_message})


def make_extension_error_event(error: str) -> AgentEvent:
    return AgentEvent(type="extension_error", data={"error": error})


async def _fake_run(message, workspace_dir=None, search_port=0):
    yield make_text_event("調査結果のサンプルテキスト " * 50)
    yield make_end_event()


@pytest.mark.asyncio
async def test_stream_agent_output_logs_tool_execution(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    log_calls: list[tuple[str, str]] = []

    async def fake_log(status: str, text: str) -> None:
        log_calls.append((status, text))

    coord._log = fake_log

    async def fake_run(message, workspace_dir=None, search_port=0):
        yield make_turn_start_event(0)
        yield make_tool_start_event("web_search", {"query": "AI倫理"})
        yield make_tool_end_event("web_search", is_error=False)
        yield make_text_event("結果テキスト")
        yield make_end_event()

    class FakeAgent:
        def run(self, msg, workspace_dir=None, search_port=0):
            return fake_run(msg, workspace_dir=workspace_dir, search_port=search_port)

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()):
        result = await coord._stream_agent_output(FakeAgent(), "test", "TestAgent")

    statuses = [s for s, _ in log_calls]
    texts = [t for _, t in log_calls]
    assert "running" in statuses
    assert any("web_search" in t and "AI倫理" in t for t in texts)
    assert any("web_search" in t and "完了" in t for t in texts)
    assert result == "結果テキスト"


@pytest.mark.asyncio
async def test_stream_agent_output_logs_tool_error(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    log_calls: list[tuple[str, str]] = []

    async def fake_log(status: str, text: str) -> None:
        log_calls.append((status, text))

    coord._log = fake_log

    async def fake_run(message, workspace_dir=None, search_port=0):
        yield make_tool_start_event("web_fetch", {"url": "https://example.com"})
        yield make_tool_end_event("web_fetch", is_error=True)
        yield make_end_event()

    class FakeAgent:
        def run(self, msg, workspace_dir=None, search_port=0):
            return fake_run(msg, workspace_dir=workspace_dir, search_port=search_port)

    result = await coord._stream_agent_output(FakeAgent(), "test", "TestAgent")

    assert any(s == "error" and "web_fetch" in t for s, t in log_calls)


@pytest.mark.asyncio
async def test_stream_agent_output_logs_retry_and_extension_error(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    log_calls: list[tuple[str, str]] = []

    async def fake_log(status: str, text: str) -> None:
        log_calls.append((status, text))

    coord._log = fake_log

    async def fake_run(message, workspace_dir=None, search_port=0):
        yield make_retry_event(1, "timeout")
        yield make_extension_error_event("connection refused")
        yield make_end_event()

    class FakeAgent:
        def run(self, msg, workspace_dir=None, search_port=0):
            return fake_run(msg, workspace_dir=workspace_dir, search_port=search_port)

    await coord._stream_agent_output(FakeAgent(), "test", "TestAgent")

    assert any("リトライ" in t and "timeout" in t for _, t in log_calls)
    assert any(s == "error" and "connection refused" in t for s, t in log_calls)


@pytest.mark.asyncio
async def test_run_returns_research_result(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._pm_agent, "run", side_effect=_fake_run), \
         patch.object(coord._team_builder, "run", side_effect=_fake_run):
        from research_team.agents.dynamic.factory import DynamicSpecialistAgent

        async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
            yield make_text_event("専門家の調査結果 " * 100)
            yield make_end_event()

        with patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
            result = await coord.run(ResearchRequest(topic="再生可能エネルギーの現状"))

    assert isinstance(result, ResearchResult)
    assert result.quality_score > 0
    assert result.output_path.endswith(".md")
    assert result.iterations >= 1


def test_coordinator_passes_workspace_to_project_manager(tmp_path):
    """Bug fix: ProjectManager must use same workspace_dir as coordinator"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    assert coord._project_manager._workspace == tmp_path


def test_coordinator_uses_project_files_dir_when_active(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    project = coord._project_manager.init("Test project")
    coord._project_manager.switch(project.id)

    agent_workspace = coord._get_agent_workspace()
    assert agent_workspace == str(coord._project_manager.project_files_dir(project.id))
    assert agent_workspace != str(tmp_path)


def test_coordinator_falls_back_to_workspace_root_when_no_active(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    assert coord._get_agent_workspace() == str(tmp_path)

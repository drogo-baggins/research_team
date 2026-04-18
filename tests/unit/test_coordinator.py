import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from research_team.orchestrator.coordinator import (
    ResearchCoordinator,
    ResearchRequest,
    ResearchResult,
    _extract_text,
    _build_research_task,
    _is_negative,
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
    content = (
        "## 概要\n\nhttps://example.com/source1 参照。\n\n"
        + "a" * 800
        + "\n\n## 結論\n\nhttps://example.com/source2 参照。\n\n"
        + "b" * 200
    )
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
async def test_stream_agent_output_saves_raw_on_tool_end(tmp_path):
    """tool_execution_end イベントで生結果が raw/ に保存される。"""
    from research_team.output.artifact_writer import ArtifactWriter

    writer = ArtifactWriter(tmp_path / "artifacts")

    async def fake_run(message, workspace_dir=None, search_port=0):
        yield AgentEvent(type="tool_execution_start", data={"toolName": "web_search", "args": {"query": "テスト"}})
        yield AgentEvent(type="tool_execution_end", data={
            "toolName": "web_search",
            "isError": False,
            "args": {"query": "テスト"},
            "result": {"query": "テスト", "results": [{"title": "T", "url": "http://x.com", "content": "c"}]},
        })
        yield AgentEvent(type="message_update", data={"assistantMessageEvent": {"type": "text_delta", "delta": "完了"}})
        yield AgentEvent(type="agent_end", data={})

    class FakeAgent:
        def run(self, message, workspace_dir=None, search_port=0):
            return fake_run(message)

    import os
    os.makedirs(str(tmp_path / "workspace"), exist_ok=True)
    coord = ResearchCoordinator(workspace_dir=str(tmp_path / "workspace"))

    result = await coord._stream_agent_output(
        FakeAgent(), "test", "TestAgent",
        artifact_writer=writer,
        run_id=1,
    )

    assert result == "完了"
    raw_files = list((tmp_path / "artifacts" / "raw").glob("*.md"))
    assert len(raw_files) == 1
    content = raw_files[0].read_text(encoding="utf-8")
    assert "web_search" in content
    assert "テスト" in content


@pytest.mark.asyncio
async def test_run_returns_research_result(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._pm_agent, "run", side_effect=_fake_run), \
         patch.object(coord._team_builder, "run", side_effect=_fake_run), \
         patch.object(coord._auditor, "run", side_effect=_fake_run):
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


@pytest.mark.asyncio
async def test_wbs_is_displayed_via_ui(tmp_path):
    """PM の WBS 出力がチャットUIに表示されることを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    notify_calls: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))

    coord._notify = fake_notify
    coord._log = AsyncMock()

    async def fake_pm_run(message, workspace_dir=None, search_port=0):
        yield make_text_event("# WBS\n\n## マイルストン1: 情報収集\n- タスク1.1: web_search\n")
        yield make_end_event()

    coord._pm_agent.run = fake_pm_run

    async def fake_team_run(message, workspace_dir=None, search_port=0):
        yield make_text_event('[{"name": "調査員", "expertise": "テスト"}]')
        yield make_end_event()

    coord._team_builder.run = fake_team_run

    from research_team.agents.dynamic.factory import DynamicSpecialistAgent

    async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
        yield make_text_event("専門家調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._auditor, "run", side_effect=_fake_run), \
         patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
        await coord.run(ResearchRequest(topic="テストテーマ"))

    pm_msgs = [msg for agent, msg in notify_calls if agent == "PM"]
    assert len(pm_msgs) >= 1
    assert "WBS" in pm_msgs[0] or "マイルストン" in pm_msgs[0]


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


def test_make_artifact_writer_uses_project_dir_when_active(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    project = coord._project_manager.init("テスト")
    coord._project_manager.switch(project.id)
    writer = coord._make_artifact_writer("20260416_120000")
    expected = coord._project_manager.project_files_dir(project.id) / "artifacts"
    assert writer._dir == expected


def test_make_artifact_writer_uses_session_dir_when_no_project(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    writer = coord._make_artifact_writer("20260416_120000")
    assert "sessions" in str(writer._dir)
    assert "20260416_120000" in str(writer._dir)


@pytest.mark.asyncio
async def test_checkpoint_created_after_specialist_pass(tmp_path):
    """スペシャリストパス完了後にチェックポイントが作成されることを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    project = coord._project_manager.init("テストプロジェクト")
    coord._project_manager.switch(project.id)

    notify_calls: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))

    coord._notify = fake_notify
    coord._log = AsyncMock()

    async def fake_agent_run(message, workspace_dir=None, search_port=0):
        yield make_text_event("調査結果 " * 100)
        yield make_end_event()

    coord._pm_agent.run = fake_agent_run
    coord._team_builder.run = fake_agent_run

    from research_team.agents.dynamic.factory import DynamicSpecialistAgent

    async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
        yield make_text_event("専門家調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=fake_agent_run), \
         patch.object(coord._auditor, "run", side_effect=fake_agent_run), \
         patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
        await coord.run(ResearchRequest(topic="テストテーマ"))

    checkpoints_dir = coord._project_manager._workspace / "projects" / project.id / "checkpoints"
    checkpoint_files = list(checkpoints_dir.glob("*.json")) if checkpoints_dir.exists() else []
    assert len(checkpoint_files) >= 1, "チェックポイントが作成されていない"

    csm_msgs = [msg for agent, msg in notify_calls if agent == "CSM"]
    assert any("中間" in msg or "チェックポイント" in msg or "draft" in msg.lower() for msg in csm_msgs), \
        f"中間成果物通知がない。notify_calls={notify_calls}"


@pytest.mark.asyncio
async def test_specialist_drafts_saved_during_pass(tmp_path):
    """スペシャリスト完了ごとに中間ファイルが保存され、CSM に通知される"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    notify_calls: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))

    coord._notify = fake_notify
    coord._log = AsyncMock()

    async def fake_agent_run(message, workspace_dir=None, search_port=0):
        yield make_text_event("調査結果 " * 100)
        yield make_end_event()

    coord._pm_agent.run = fake_agent_run
    coord._team_builder.run = fake_agent_run

    from research_team.agents.dynamic.factory import DynamicSpecialistAgent

    async def fake_specialist_run(self, message, workspace_dir=None, search_port=0):
        yield make_text_event("専門家調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=fake_agent_run), \
         patch.object(coord._auditor, "run", side_effect=fake_agent_run), \
         patch.object(DynamicSpecialistAgent, "run", fake_specialist_run):
        await coord.run(ResearchRequest(topic="テストテーマ"), session_id="test_session")

    # ファイルが保存されている
    artifacts_dir = tmp_path / "sessions" / "test_session" / "artifacts"
    specialist_files = list(artifacts_dir.glob("specialist_*.md")) if artifacts_dir.exists() else []
    assert len(specialist_files) >= 1, f"スペシャリスト中間ファイルがない: {list(artifacts_dir.iterdir()) if artifacts_dir.exists() else 'dir missing'}"

    # CSM への通知がある
    csm_file_notifications = [
        msg for agent, msg in notify_calls
        if agent == "CSM" and "📄" in msg and "保存" in msg
    ]
    assert len(csm_file_notifications) >= 1, f"ファイル保存通知がない。notify_calls={notify_calls}"


def test_is_negative_recognizes_no():
    assert _is_negative("いいえ") is True
    assert _is_negative("no") is True
    assert _is_negative("終了") is True
    assert _is_negative("終わり") is True
    assert _is_negative("完了") is True


def test_is_negative_does_not_match_affirmative():
    assert _is_negative("はい") is False
    assert _is_negative("yes") is False
    assert _is_negative("追加調査してほしい") is False


def test_summary_prompt_uses_full_content_when_no_env(monkeypatch, tmp_path):
    """RT_MAX_SUMMARY_CHARS 未設定なら combined_content 全文が summary_prompt に含まれる。"""
    monkeypatch.delenv("RT_MAX_SUMMARY_CHARS", raising=False)
    from research_team.orchestrator.coordinator import ResearchCoordinator

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    long_content = "A" * 10_000
    prompt = coord._build_summary_prompt("テスト", long_content)
    assert long_content in prompt


def test_audit_prompt_uses_full_content_when_no_env(monkeypatch, tmp_path):
    """RT_MAX_AUDIT_CHARS 未設定なら content 全文が audit_prompt に含まれる。"""
    monkeypatch.delenv("RT_MAX_AUDIT_CHARS", raising=False)
    from research_team.orchestrator.coordinator import ResearchCoordinator

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    long_content = "B" * 10_000
    prompt = coord._build_audit_prompt("テスト", long_content)
    assert long_content in prompt


@pytest.mark.asyncio
async def test_run_interactive_additional_request_loop(tmp_path):
    """調査完了後に追加リクエストを受け付けるループが動作することを検証"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    messages_sent: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        messages_sent.append((agent, message))

    coord._notify = fake_notify
    coord._log = AsyncMock()

    user_inputs = [
        "テストテーマA",
        "はい",
        "1",
        "別のテーマ追加",
        "はい",
        "1",
        "終了",
    ]
    input_iter = iter(user_inputs)

    async def fake_wait() -> str:
        return next(input_iter)

    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = fake_wait
    coord._ui = mock_ui

    run_calls: list[ResearchRequest] = []

    async def fake_run(request: ResearchRequest, run_id: int = 0, session_id: str = "") -> ResearchResult:
        run_calls.append(request)
        return ResearchResult(
            content="調査結果",
            output_path=str(tmp_path / "report.md"),
            quality_score=1.0,
            iterations=1,
        )

    coord.run = fake_run

    await coord.run_interactive(depth="standard")

    assert len(run_calls) == 2, f"run() が{len(run_calls)}回呼ばれた（期待: 2回）"
    assert run_calls[0].topic == "テストテーマA"

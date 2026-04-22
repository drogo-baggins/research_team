import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from research_team.orchestrator.coordinator import (
    ResearchCoordinator,
    ResearchRequest,
    ResearchResult,
    SessionState,
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


def test_research_request_locales_default():
    request = ResearchRequest(topic="AI倫理", depth="standard", output_format="report")
    assert request.locales == ["ja", "en"]


def test_research_request_locales_custom():
    request = ResearchRequest(topic="AI倫理", depth="standard", output_format="report", locales=["zh-CN", "ko"])
    assert request.locales == ["zh-CN", "ko"]


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
            "result": {
                "content": [{"type": "text", "text": "..."}],
                "details": [{"title": "T", "url": "http://x.com", "content": "c", "source": "human"}],
            },
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
         patch.object(coord._auditor, "run", side_effect=_fake_run), \
         patch.object(coord._doc_editor, "run", side_effect=_fake_run):
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


def test_session_state_has_last_run_id():
    state = SessionState()
    assert state.last_run_id == 0
    state.last_run_id = 3
    assert state.last_run_id == 3


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


def test_evaluate_content_book_chapter_deep_threshold():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    short_content = "x" * 14999
    result = coord._evaluate_content(short_content, "deep", style="book_chapter")
    assert result.passed is False

    long_content = "x" * 15000
    result = coord._evaluate_content(long_content, "deep", style="book_chapter")
    assert result.passed is True


def test_evaluate_content_default_unchanged():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    content_2000 = "x" * 2000
    result = coord._evaluate_content(content_2000, "deep")
    assert result.passed is True


def test_assemble_book_from_outline_basic(tmp_path):
    from research_team.orchestrator.book_pipeline import BookOutline

    outline = BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "導入",
            "sections": [
                {"section_index": 1, "section_title": "背景", "key_points": []},
                {"section_index": 2, "section_title": "目的", "key_points": []},
            ],
        },
        {
            "chapter_index": 2,
            "chapter_title": "本論",
            "sections": [
                {"section_index": 1, "section_title": "分析", "key_points": []},
            ],
        },
    ])

    def make_artifact(section_id: str, content: str) -> str:
        path = tmp_path / f"book_{section_id}_run1_20260101.md"
        path.write_text(
            f"# 書籍セクション — {section_id} / Run 1 (20260101)\n\n"
            f"**章:** 導入  \n**節:** test\n\n---\n\n{content}",
            encoding="utf-8",
        )
        return str(path)

    section_paths = {
        "ch01_sec01": {"artifact_path": make_artifact("ch01_sec01", "### 背景\n\n背景の内容です。")},
        "ch01_sec02": {"artifact_path": make_artifact("ch01_sec02", "### 目的\n\n目的の内容です。")},
        "ch02_sec01": {"artifact_path": make_artifact("ch02_sec01", "### 分析\n\n分析の内容です。")},
    }

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    result = coord._assemble_book_from_outline(outline, section_paths)

    assert "## 目次" in result
    assert "第1章" in result
    assert "第2章" in result
    assert "背景の内容です。" in result
    assert "目的の内容です。" in result
    assert "分析の内容です。" in result
    assert "---" in result


def test_assemble_book_from_outline_with_discussion(tmp_path):
    from research_team.orchestrator.book_pipeline import BookOutline

    outline = BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "テスト章",
            "sections": [
                {"section_index": 1, "section_title": "節A", "key_points": []},
            ],
        },
    ])

    sec_path = tmp_path / "book_ch01_sec01_run1_20260101.md"
    sec_path.write_text(
        "# header\n\n**章:** テスト  \n**節:** A\n\n---\n\n### 節A\n\n節Aの内容。",
        encoding="utf-8",
    )

    disc_path = tmp_path / "discussion_run1_20260101.md"
    disc_path.write_text("## スペシャリスト対談\n\n対談内容。", encoding="utf-8")

    section_paths = {"ch01_sec01": {"artifact_path": str(sec_path)}}

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    result = coord._assemble_book_from_outline(
        outline, section_paths, discussion_artifact_path=str(disc_path)
    )

    assert "節Aの内容。" in result
    assert "スペシャリスト対談" in result


def test_assemble_book_missing_artifact_skipped(tmp_path):
    from research_team.orchestrator.book_pipeline import BookOutline

    outline = BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "章",
            "sections": [
                {"section_index": 1, "section_title": "節", "key_points": []},
            ],
        },
    ])

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    result = coord._assemble_book_from_outline(outline, {})

    assert "## 目次" in result
    assert "第1章" in result


def test_summary_prompt_uses_full_content_when_no_env(monkeypatch, tmp_path):
    """RT_MAX_SUMMARY_CHARS 未設定なら combined_content 全文が summary_prompt に含まれる。"""
    monkeypatch.delenv("RT_MAX_SUMMARY_CHARS", raising=False)
    from research_team.orchestrator.coordinator import ResearchCoordinator

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    long_content = "A" * 10_000
    prompt = coord._build_summary_prompt("テスト", long_content)
    assert long_content in prompt


def test_parse_regenerate_intent_style_change():
    from research_team.orchestrator.coordinator import _parse_regenerate_intent, RegenerateRequest

    result = _parse_regenerate_intent("コラム形式に変えて", last_run_id=1)
    assert result is not None
    assert isinstance(result, RegenerateRequest)
    assert result.re_research_specialists == []


def test_parse_regenerate_intent_new_topic_returns_none():
    from research_team.orchestrator.coordinator import _parse_regenerate_intent

    result = _parse_regenerate_intent("量子コンピュータについて調査して", last_run_id=1)
    assert result is None


def test_parse_regenerate_intent_no_last_run_returns_none():
    from research_team.orchestrator.coordinator import _parse_regenerate_intent

    result = _parse_regenerate_intent("コラム形式に変えて", last_run_id=0)
    assert result is None


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
        "1",
        "テストテーマA",
        "別のテーマ追加",
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


@pytest.mark.asyncio
async def test_run_interactive_updates_session_last_run_id(tmp_path, monkeypatch):
    import research_team.orchestrator.coordinator as coordinator_module

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    state = SessionState()
    monkeypatch.setattr(coordinator_module, "SessionState", lambda: state)

    user_inputs = ["1", "テストテーマ", "終了"]
    input_iter = iter(user_inputs)

    async def fake_wait() -> str:
        return next(input_iter)

    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = fake_wait
    coord._ui = mock_ui
    coord._log = AsyncMock()

    async def fake_run(request: ResearchRequest, run_id: int = 0, session_id: str = "") -> ResearchResult:
        return ResearchResult(
            content="調査結果",
            output_path=str(tmp_path / "report.md"),
            quality_score=1.0,
            iterations=1,
        )

    coord.run = fake_run

    await coord.run_interactive(depth="standard")

    assert state.last_run_id == 1


@pytest.mark.asyncio
async def test_parse_regenerate_intent_dispatches_in_interactive(tmp_path, monkeypatch):
    import research_team.orchestrator.coordinator as coordinator_module

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    state = SessionState(last_run_id=3, session_id="sess-1")
    monkeypatch.setattr(coordinator_module, "SessionState", lambda: state)

    user_inputs = ["1", "コラム形式に変えて", "終了"]
    input_iter = iter(user_inputs)

    async def fake_wait() -> str:
        return next(input_iter)

    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = fake_wait
    coord._ui = mock_ui
    coord._log = AsyncMock()
    notify_calls: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))

    coord._notify = fake_notify

    regen_result = ResearchResult(
        content="再生成結果",
        output_path=str(tmp_path / "regen.md"),
        quality_score=1.0,
        iterations=0,
    )

    coord.run = AsyncMock()
    coord._run_regenerate = AsyncMock(return_value=regen_result)

    regen_request = coordinator_module.RegenerateRequest(
        run_id=3,
        artifacts_dir="",
        re_research_specialists=[],
    )

    with patch.object(coordinator_module, "_parse_regenerate_intent", return_value=regen_request):
        await coord.run_interactive(depth="standard")

    coord._run_regenerate.assert_awaited_once()
    coord.run.assert_not_called()
    assert state.last_report_path == str(tmp_path / "regen.md")


@pytest.mark.asyncio
async def test_run_interactive_regenerate_manifest_missing_falls_back_to_run(tmp_path, monkeypatch):
    import research_team.orchestrator.coordinator as coordinator_module

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    state = SessionState(last_run_id=2, session_id="sess-2")
    monkeypatch.setattr(coordinator_module, "SessionState", lambda: state)

    user_inputs = ["1", "コラム形式に変えて", "終了"]
    input_iter = iter(user_inputs)

    async def fake_wait() -> str:
        return next(input_iter)

    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = fake_wait
    coord._ui = mock_ui
    coord._log = AsyncMock()
    notify_calls: list[tuple[str, str]] = []

    async def fake_notify(agent: str, message: str) -> None:
        notify_calls.append((agent, message))

    coord._notify = fake_notify

    regen_request = coordinator_module.RegenerateRequest(
        run_id=2,
        artifacts_dir="",
        re_research_specialists=[],
    )

    coord._run_regenerate = AsyncMock(side_effect=FileNotFoundError("manifest missing"))
    coord.run = AsyncMock(
        return_value=ResearchResult(
            content="通常調査",
            output_path=str(tmp_path / "normal.md"),
            quality_score=1.0,
            iterations=1,
        )
    )

    with patch.object(coordinator_module, "_parse_regenerate_intent", return_value=regen_request):
        await coord.run_interactive(depth="standard")

    coord._run_regenerate.assert_awaited_once()
    coord.run.assert_awaited_once()
    assert state.last_report_path == str(tmp_path / "normal.md")
    notify_messages = [message for agent, message in notify_calls if agent == "CSM"]
    assert any("前回の調査データが見つかりません" in msg for msg in notify_messages)


def test_detect_resumable_session_finds_progress_in_sessions(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    from research_team.output.run_progress import RunProgress, SpecialistProgress

    session_id = "20260421_100000_テスト"
    writer = ArtifactWriter.for_session(tmp_path, session_id)
    progress = RunProgress(
        run_id=1,
        topic="テスト調査",
        style="research_report",
        depth="standard",
        locales=["ja"],
        all_specialists=[SpecialistProgress(name="専門家A", expertise="分野A")],
        wbs_artifact_path="",
        created_at="2026-04-21T10:00:00",
    )
    writer.write_run_progress(progress)

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()
    coord._project_manager.get_active_id.return_value = None

    result = coord._detect_resumable_session()
    assert result is not None
    loaded_progress, loaded_writer = result
    assert loaded_progress.topic == "テスト調査"


def test_detect_resumable_session_returns_none_when_no_progress(tmp_path):
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()
    coord._project_manager.get_active_id.return_value = None

    result = coord._detect_resumable_session()
    assert result is None


@pytest.mark.asyncio
async def test_run_specialist_pass_skips_pre_completed():
    from unittest.mock import AsyncMock, MagicMock

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._stream_agent_output = AsyncMock(return_value="新規調査結果")
    coord._mark_wbs_done = AsyncMock()
    coord._notify = AsyncMock()

    agent_a = MagicMock()
    agent_b = MagicMock()
    factory = MagicMock()
    factory.agents = {"完了済み": agent_a, "未完了": agent_b}

    pre_completed = {"完了済み": "キャッシュコンテンツ"}
    combined, paths = await coord._run_specialist_pass(
        factory=factory,
        topic="テスト",
        feedback=None,
        pre_completed=pre_completed,
    )

    assert "キャッシュコンテンツ" in combined
    assert "新規調査結果" in combined
    coord._stream_agent_output.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_specialist_pass_calls_on_specialist_done():
    from unittest.mock import AsyncMock, MagicMock
    from pathlib import Path

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._stream_agent_output = AsyncMock(return_value="調査結果")
    coord._mark_wbs_done = AsyncMock()
    coord._notify = AsyncMock()

    agent = MagicMock()
    factory = MagicMock()
    factory.agents = {"専門家": agent}

    artifact_writer = MagicMock()
    artifact_writer.write_specialist_draft = MagicMock(return_value="/some/path.md")

    done_calls: list[tuple[str, str]] = []

    def on_done(name: str, path: str) -> None:
        done_calls.append((name, path))

    await coord._run_specialist_pass(
        factory=factory,
        topic="テスト",
        feedback=None,
        artifact_writer=artifact_writer,
        on_specialist_done=on_done,
    )

    assert len(done_calls) == 1
    assert done_calls[0] == ("専門家", "/some/path.md")


@pytest.mark.asyncio
async def test_run_interactive_resume_yes_calls_run_research_with_resume_from(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    from research_team.output.run_progress import RunProgress, SpecialistProgress

    session_id = "20260421_100000_テスト"
    writer = ArtifactWriter.for_session(tmp_path, session_id)
    progress = RunProgress(
        run_id=2,
        topic="再開テーマ",
        style="research_report",
        depth="standard",
        locales=["ja"],
        all_specialists=[
            SpecialistProgress(name="専門家A", expertise="分野A", artifact_path="", completed=True),
            SpecialistProgress(name="専門家B", expertise="分野B"),
        ],
        wbs_artifact_path="",
        created_at="2026-04-21T10:00:00",
    )
    writer.write_run_progress(progress)

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    coord._detect_resumable_session = MagicMock(return_value=(progress, writer))
    coord._start_search_server = AsyncMock()
    coord._stop_search_server = AsyncMock()
    coord._log = AsyncMock()
    coord._notify = AsyncMock()

    run_research_calls: list[dict] = []

    async def fake_run_research(topic, request, reference_content="", run_id=0, session_id="", resume_from=None, resume_writer=None):
        run_research_calls.append({"topic": topic, "resume_from": resume_from})
        return ResearchResult(
            content="再開調査結果",
            output_path=str(tmp_path / "report.md"),
            quality_score=1.0,
            iterations=1,
        )

    coord._run_research = fake_run_research

    user_inputs = iter(["はい", "終了"])
    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = AsyncMock(side_effect=lambda: next(user_inputs))
    coord._ui = mock_ui

    coord.run = AsyncMock(
        return_value=ResearchResult(content="", output_path="", quality_score=1.0, iterations=0)
    )

    await coord.run_interactive()

    assert len(run_research_calls) == 1
    assert run_research_calls[0]["topic"] == "再開テーマ"
    assert run_research_calls[0]["resume_from"] is progress


@pytest.mark.asyncio
async def test_run_interactive_resume_no_clears_progress(tmp_path):
    from research_team.output.run_progress import RunProgress, SpecialistProgress

    progress = RunProgress(
        run_id=1,
        topic="破棄テーマ",
        style="research_report",
        depth="standard",
        locales=["ja"],
        all_specialists=[SpecialistProgress(name="専門家A", expertise="分野A")],
        wbs_artifact_path="",
        created_at="2026-04-21T10:00:00",
    )
    mock_writer = MagicMock()
    mock_writer.clear_run_progress = MagicMock()

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    coord._detect_resumable_session = MagicMock(return_value=(progress, mock_writer))
    coord._log = AsyncMock()
    coord._notify = AsyncMock()

    user_inputs = iter(["いいえ", "終了"])
    mock_ui = MagicMock()
    mock_ui.append_agent_message = AsyncMock()
    mock_ui.append_log = AsyncMock()
    mock_ui.wait_for_user_message = AsyncMock(side_effect=lambda: next(user_inputs))
    coord._ui = mock_ui

    coord.run = AsyncMock(
        return_value=ResearchResult(content="", output_path="", quality_score=1.0, iterations=0)
    )

    await coord.run_interactive()

    mock_writer.clear_run_progress.assert_called_once()


@pytest.mark.asyncio
async def test_run_research_resume_reads_completed_specialist_file(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    from research_team.output.run_progress import RunProgress, SpecialistProgress

    artifact_path = tmp_path / "specialist_A.md"
    artifact_path.write_text("# 専門家Aの調査\n\nキャッシュ内容です。", encoding="utf-8")

    progress = RunProgress(
        run_id=1,
        topic="テスト調査",
        style="research_report",
        depth="standard",
        locales=["ja"],
        all_specialists=[
            SpecialistProgress(name="専門家A", expertise="分野A", artifact_path=str(artifact_path), completed=True),
            SpecialistProgress(name="専門家B", expertise="分野B"),
        ],
        wbs_artifact_path="",
        created_at="2026-04-21T10:00:00",
    )
    resume_writer = ArtifactWriter(tmp_path / "artifacts")

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    coord._push_wbs = AsyncMock()
    coord._notify = AsyncMock()
    coord._log = AsyncMock()
    coord._mark_wbs_done = AsyncMock()
    coord._set_agent_status = AsyncMock()
    coord._ui = None

    pass_calls: list[dict] = []

    async def fake_specialist_pass(factory, topic, feedback, reference_content="", run_id=0, artifact_writer=None, style="research_report", pre_completed=None, on_specialist_done=None):
        pass_calls.append({"pre_completed": pre_completed})
        return ("結果テキスト", {})

    coord._run_specialist_pass = fake_specialist_pass

    from research_team.orchestrator.quality_loop import QualityFeedback

    with patch("research_team.orchestrator.coordinator.QualityLoop") as mock_ql_cls:
        mock_ql_instance = MagicMock()
        mock_ql_instance.run = AsyncMock(return_value=QualityFeedback(passed=True, score=1.0))
        mock_ql_cls.return_value = mock_ql_instance
        with patch("research_team.orchestrator.coordinator.MarkdownOutput") as mock_md:
            mock_md.return_value.save = MagicMock(return_value=str(tmp_path / "report.md"))
            with patch("research_team.orchestrator.coordinator.edit_document", new=AsyncMock(side_effect=lambda _fn, _ag, _t, c, _s: c)):
                with patch.object(resume_writer, "write_run_manifest", return_value=""):
                    with patch.object(resume_writer, "clear_run_progress"):
                        request = ResearchRequest(topic="テスト調査", depth="standard", style="research_report", locales=["ja"])
                        await coord._run_research(
                            "テスト調査",
                            request,
                            run_id=1,
                            resume_from=progress,
                            resume_writer=resume_writer,
                        )

    assert len(pass_calls) == 1
    pre = pass_calls[0]["pre_completed"]
    assert "専門家A" in pre
    assert "キャッシュ内容です。" in pre["専門家A"]


@pytest.mark.asyncio
async def test_run_research_resume_handles_missing_artifact_files(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter
    from research_team.output.run_progress import RunProgress, SpecialistProgress

    progress = RunProgress(
        run_id=1,
        topic="テスト調査",
        style="research_report",
        depth="standard",
        locales=["ja"],
        all_specialists=[
            SpecialistProgress(name="空パス", expertise="分野A", artifact_path="", completed=True),
            SpecialistProgress(name="存在しないファイル", expertise="分野B", artifact_path="/nonexistent/path.md", completed=True),
            SpecialistProgress(name="未完了", expertise="分野C"),
        ],
        wbs_artifact_path="",
        created_at="2026-04-21T10:00:00",
    )
    resume_writer = ArtifactWriter(tmp_path / "artifacts")

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    coord._push_wbs = AsyncMock()
    coord._notify = AsyncMock()
    coord._log = AsyncMock()
    coord._mark_wbs_done = AsyncMock()
    coord._set_agent_status = AsyncMock()
    coord._ui = None

    pass_calls: list[dict] = []

    async def fake_specialist_pass(factory, topic, feedback, reference_content="", run_id=0, artifact_writer=None, style="research_report", pre_completed=None, on_specialist_done=None):
        pass_calls.append({"pre_completed": pre_completed})
        return ("", {})

    coord._run_specialist_pass = fake_specialist_pass

    from research_team.orchestrator.quality_loop import QualityFeedback

    with patch("research_team.orchestrator.coordinator.QualityLoop") as mock_ql_cls:
        mock_ql_instance = MagicMock()
        mock_ql_instance.run = AsyncMock(return_value=QualityFeedback(passed=True, score=1.0))
        mock_ql_cls.return_value = mock_ql_instance
        with patch("research_team.orchestrator.coordinator.MarkdownOutput") as mock_md:
            mock_md.return_value.save = MagicMock(return_value=str(tmp_path / "report.md"))
            with patch("research_team.orchestrator.coordinator.edit_document", new=AsyncMock(side_effect=lambda _fn, _ag, _t, c, _s: c)):
                with patch.object(resume_writer, "write_run_manifest", return_value=""):
                    with patch.object(resume_writer, "clear_run_progress"):
                        request = ResearchRequest(topic="テスト調査", depth="standard", style="research_report", locales=["ja"])
                        await coord._run_research(
                            "テスト調査",
                            request,
                            run_id=1,
                            resume_from=progress,
                            resume_writer=resume_writer,
                        )

    assert len(pass_calls) == 1
    pre = pass_calls[0]["pre_completed"]
    assert pre["空パス"] == ""
    assert pre["存在しないファイル"] == ""


@pytest.mark.asyncio
async def test_run_specialist_pass_all_pre_completed_skips_all_agents():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._stream_agent_output = AsyncMock(return_value="これは呼ばれてはいけない")
    coord._mark_wbs_done = AsyncMock()
    coord._notify = AsyncMock()

    agent_a = MagicMock()
    agent_b = MagicMock()
    agent_c = MagicMock()
    factory = MagicMock()
    factory.agents = {"専門家A": agent_a, "専門家B": agent_b, "専門家C": agent_c}

    pre_completed = {
        "専門家A": "Aのキャッシュ内容",
        "専門家B": "Bのキャッシュ内容",
        "専門家C": "Cのキャッシュ内容",
    }

    combined, paths = await coord._run_specialist_pass(
        factory=factory,
        topic="テスト",
        feedback=None,
        pre_completed=pre_completed,
    )

    coord._stream_agent_output.assert_not_awaited()
    assert "Aのキャッシュ内容" in combined
    assert "Bのキャッシュ内容" in combined
    assert "Cのキャッシュ内容" in combined


def test_list_completed_sessions_empty_workspace(tmp_path):
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()
    assert coord.list_completed_sessions() == []


def test_list_completed_sessions_returns_sessions(tmp_path):
    from research_team.orchestrator.coordinator import CompletedSession

    sessions_dir = tmp_path / "sessions" / "20260422_120000_テーマA" / "artifacts"
    sessions_dir.mkdir(parents=True)
    manifest = {
        "run_id": 1,
        "topic": "テーマA\n詳細",
        "style": "research_report",
        "specialists": [],
        "discussion_artifact_path": None,
        "report_path": str(sessions_dir / "report.md"),
        "book_sections": [],
    }
    (sessions_dir / "manifest_run1.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()

    results = coord.list_completed_sessions()
    assert len(results) == 1
    assert isinstance(results[0], CompletedSession)
    assert results[0].run_id == 1
    assert results[0].style == "research_report"
    assert results[0].session_id == "20260422_120000_テーマA"


def test_list_completed_sessions_skips_malformed_manifests(tmp_path):
    sessions_dir = tmp_path / "sessions" / "20260422_bad_session" / "artifacts"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "manifest_run1.json").write_text("not json", encoding="utf-8")

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()

    assert coord.list_completed_sessions() == []


def test_build_format_prompt_includes_modification_text():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_format_prompt("テーマ", "コンテンツ", "research_report", "冒頭を削除してください")
    assert "冒頭を削除してください" in prompt
    assert "修正指示" in prompt


def test_build_format_prompt_no_modification_text_omits_section():
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    prompt = coord._build_format_prompt("テーマ", "コンテンツ", "research_report")
    assert "修正指示" not in prompt


@pytest.mark.asyncio
async def test_run_modify_mode_no_sessions_does_not_increment_run_count(tmp_path):
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()

    ui = AsyncMock()
    coord._ui = ui

    from research_team.orchestrator.coordinator import SessionState

    session = SessionState()
    await coord._run_modify_mode(session, "markdown")

    ui.append_agent_message.assert_awaited_once()
    assert session.run_count == 0


@pytest.mark.asyncio
async def test_run_modify_mode_invalid_selection_returns_early(tmp_path):
    from research_team.orchestrator.coordinator import CompletedSession
    from pathlib import Path

    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    coord._project_manager = MagicMock()

    fake_session = CompletedSession(
        session_id="ses_abc",
        topic="テスト",
        run_id=1,
        style="research_report",
        created_at="2026-04-22 12:00",
        artifacts_dir=Path(tmp_path),
        manifest_path=Path(tmp_path) / "manifest_run1.json",
    )
    coord.list_completed_sessions = MagicMock(return_value=[fake_session])

    ui = AsyncMock()
    ui.wait_for_user_message = AsyncMock(return_value="99")
    coord._ui = ui

    from research_team.orchestrator.coordinator import SessionState

    session = SessionState()
    await coord._run_modify_mode(session, "markdown")

    assert session.run_count == 0

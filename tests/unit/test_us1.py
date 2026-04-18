"""
US-2-6: PMがWBS生成後にユーザー承認フローを実行する（テーマ・深さ・スタイル確認含む）
US-1-4: 参照ファイル（テキスト）を調査入力として渡せる
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest
from research_team.orchestrator.quality_loop import QualityFeedback
from research_team.pi_bridge.types import AgentEvent


def make_text_event(text: str) -> AgentEvent:
    return AgentEvent(
        type="message_update",
        data={"assistantMessageEvent": {"type": "text_delta", "delta": text}},
    )


def make_end_event() -> AgentEvent:
    return AgentEvent(type="agent_end", data={})


async def _fake_run(message, workspace_dir=None, search_port=0):
    yield make_text_event("調査結果のサンプルテキスト " * 50)
    yield make_end_event()


# ---------------------------------------------------------------------------
# US-2-6
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_interactive_no_prerun_topic_confirmation(tmp_path):
    messages: list[tuple[str, str]] = []

    class FakeUI:
        _chat_queue: asyncio.Queue = asyncio.Queue()

        async def append_agent_message(self, sender, text):
            messages.append((sender, text))

        async def append_log(self, status, text):
            pass

        async def wait_for_user_message(self) -> str:
            return await self._chat_queue.get()

        async def stream_delta(self, agent_name, delta):
            pass

    ui = FakeUI()
    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=ui)

    async def inject():
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("Pythonの歴史")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("はい")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("1")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("終了")

    with patch.object(coord, "_run_research", new=AsyncMock(return_value=_make_result())), \
         patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()):
        asyncio.create_task(inject())
        await coord.run_interactive(depth="standard")

    csm_texts = [text for sender, text in messages if sender == "CSM"]
    confirmation_msg = "\n".join(csm_texts)
    assert "Pythonの歴史" in confirmation_msg, \
        f"確認メッセージにテーマが含まれていない: {confirmation_msg}"
    assert "standard" in confirmation_msg or "標準" in confirmation_msg, \
        f"確認メッセージに深さが含まれていない: {confirmation_msg}"


@pytest.mark.asyncio
async def test_run_interactive_run_research_called_after_theme_input(tmp_path):
    run_research_called = False

    class FakeUI:
        _chat_queue: asyncio.Queue = asyncio.Queue()

        async def append_agent_message(self, sender, text):
            pass

        async def append_log(self, status, text):
            pass

        async def wait_for_user_message(self) -> str:
            return await self._chat_queue.get()

        async def stream_delta(self, agent_name, delta):
            pass

    ui = FakeUI()
    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=ui)

    async def inject():
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("AI技術の動向")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("はい")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("1")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("終了")

    async def fake_run_research(topic, request, reference_content="", **kwargs):
        nonlocal run_research_called
        run_research_called = True
        return _make_result()

    with patch.object(coord, "_run_research", side_effect=fake_run_research), \
         patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()):
        asyncio.create_task(inject())
        await coord.run_interactive(depth="quick")

    assert run_research_called, "_run_research が呼ばれなかった"


@pytest.mark.asyncio
async def test_run_interactive_continues_loop_after_first_research(tmp_path):
    run_count = 0

    class FakeUI:
        _chat_queue: asyncio.Queue = asyncio.Queue()

        async def append_agent_message(self, sender, text):
            pass

        async def append_log(self, status, text):
            pass

        async def wait_for_user_message(self) -> str:
            return await self._chat_queue.get()

        async def stream_delta(self, agent_name, delta):
            pass

    ui = FakeUI()
    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=ui)

    async def inject():
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("最初のテーマ")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("はい")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("1")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("2番目のテーマ")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("はい")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("1")
        await asyncio.sleep(0.05)
        await ui._chat_queue.put("終了")

    async def fake_run_research(topic, request, reference_content="", **kwargs):
        nonlocal run_count
        run_count += 1
        return _make_result()

    with patch.object(coord, "_run_research", side_effect=fake_run_research), \
         patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()):
        asyncio.create_task(inject())
        await coord.run_interactive(depth="standard")

    assert run_count == 2, f"run が {run_count} 回呼ばれた（期待: 2回）"


# ---------------------------------------------------------------------------
# US-1-4: 参照ファイル
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_research_request_with_reference_file_passes_content_to_task(tmp_path):
    """参照ファイルの内容が調査タスクのプロンプトに含まれる"""
    ref_file = tmp_path / "ref.txt"
    ref_file.write_text("重要な背景情報: XYZプロジェクトの予算は100億円", encoding="utf-8")

    task_messages: list[str] = []

    async def fake_run(self_agent, message, workspace_dir=None, search_port=0):
        task_messages.append(message)
        yield make_text_event("調査結果 " * 100)
        yield make_end_event()

    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._pm_agent, "run", side_effect=_fake_run), \
         patch.object(coord._team_builder, "run", side_effect=_fake_run), \
         patch.object(coord._auditor, "run", side_effect=_fake_run), \
         patch.object(coord, "_evaluate_content", return_value=QualityFeedback(passed=True, score=1.0)):
        from research_team.agents.dynamic.factory import DynamicSpecialistAgent
        with patch.object(DynamicSpecialistAgent, "run", fake_run):
            result = await coord.run(ResearchRequest(
                topic="XYZプロジェクトの調査",
                depth="quick",
                reference_files=[str(ref_file)],
            ))

    # スペシャリストへのタスクメッセージに参照ファイルの内容が含まれること
    assert any("100億円" in msg or "XYZプロジェクトの予算" in msg for msg in task_messages), \
        f"参照ファイルの内容がタスクに含まれていない: {task_messages}"


@pytest.mark.asyncio
async def test_research_request_with_missing_reference_file_raises(tmp_path):
    """存在しない参照ファイルを指定したらエラー"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()):
        with pytest.raises((FileNotFoundError, ValueError)):
            await coord.run(ResearchRequest(
                topic="何かの調査",
                depth="quick",
                reference_files=[str(tmp_path / "nonexistent.txt")],
            ))


@pytest.mark.asyncio
async def test_research_request_without_reference_files_works_as_before(tmp_path):
    """reference_files が空のときは従来どおり動作する"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))

    async def _fake(self_agent, message, workspace_dir=None, search_port=0):
        yield make_text_event("調査結果 " * 100)
        yield make_end_event()

    with patch.object(coord, "_start_search_server", new=AsyncMock()), \
         patch.object(coord, "_stop_search_server", new=AsyncMock()), \
         patch.object(coord._csm, "run", side_effect=_fake_run), \
         patch.object(coord._pm_agent, "run", side_effect=_fake_run), \
         patch.object(coord._team_builder, "run", side_effect=_fake_run), \
         patch.object(coord._auditor, "run", side_effect=_fake_run), \
         patch.object(coord, "_evaluate_content", return_value=QualityFeedback(passed=True, score=1.0)):
        from research_team.agents.dynamic.factory import DynamicSpecialistAgent
        with patch.object(DynamicSpecialistAgent, "run", _fake):
            result = await coord.run(ResearchRequest(topic="AIの概要", depth="quick"))

    assert result.output_path.endswith(".md")


# ---------------------------------------------------------------------------
# depth パラメータの統合テスト (US-1-2 補完)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("depth,min_len", [
    ("quick", 300),
    ("standard", 800),
    ("deep", 2000),
])
def test_evaluate_content_thresholds_for_all_depths(depth, min_len, tmp_path):
    """各 depth の閾値が正しく設定されている"""
    coord = ResearchCoordinator.__new__(ResearchCoordinator)

    # ちょうど閾値未満 → fail
    short = coord._evaluate_content("a" * (min_len - 1), depth)
    assert not short.passed, f"{depth}: {min_len-1}文字でパスしてしまった"

    # ちょうど閾値以上 → pass
    ok = coord._evaluate_content("a" * min_len, depth)
    assert ok.passed, f"{depth}: {min_len}文字でフェイルした"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_result():
    from research_team.orchestrator.coordinator import ResearchResult
    return ResearchResult(
        content="調査結果",
        output_path="/tmp/report.md",
        quality_score=1.0,
        iterations=1,
    )

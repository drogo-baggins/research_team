import asyncio
import os
import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_pi_agent_client_prompt(tmp_path):
    from research_team.pi_bridge.client import PiAgentClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    received: list[str] = []
    async with PiAgentClient(
        system_prompt="You are a concise assistant. Reply in one sentence only.",
        workspace_dir=str(workspace),
    ) as client:
        async for event in client.prompt("Reply with exactly: OK"):
            if event.type == "message_update":
                ame = event.data.get("assistantMessageEvent", {})
                if ame.get("type") == "text_delta":
                    received.append(ame.get("delta", ""))

    text = "".join(received).strip()
    assert len(text) > 0, f"Expected non-empty response, got: {text!r}"


@pytest.mark.asyncio
async def test_research_coordinator_quick(tmp_path):
    from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    coordinator = ResearchCoordinator(workspace_dir=str(workspace))
    request = ResearchRequest(
        topic="Pythonとは何か、一段落で説明してください",
        depth="quick",
        output_format="markdown",
    )
    result = await coordinator.run(request)

    assert result.output_path, "output_path is empty"
    assert os.path.exists(result.output_path), f"Output file not found: {result.output_path}"
    assert result.quality_score >= 0.0
    assert result.iterations >= 1

    content = open(result.output_path, encoding="utf-8").read()
    assert len(content) > 50, f"Output too short: {len(content)} chars"


@pytest.mark.interactive
@pytest.mark.asyncio
async def test_ui_integration(tmp_path, dummy_search_server, monkeypatch):
    from playwright.async_api import async_playwright
    from research_team.ui.control_ui import ControlUI
    from research_team.orchestrator.coordinator import ResearchCoordinator

    monkeypatch.setenv("SEARCH_ENGINE_URL", dummy_search_server)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ui = ControlUI(browser)
        await ui.start()

        messages_appended: list[tuple[str, str]] = []
        logs_appended: list[tuple[str, str]] = []
        approval_calls: list[tuple[str, str]] = []

        _orig_append_agent = ui.append_agent_message
        _orig_append_log = ui.append_log

        async def _spy_agent(sender, text):
            messages_appended.append((sender, text))
            await _orig_append_agent(sender, text)

        async def _spy_log(status, text):
            logs_appended.append((status, text))
            await _orig_append_log(status, text)

        async def _auto_approve(url, title):
            approval_calls.append((url, title))
            return True

        ui.append_agent_message = _spy_agent
        ui.append_log = _spy_log
        ui.request_content_approval = _auto_approve

        coordinator = ResearchCoordinator(workspace_dir=str(workspace), ui=ui)

        async def _inject_topic():
            await asyncio.sleep(0.1)
            await ui._chat_queue.put("Pythonとは何か、一段落で説明してください")

        asyncio.create_task(_inject_topic())

        await coordinator.run_interactive(depth="quick", output_format="markdown")

        await ui.close()

    senders = [s for s, _ in messages_appended]
    assert "CSM" in senders, f"CSMメッセージが届かなかった: {senders}"

    statuses = [s for s, _ in logs_appended]
    assert "running" in statuses, f"runningログが届かなかった: {statuses}"

    assert len(approval_calls) >= 1, (
        f"承認バナーが一度も表示されなかった（web_search/web_fetchが呼ばれていない）: approval_calls={approval_calls}"
    )

    output_files = list(workspace.glob("**/*.md"))
    assert output_files, f"Markdownファイルが生成されなかった: {list(workspace.iterdir())}"

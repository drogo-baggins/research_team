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

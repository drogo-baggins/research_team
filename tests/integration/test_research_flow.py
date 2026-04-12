import pytest
import os


@pytest.mark.skip(reason="Integration test - requires API key and pi-agent installed")
@pytest.mark.asyncio
async def test_research_flow_with_mock_agents(tmp_path):
    from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest

    coordinator = ResearchCoordinator(workspace_dir=str(tmp_path))
    request = ResearchRequest(
        topic="Python asyncioのベストプラクティス",
        depth="quick",
        output_format="markdown",
    )
    result = await coordinator.run(request)

    assert result.output_path
    assert os.path.exists(result.output_path)
    assert result.quality_score >= 0.0

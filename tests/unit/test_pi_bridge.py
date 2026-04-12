import pytest
from research_team.pi_bridge.types import PromptRequest, SteerRequest, FollowUpRequest, AgentEvent


def test_prompt_request_serialization():
    req = PromptRequest(id="req-1", message="hello")
    data = req.model_dump()
    assert data["type"] == "prompt"
    assert data["message"] == "hello"
    assert data["id"] == "req-1"
    assert "method" not in data


def test_steer_request_serialization():
    req = SteerRequest(message="focus on costs")
    data = req.model_dump()
    assert data["type"] == "steer"
    assert data["message"] == "focus on costs"


def test_follow_up_request_serialization():
    req = FollowUpRequest(message="please elaborate")
    data = req.model_dump()
    assert data["type"] == "follow_up"
    assert data["message"] == "please elaborate"


def test_agent_event_agent_end():
    event = AgentEvent(type="agent_end", data={})
    assert event.type == "agent_end"


@pytest.mark.asyncio
async def test_search_server_serves_search_results():
    import aiohttp
    from unittest.mock import AsyncMock
    from research_team.pi_bridge.search_server import SearchServer
    from research_team.search.base import SearchResult

    engine = AsyncMock()
    engine.search.return_value = [
        SearchResult(url="https://example.com", title="Example", content="Sample content", source="test")
    ]

    server = SearchServer(engine)
    port = await server.start()
    assert port > 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/search?q=test&max=3") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert len(data) == 1
                assert data[0]["url"] == "https://example.com"
        engine.search.assert_called_once_with("test", max_results=3)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_search_server_serves_fetch_results():
    import aiohttp
    from unittest.mock import AsyncMock
    from research_team.pi_bridge.search_server import SearchServer
    from research_team.search.base import SearchResult

    engine = AsyncMock()
    engine.fetch.return_value = SearchResult(
        url="https://example.com", title="Fetched", content="Full content", source="fetch"
    )

    server = SearchServer(engine)
    port = await server.start()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/fetch?url=https%3A%2F%2Fexample.com"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["title"] == "Fetched"
        engine.fetch.assert_called_once_with("https://example.com")
    finally:
        await server.stop()


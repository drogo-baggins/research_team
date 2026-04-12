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

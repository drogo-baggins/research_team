from typing import Any, Literal
from pydantic import BaseModel


class PromptRequest(BaseModel):
    id: str
    type: Literal["prompt"] = "prompt"
    message: str


class SteerRequest(BaseModel):
    type: Literal["steer"] = "steer"
    message: str


class FollowUpRequest(BaseModel):
    type: Literal["follow_up"] = "follow_up"
    message: str


class RpcResponse(BaseModel):
    id: str
    type: Literal["response"] = "response"
    command: str
    success: bool
    error: str | None = None


class AgentEvent(BaseModel):
    type: str
    data: dict[str, Any] = {}

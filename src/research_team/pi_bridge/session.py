from dataclasses import dataclass, field
from research_team.pi_bridge.types import AgentEvent


@dataclass
class AgentSession:
    agent_name: str
    events: list[AgentEvent] = field(default_factory=list)
    final_message: str = ""

    def collect(self, event: AgentEvent) -> None:
        self.events.append(event)
        if event.type == "message_update":
            self.final_message = event.data.get("content", self.final_message)

from pathlib import Path
from collections.abc import AsyncIterator
from research_team.agents.base_agent import BaseResearchAgent
from research_team.pi_bridge.client import PiAgentClient
from research_team.pi_bridge.types import AgentEvent

MAX_AGENTS = 5

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "specialist.md.template"


class DynamicSpecialistAgent(BaseResearchAgent):
    def __init__(self, name: str, expertise: str, system_prompt: str) -> None:
        self._name = name
        self._expertise = expertise
        self._system_prompt = system_prompt

    @property
    def name(self) -> str:
        return self._name

    @property
    def skill_path(self) -> Path:
        return Path(__file__).parent / "templates"

    def _load_system_prompt(self) -> str:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
        return template.format(
            name=self._name,
            expertise=self._expertise,
            system_prompt=self._system_prompt,
        )

    def create_client(self, workspace_dir: str | None = None) -> PiAgentClient:
        return PiAgentClient(
            system_prompt=self._load_system_prompt(),
            workspace_dir=workspace_dir,
        )

    async def run(
        self, message: str, workspace_dir: str | None = None
    ) -> AsyncIterator[AgentEvent]:
        async with self.create_client(workspace_dir) as client:
            async for event in client.prompt(message):
                yield event


class DynamicAgentFactory:
    """Factory for creating and managing dynamic specialist agents.

    Enforces MAX_AGENTS limit to prevent resource exhaustion.
    """

    def __init__(self) -> None:
        self._agents: dict[str, DynamicSpecialistAgent] = {}

    @property
    def agents(self) -> dict[str, DynamicSpecialistAgent]:
        return dict(self._agents)

    def create_specialist(
        self, name: str, expertise: str, system_prompt: str
    ) -> DynamicSpecialistAgent:
        """Create a new specialist agent.

        Raises:
            ValueError: If name is already taken or MAX_AGENTS limit reached.
        """
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already exists")
        if len(self._agents) >= MAX_AGENTS:
            raise ValueError(
                f"Cannot create agent '{name}': maximum of {MAX_AGENTS} agents reached"
            )
        agent = DynamicSpecialistAgent(
            name=name, expertise=expertise, system_prompt=system_prompt
        )
        self._agents[name] = agent
        return agent

    def remove_specialist(self, name: str) -> None:
        """Remove a specialist agent by name.

        Raises:
            KeyError: If agent with given name does not exist.
        """
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found")
        del self._agents[name]

    def clear(self) -> None:
        self._agents.clear()

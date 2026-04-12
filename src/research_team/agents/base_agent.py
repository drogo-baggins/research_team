from abc import ABC, abstractmethod
from pathlib import Path
from collections.abc import AsyncIterator
from research_team.pi_bridge.client import PiAgentClient
from research_team.pi_bridge.types import AgentEvent


class BaseResearchAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def skill_path(self) -> Path:
        ...

    def _load_system_prompt(self) -> str:
        skill_file = self.skill_path / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                return parts[2].strip() if len(parts) >= 3 else content
        return ""

    def create_client(
        self, workspace_dir: str | None = None, search_port: int = 0
    ) -> PiAgentClient:
        return PiAgentClient(
            system_prompt=self._load_system_prompt(),
            workspace_dir=workspace_dir,
            search_port=search_port,
        )

    async def run(
        self,
        message: str,
        workspace_dir: str | None = None,
        search_port: int = 0,
    ) -> AsyncIterator[AgentEvent]:
        async with self.create_client(workspace_dir, search_port=search_port) as client:
            async for event in client.prompt(message):
                yield event

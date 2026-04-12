import os
from dataclasses import dataclass, field
from research_team.agents.csm import ClientSuccessManager
from research_team.agents.pm import ProjectManager
from research_team.agents.team_builder import TeamBuilder
from research_team.search.factory import SearchEngineFactory
from research_team.orchestrator.quality_loop import QualityLoop, QualityFeedback
from research_team.output.markdown import MarkdownOutput


@dataclass
class ResearchRequest:
    topic: str
    depth: str = "standard"
    output_format: str = "markdown"
    reference_files: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    content: str
    output_path: str
    quality_score: float
    iterations: int


class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm = ProjectManager()
        self._team_builder = TeamBuilder()
        self._search_engine = SearchEngineFactory.create()
        self._quality_loop = QualityLoop()

    async def run(self, request: ResearchRequest) -> ResearchResult:
        raise NotImplementedError("Implemented in Phase 2 Task 13")

    async def run_interactive(
        self,
        depth: str = "standard",
        output_format: str = "markdown",
    ) -> None:
        if self._ui:
            await self._ui.append_agent_message(
                "CSM",
                "こんにちは！リサーチするテーマを入力してください。"
            )
            topic = await self._ui.wait_for_user_message()
            await self._ui.append_log("running", f"テーマ: {topic}")
            await self._ui.append_agent_message("CSM", f"「{topic}」の調査を開始します。")
        else:
            topic = input("テーマを入力してください: ")

        request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
        try:
            result = await self.run(request)
            if self._ui:
                await self._ui.append_log("done", f"完了: {result.output_path}")
                await self._ui.append_agent_message("CSM", f"調査が完了しました。\n出力: {result.output_path}")
        except NotImplementedError:
            if self._ui:
                await self._ui.append_log("pending", "Phase 2以降で実装予定")
                await self._ui.append_agent_message(
                    "System",
                    "⚠️ Coordinator の完全実装は Phase 2 Task 9 で行います。"
                )

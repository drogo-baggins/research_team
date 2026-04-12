from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from research_team.agents.csm import ClientSuccessManager
from research_team.agents.dynamic.factory import DynamicAgentFactory
from research_team.agents.pm import ProjectManager
from research_team.agents.team_builder import TeamBuilder
from research_team.orchestrator.quality_loop import QualityFeedback, QualityLoop
from research_team.output.markdown import MarkdownOutput
from research_team.pi_bridge.types import AgentEvent
from research_team.search.factory import SearchEngineFactory
from research_team.security.sanitizer import sanitize_query


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


def _extract_text(events: list[AgentEvent]) -> str:
    parts: list[str] = []
    for event in events:
        if event.type == "message_update":
            ame = event.data.get("assistantMessageEvent", {})
            if ame.get("type") == "text_delta":
                parts.append(ame.get("delta", ""))
        elif event.type == "message_end":
            msg = event.data.get("message", {})
            content = msg.get("content", [])
            if not parts:
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
    return "".join(parts).strip()


def _build_research_task(topic: str, feedback: QualityFeedback | None, agent_name: str) -> str:
    base = f"以下のテーマについて詳細な調査を行い、調査結果をMarkdown形式でまとめてください。\n\nテーマ: {topic}"
    if feedback and feedback.improvements:
        improvements = "\n".join(f"- {imp}" for imp in feedback.improvements)
        base += f"\n\n前回の評価で指摘された改善点:\n{improvements}"
    if feedback and agent_name in feedback.agent_instructions:
        base += f"\n\n追加指示: {feedback.agent_instructions[agent_name]}"
    return base


class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm = ProjectManager()
        self._team_builder = TeamBuilder()
        self._search_engine = SearchEngineFactory.create()
        self._quality_loop = QualityLoop()

    async def _notify(self, agent: str, message: str) -> None:
        if self._ui:
            await self._ui.append_agent_message(agent, message)

    async def _collect_agent_output(self, agent, message: str) -> str:
        events: list[AgentEvent] = []
        async for event in agent.run(message, workspace_dir=self._workspace_dir):
            events.append(event)
        return _extract_text(events)

    async def run(self, request: ResearchRequest) -> ResearchResult:
        topic = sanitize_query(request.topic)

        await self._notify("CSM", f"「{topic}」の調査を開始します。チームを編成しています…")

        pm_output = await self._collect_agent_output(
            self._pm,
            f"次の調査プロジェクトのWBSと品質目標を定義してください。\n\nテーマ: {topic}\n深度: {request.depth}",
        )
        await self._notify("PM", pm_output or "WBSを定義しました。")

        example = '[{"name": "経済アナリスト", "expertise": "経済・金融"}]'
        team_spec = await self._collect_agent_output(
            self._team_builder,
            f"次のテーマを調査するための専門家チームを3名以内で定義してください。各専門家の名前と専門分野をJSON配列で返してください。\n\nテーマ: {topic}\n\n例: {example}",
        )
        await self._notify("TeamBuilder", "専門家チームを構成しました。")

        specialists = self._parse_team_spec(team_spec, topic)
        factory = DynamicAgentFactory()

        for spec in specialists:
            factory.create_specialist(
                name=spec["name"],
                expertise=spec["expertise"],
                system_prompt=f"あなたは{spec['expertise']}の専門家です。{topic}について調査します。",
            )

        combined_content = ""
        iterations_done = 0
        last_feedback: QualityFeedback | None = None

        async def run_research(iteration: int, feedback: QualityFeedback) -> str:
            nonlocal combined_content, last_feedback
            last_feedback = feedback
            return await self._run_specialist_pass(factory, topic, feedback)

        combined_content = await self._run_specialist_pass(factory, topic, None)

        async def evaluate(content: str) -> QualityFeedback:
            nonlocal iterations_done
            iterations_done += 1
            return self._evaluate_content(content, request.depth)

        self._quality_loop = QualityLoop(evaluator=evaluate)

        final_feedback = await self._quality_loop.run(
            initial_content=combined_content,
            on_iteration=run_research,
        )

        output_path = MarkdownOutput(self._workspace_dir).save(
            combined_content, topic, report_type="business"
        )

        await self._notify(
            "CSM",
            f"調査が完了しました（品質スコア: {final_feedback.score:.2f}）。\n出力: {output_path}",
        )

        return ResearchResult(
            content=combined_content,
            output_path=output_path,
            quality_score=final_feedback.score,
            iterations=max(iterations_done, 1),
        )

    async def _run_specialist_pass(
        self,
        factory: DynamicAgentFactory,
        topic: str,
        feedback: QualityFeedback | None,
    ) -> str:
        sections: list[str] = []
        for name, agent in factory.agents.items():
            task_message = _build_research_task(topic, feedback, name)
            section = await self._collect_agent_output(agent, task_message)
            if section:
                sections.append(f"## {name}\n\n{section}")
        return "\n\n".join(sections)

    def _parse_team_spec(self, raw: str, topic: str) -> list[dict]:
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start != -1 and end > start:
                data = json.loads(raw[start:end])
                if isinstance(data, list) and all(
                    isinstance(d, dict) and "name" in d and "expertise" in d for d in data
                ):
                    return data[:3]
        except (json.JSONDecodeError, ValueError):
            pass
        return [{"name": "調査員", "expertise": f"{topic}の総合調査"}]

    def _evaluate_content(self, content: str, depth: str) -> QualityFeedback:
        min_length = {"quick": 300, "standard": 800, "deep": 2000}.get(depth, 800)
        if len(content) < min_length:
            return QualityFeedback(
                passed=False,
                score=len(content) / min_length,
                improvements=[f"内容が不十分です（{len(content)}文字 / 目標{min_length}文字）"],
            )
        return QualityFeedback(passed=True, score=1.0)

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
        else:
            topic = input("テーマを入力してください: ")

        request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
        result = await self.run(request)
        if self._ui:
            await self._ui.append_log("done", f"完了: {result.output_path}")

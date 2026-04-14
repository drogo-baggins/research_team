from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from research_team.agents.csm import ClientSuccessManager
from research_team.agents.dynamic.factory import DynamicAgentFactory
from research_team.agents.pm import ProjectManager as PMAgent
from research_team.agents.team_builder import TeamBuilder
from research_team.project.manager import ProjectManager as ProjectFileManager
from research_team.orchestrator.quality_loop import QualityFeedback, QualityLoop
from research_team.output.markdown import MarkdownOutput
from research_team.pi_bridge.search_server import SearchServer
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


def _is_affirmative(text: str) -> bool:
    normalized = text.strip().lower()
    affirmatives = {"はい", "yes", "ok", "okay", "y", "そうです", "お願いします", "進めて"}
    if normalized in affirmatives:
        return True
    if normalized.startswith(("はい", "yes", "ok", "y ")):
        return True
    return False


def _build_research_task(
    topic: str,
    feedback: QualityFeedback | None,
    agent_name: str,
    reference_content: str = "",
) -> str:
    base = (
        f"以下のテーマについて詳細な調査を行い、調査結果をMarkdown形式でまとめてください。"
        f"\n\nテーマ: {topic}"
        f"\n\nweb_search および web_fetch ツールを積極的に活用して、最新の情報を収集してください。"
    )
    if reference_content:
        base += f"\n\n参照情報:\n{reference_content}"
    if feedback and feedback.improvements:
        improvements = "\n".join(f"- {imp}" for imp in feedback.improvements)
        base += f"\n\n前回の評価で指摘された改善点:\n{improvements}"
    if feedback and agent_name in feedback.agent_instructions:
        base += f"\n\n追加指示: {feedback.agent_instructions[agent_name]}"
    return base


def _load_reference_files(paths: list[str]) -> str:
    parts: list[str] = []
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"参照ファイルが見つかりません: {path}")
        with open(path, encoding="utf-8") as f:
            parts.append(f.read())
    return "\n\n".join(parts)


class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm_agent = PMAgent()
        self._project_manager = ProjectFileManager(workspace_dir=self._workspace_dir)
        self._team_builder = TeamBuilder()
        self._search_engine = SearchEngineFactory.create(control_ui=ui)
        self._quality_loop = QualityLoop()
        self._search_server: SearchServer | None = None
        self._search_port: int = 0

    def _get_agent_workspace(self) -> str:
        active_id = self._project_manager.get_active_id()
        if active_id:
            return str(self._project_manager.project_files_dir(active_id))
        return self._workspace_dir

    async def _start_search_server(self) -> None:
        try:
            self._search_server = SearchServer(self._search_engine)
            self._search_port = await self._search_server.start()
        except Exception as exc:
            logger.error("_start_search_server failed: %s", exc)
            self._search_server = None
            self._search_port = 0
            raise

    async def _stop_search_server(self) -> None:
        if self._search_server:
            try:
                await self._search_server.stop()
            except Exception as exc:
                logger.warning("_stop_search_server failed: %s", exc)
            finally:
                self._search_server = None
                self._search_port = 0

    async def _notify(self, agent: str, message: str) -> None:
        if self._ui:
            try:
                await self._ui.append_agent_message(agent, message)
            except Exception as exc:
                logger.warning("_notify failed (agent=%s): %s", agent, exc)

    async def _log(self, status: str, text: str) -> None:
        if self._ui:
            try:
                await self._ui.append_log(status, text)
            except Exception as exc:
                logger.warning("_log failed (status=%s): %s", status, exc)

    async def _stream_agent_output(self, agent, message: str, agent_name: str) -> str:
        parts: list[str] = []
        events: list[AgentEvent] = []
        await self._log("running", f"{agent_name} が処理中...")
        try:
            async for event in agent.run(
                message,
                workspace_dir=self._get_agent_workspace(),
                search_port=self._search_port,
            ):
                events.append(event)
                match event.type:
                    case "turn_start":
                        turn_idx = event.data.get("turnIndex", "")
                        await self._log("running", f"{agent_name} ターン {turn_idx} 開始")
                    case "tool_execution_start":
                        tool = event.data.get("toolName", "")
                        args = event.data.get("args", {})
                        if tool == "web_search":
                            q = args.get("query", "")
                            await self._log("running", f"🔍 {agent_name}: web_search 「{q}」")
                        elif tool == "web_fetch":
                            url = args.get("url", "")
                            await self._log("running", f"🌐 {agent_name}: web_fetch {url}")
                        else:
                            await self._log("running", f"⚙️ {agent_name}: {tool}")
                    case "tool_execution_end":
                        tool = event.data.get("toolName", "")
                        is_error = event.data.get("isError", False)
                        if is_error:
                            await self._log("error", f"{agent_name}: {tool} エラー")
                        else:
                            await self._log("done", f"{agent_name}: {tool} 完了")
                    case "auto_retry_start":
                        attempt = event.data.get("attempt", "")
                        err = event.data.get("errorMessage", "")
                        await self._log("running", f"⚠️ {agent_name}: リトライ中 (試行{attempt}) {err}")
                    case "extension_error":
                        err = event.data.get("error", "")
                        await self._log("error", f"{agent_name}: Extension エラー: {err}")
                    case "message_update":
                        ame = event.data.get("assistantMessageEvent", {})
                        if ame.get("type") == "text_delta":
                            delta = ame.get("delta", "")
                            if delta:
                                parts.append(delta)
                                if self._ui:
                                    try:
                                        await self._ui.stream_delta(agent_name, delta)
                                    except Exception as exc:
                                        logger.warning("stream_delta failed: %s", exc)
        except Exception as exc:
            logger.error("_stream_agent_output: agent=%s error: %s", agent_name, exc, exc_info=True)
            await self._log("error", f"{agent_name}: エラーが発生しました: {exc}")
        text = "".join(parts).strip()
        if not text:
            text = _extract_text(events)
        if text:
            await self._notify(agent_name, text)
        await self._log("done", f"{agent_name} 完了")
        return text

    async def run(self, request: ResearchRequest) -> ResearchResult:
        topic = sanitize_query(request.topic)

        if request.reference_files:
            reference_content = _load_reference_files(request.reference_files)
        else:
            reference_content = ""

        await self._notify("CSM", f"「{topic}」の調査を開始します。チームを編成しています…")
        await self._log("running", f"テーマ: {topic}")

        await self._start_search_server()
        try:
            return await self._run_research(topic, request, reference_content)
        finally:
            await self._stop_search_server()

    async def _run_research(self, topic: str, request: ResearchRequest, reference_content: str = "") -> ResearchResult:
        pm_output = await self._stream_agent_output(
            self._pm_agent,
            f"次の調査プロジェクトのWBSと品質目標を定義してください。\n\nテーマ: {topic}\n深度: {request.depth}",
            "PM",
        )

        example = '[{"name": "経済アナリスト", "expertise": "経済・金融"}]'
        team_spec = await self._stream_agent_output(
            self._team_builder,
            f"次のテーマを調査するための専門家チームを3名以内で定義してください。各専門家の名前と専門分野をJSON配列で返してください。\n\nテーマ: {topic}\n\n例: {example}",
            "TeamBuilder",
        )
        await self._log("done", "専門家チームを構成しました。")

        specialists = self._parse_team_spec(team_spec, topic)
        factory = DynamicAgentFactory()

        for spec in specialists:
            factory.create_specialist(
                name=spec["name"],
                expertise=spec["expertise"],
                system_prompt=f"あなたは{spec['expertise']}の専門家です。{topic}について調査します。",
            )

        iterations_done = 0

        async def run_research(iteration: int, feedback: QualityFeedback) -> str:
            return await self._run_specialist_pass(factory, topic, feedback, reference_content)

        combined_content = await self._run_specialist_pass(factory, topic, None, reference_content)

        active_id = self._project_manager.get_active_id()
        if active_id:
            try:
                checkpoint_path = self._project_manager.create_checkpoint(active_id, "draft_pass1")
                await self._notify(
                    "CSM",
                    f"📁 中間成果物を保存しました。\nチェックポイント: {checkpoint_path}",
                )
            except Exception as exc:
                logger.warning("create_checkpoint failed: %s", exc)

        async def evaluate(content: str) -> QualityFeedback:
            nonlocal iterations_done
            iterations_done += 1
            return self._evaluate_content(content, request.depth)

        self._quality_loop = QualityLoop(evaluator=evaluate)

        final_feedback = await self._quality_loop.run(
            initial_content=combined_content,
            on_iteration=run_research,
        )

        output_path = MarkdownOutput(self._get_agent_workspace()).save(
            combined_content, topic, report_type="business"
        )

        await self._notify(
            "CSM",
            f"調査が完了しました（品質スコア: {final_feedback.score:.2f}）。\n出力: {output_path}",
        )
        await self._log("done", f"完了: {output_path}")

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
        reference_content: str = "",
    ) -> str:
        sections: list[str] = []
        for name, agent in factory.agents.items():
            task_message = _build_research_task(topic, feedback, name, reference_content)
            section = await self._stream_agent_output(agent, task_message, name)
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
            depth_label = {"quick": "簡易", "standard": "標準", "deep": "詳細"}.get(depth, depth)
            while True:
                await self._ui.append_agent_message(
                    "CSM",
                    "こんにちは！リサーチするテーマを入力してください。"
                )
                topic = await self._ui.wait_for_user_message()
                await self._log("running", f"テーマ: {topic}")

                await self._ui.append_agent_message(
                    "CSM",
                    f"テーマ「{topic}」、深さ「{depth_label}」で調査します。よろしいですか？（はい／いいえ）"
                )
                answer = await self._ui.wait_for_user_message()
                if _is_affirmative(answer):
                    break
                await self._ui.append_agent_message(
                    "CSM",
                    "承知しました。もう一度テーマを入力してください。"
                )
        else:
            topic = input("テーマを入力してください: ")

        request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
        try:
            result = await self.run(request)
            if self._ui:
                await self._log("done", f"完了: {result.output_path}")
        except Exception as exc:
            err_msg = f"エラーが発生しました: {exc}"
            tb = traceback.format_exc()
            logger.error("run_interactive error:\n%s", tb)
            await self._notify("System", err_msg)
            await self._log("running", err_msg)
            if self._ui:
                await self._ui.append_log("running", tb)
            raise

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from research_team.agents.csm import ClientSuccessManager
from research_team.agents.auditor import Auditor
from research_team.agents.dynamic.factory import DynamicAgentFactory
from research_team.agents.pm import ProjectManager as PMAgent
from research_team.agents.team_builder import TeamBuilder
from research_team.project.manager import ProjectManager as ProjectFileManager
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas
from research_team.orchestrator.quality_loop import QualityFeedback, QualityLoop
from research_team.output.artifact_writer import ArtifactWriter
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
    style: str = "research_report"


@dataclass
class ResearchResult:
    content: str
    output_path: str
    quality_score: float
    iterations: int


@dataclass
class SessionState:
    current_topic: str = ""
    last_report_path: str = ""
    run_count: int = 0
    session_id: str = ""


@dataclass
class RunContext:
    run_id: int
    topic: str
    depth: str
    style: str


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


def _is_negative(text: str) -> bool:
    normalized = text.strip().lower()
    negatives = {"いいえ", "no", "n", "終了", "終わり", "完了", "やめる", "stop", "quit", "exit"}
    if normalized in negatives:
        return True
    if normalized.startswith(("いいえ", "no ", "終了", "終わり")):
        return True
    return False


def _format_topic_confirmation(topic: str, depth: str = "standard") -> str:
    depth_labels = {
        "quick": "クイック（簡易調査）",
        "standard": "スタンダード（標準調査）",
        "deep": "ディープ（詳細調査）",
    }
    depth_label = depth_labels.get(depth, depth)
    lines = [
        "ご依頼内容を整理しました。",
        "",
        f"**調査テーマ:** {topic}",
        f"**調査深度:** {depth_label}",
        "",
        "上記の内容で調査を開始してよろしいでしょうか？",
        "修正がある場合は内容をそのまま入力してください。",
    ]
    return "\n".join(lines)


def _build_research_task(
    topic: str,
    feedback: QualityFeedback | None,
    agent_name: str,
    reference_content: str = "",
    style: str = "research_report",
) -> str:
    style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["research_report"])
    base = (
        f"以下のテーマについて詳細な調査を行い、調査結果をMarkdown形式でまとめてください。"
        f"\n\nテーマ: {topic}"
        f"\n\nweb_search および web_fetch ツールを積極的に活用して、最新の情報を収集してください。"
        f"\n\n【出力形式の指示】{style_instruction}"
        f"\n\n【重要】調査結果のみをMarkdown形式で出力してください。"
        f"思考過程、謝罪文、「検索します」などの作業説明は一切含めないでください。"
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


_STYLE_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("research_report", "調査レポート（正式・引用密度高）"),
    "2": ("executive_memo", "エグゼクティブメモ（結論先出し・簡潔）"),
    "3": ("magazine_column", "マガジンコラム（物語的・読みやすい）"),
    "4": ("book_chapter", "書籍チャプター（詳細・叙述的）"),
}

_STYLE_INSTRUCTIONS: dict[str, str] = {
    "research_report": (
        "正式な調査レポート形式で記述してください。"
        "客観的な文体、出典URL付きの引用、セクション見出しを用いて構造化してください。"
    ),
    "executive_memo": (
        "エグゼクティブメモ形式で記述してください。"
        "結論・提言を冒頭に置き、根拠を簡潔に続けてください。全体を500字以内に収めてください。"
    ),
    "magazine_column": (
        "マガジンコラム形式で記述してください。"
        "読者を引き込む導入から始め、物語的・読みやすい文体で展開してください。"
    ),
    "book_chapter": (
        "書籍の一章として記述してください。"
        "章タイトル・節タイトルを設け、詳細かつ叙述的に展開してください。"
        "導入・本論・まとめの構成を守り、読者が通読できる完成した章にしてください。"
    ),
}

_STYLES_WITHOUT_EXEC_SUMMARY = {"book_chapter", "magazine_column"}


class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm_agent = PMAgent()
        self._auditor = Auditor()
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

    async def _mark_wbs_done(self, task_id: str) -> None:
        if self._ui and hasattr(self._ui, "update_wbs_task"):
            try:
                await self._ui.update_wbs_task(task_id, True)
            except Exception as exc:
                logger.warning("update_wbs_task failed (id=%s): %s", task_id, exc)

    async def _push_wbs(self, topic: str, specialists: list[dict], run_id: int = 0) -> None:
        if not self._ui or not hasattr(self._ui, "set_wbs"):
            return
        milestones = [
            {
                "id": f"r{run_id}-milestone-planning",
                "title": "計画フェーズ",
                "tasks": [
                    {"id": f"r{run_id}-task-pm", "title": "WBS・品質目標定義", "assignee": "PM", "done": False},
                    {"id": f"r{run_id}-task-team", "title": "専門家チーム編成", "assignee": "TeamBuilder", "done": False},
                ],
            },
            {
                "id": f"r{run_id}-milestone-research",
                "title": "調査フェーズ",
                "tasks": [
                    {
                        "id": f"r{run_id}-task-specialist-{i}",
                        "title": f"{spec['expertise']} 調査",
                        "assignee": spec["name"],
                        "done": False,
                    }
                    for i, spec in enumerate(specialists)
                ],
            },
            {
                "id": f"r{run_id}-milestone-output",
                "title": "出力フェーズ",
                "tasks": [
                    {"id": f"r{run_id}-task-quality", "title": "品質評価・改善ループ", "assignee": "QualityLoop", "done": False},
                    {"id": f"r{run_id}-task-output", "title": "Markdown出力", "assignee": "System", "done": False},
                ],
            },
        ]
        try:
            await self._ui.set_wbs(milestones)
        except Exception as exc:
            logger.warning("_push_wbs failed: %s", exc)

    async def _run_discussion(
        self,
        specialists: list[dict],
        topic: str,
        artifact_writer: "ArtifactWriter | None",
        run_id: int,
    ) -> str:
        personas = generate_personas(specialists)
        turns = int(os.environ.get("RT_DISCUSSION_TURNS", "2"))
        orch = DiscussionOrchestrator(stream_fn=self._stream_agent_output, turns=turns)
        transcript = await orch.run(specialists=specialists, personas=personas, topic=topic)
        if artifact_writer:
            try:
                discussion_path = artifact_writer.write_discussion(run_id=run_id, transcript=transcript)
                if self._ui and hasattr(self._ui, "show_artifact_link"):
                    await self._ui.show_artifact_link("対談トランスクリプト", discussion_path)
            except Exception as exc:
                logger.warning("write_discussion failed: %s", exc)
        return transcript

    async def _set_agent_status(self, agent_name: str, status: str) -> None:
        if self._ui and hasattr(self._ui, "set_agent_status"):
            try:
                await self._ui.set_agent_status(agent_name, status)
            except Exception as exc:
                logger.warning("set_agent_status failed (agent=%s): %s", agent_name, exc)

    async def _stream_agent_output(
        self,
        agent,
        message: str,
        agent_name: str,
        artifact_writer: "ArtifactWriter | None" = None,
        run_id: int = 0,
    ) -> str:
        parts: list[str] = []
        events: list[AgentEvent] = []
        pending_tool_args: dict[str, dict] = {}
        await self._set_agent_status(agent_name, "working")
        await self._log("running", f"{agent_name} が処理中...")
        timeout_sec = float(os.environ.get("RT_AGENT_TIMEOUT_SEC", "1800"))
        try:
            async with asyncio.timeout(timeout_sec):
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
                            pending_tool_args[tool] = args
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

                            # ゼロトラスト蓄積: 生ツール結果を即時保存
                            if artifact_writer and tool in ("web_search", "web_fetch") and not is_error:
                                start_args = pending_tool_args.get(tool, {})
                                result_data = {**start_args, **(event.data.get("result") or {})}
                                try:
                                    call_index = sum(
                                        1 for e in events
                                        if e.type == "tool_execution_end"
                                        and e.data.get("toolName") == tool
                                    )
                                    artifact_writer.write_raw_tool_result(
                                        run_id=run_id,
                                        specialist_name=agent_name,
                                        tool_name=tool,
                                        call_index=call_index,
                                        result_data=result_data,
                                    )
                                except Exception as exc:
                                    logger.warning("write_raw_tool_result failed: %s", exc)
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
        except TimeoutError:
            logger.error(
                "_stream_agent_output: agent=%s timed out after %.0fs",
                agent_name,
                timeout_sec,
            )
            await self._log("error", f"{agent_name}: タイムアウト（{timeout_sec:.0f}秒）")
        except Exception as exc:
            logger.error("_stream_agent_output: agent=%s error: %s", agent_name, exc, exc_info=True)
            await self._log("error", f"{agent_name}: エラーが発生しました: {exc}")
        text = "".join(parts).strip()
        if not text:
            text = _extract_text(events)
        if text:
            await self._notify(agent_name, text)
        await self._log("done", f"{agent_name} 完了")
        await self._set_agent_status(agent_name, "done")
        return text

    async def run(self, request: ResearchRequest, run_id: int = 0, session_id: str = "") -> ResearchResult:
        topic = sanitize_query(request.topic)

        if request.reference_files:
            reference_content = _load_reference_files(request.reference_files)
        else:
            reference_content = ""

        await self._notify("CSM", f"「{topic}」の調査を開始します。チームを編成しています…")
        await self._log("running", f"テーマ: {topic}")

        await self._start_search_server()
        try:
            return await self._run_research(
                topic,
                request,
                reference_content,
                run_id=run_id,
                session_id=session_id,
            )
        finally:
            await self._stop_search_server()

    def _make_artifact_writer(self, session_id: str) -> ArtifactWriter:
        """プロジェクト有無に関わらず ArtifactWriter を返す。"""
        active_id = self._project_manager.get_active_id()
        if active_id:
            artifacts_dir = self._project_manager.project_files_dir(active_id) / "artifacts"
            return ArtifactWriter(artifacts_dir)
        return ArtifactWriter.for_session(Path(self._workspace_dir), session_id)

    def _build_summary_prompt(self, topic: str, content: str) -> str:
        max_chars = os.environ.get("RT_MAX_SUMMARY_CHARS")
        body = content[:int(max_chars)] if max_chars else content
        return (
            f"以下は「{topic}」についての専門家調査結果です。\n\n"
            f"{body}\n\n"
            f"この調査結果から、意思決定者向けに300字以内の「エグゼクティブサマリー」を書いてください。"
            f"最重要な発見を3点、箇条書きで含めてください。日本語で記述してください。"
            f"\n\n【重要】サマリー本文のみを出力してください。説明や前置きは不要です。"
        )

    def _build_format_prompt(self, topic: str, content: str, style: str) -> str:
        max_chars = os.environ.get("RT_MAX_SUMMARY_CHARS")
        body = content[:int(max_chars)] if max_chars else content
        style_instruction = _STYLE_INSTRUCTIONS.get(style, "")
        return (
            f"以下は「{topic}」についての専門家調査結果（生データ）です。\n\n"
            f"{body}\n\n"
            f"上記の調査データを元に、完成した読み物として整形してください。\n"
            f"【形式指示】{style_instruction}\n"
            f"【対談セクション保持】本文中に「## スペシャリスト対談」セクションが含まれる場合、"
            f"そのセクション全体（`> **争点**: ...` や `**名前**: 発言` 形式を含む）を"
            f"改変・削除せずそのまま出力に含めてください。\n"
            f"【重要】整形済みのMarkdown本文のみを出力してください。"
            f"説明文、前置き、謝罪文、作業説明は一切含めないでください。"
        )

    def _build_audit_prompt(self, topic: str, content: str) -> str:
        max_chars = os.environ.get("RT_MAX_AUDIT_CHARS")
        body = content[:int(max_chars)] if max_chars else content
        return (
            f"以下は「{topic}」についてのリサーチレポートです。評価してください。\n\n"
            f"{body}"
        )

    async def _run_research(
        self,
        topic: str,
        request: ResearchRequest,
        reference_content: str = "",
        run_id: int = 0,
        session_id: str = "",
    ) -> ResearchResult:
        pm_output = await self._stream_agent_output(
            self._pm_agent,
            f"次の調査プロジェクトのWBSと品質目標を定義してください。\n\nテーマ: {topic}\n深度: {request.depth}",
            "PM",
        )
        await self._mark_wbs_done(f"r{run_id}-task-pm")

        example = '[{"name": "経済アナリスト", "expertise": "経済・金融"}]'
        team_spec = await self._stream_agent_output(
            self._team_builder,
            f"次のテーマを調査するための専門家チームを3名以内で定義してください。各専門家の名前と専門分野をJSON配列で返してください。\n\nテーマ: {topic}\n\n例: {example}",
            "TeamBuilder",
        )
        await self._mark_wbs_done(f"r{run_id}-task-team")
        await self._log("done", "専門家チームを構成しました。")

        specialists = self._parse_team_spec(team_spec, topic)
        factory = DynamicAgentFactory()

        for spec in specialists:
            factory.create_specialist(
                name=spec["name"],
                expertise=spec["expertise"],
                system_prompt=f"あなたは{spec['expertise']}の専門家です。{topic}について調査します。",
            )

        await self._push_wbs(topic, specialists, run_id=run_id)

        artifact_writer = self._make_artifact_writer(session_id)
        try:
            wbs_path = artifact_writer.write_wbs(run_id, topic, specialists)
            await self._notify(
                "CSM",
                f"📋 WBS を保存しました:\n`{wbs_path}`",
            )
        except Exception as exc:
            logger.warning("write_wbs failed: %s", exc)

        iterations_done = 0

        async def run_research(
            iteration: int,
            feedback: QualityFeedback,
            previous_content: str = "",
        ) -> str:
            new_content = await self._run_specialist_pass(
                factory,
                topic,
                feedback,
                reference_content,
                run_id=run_id,
                artifact_writer=artifact_writer,
                style=request.style,
            )
            if previous_content and new_content:
                # 前回内容を保持し、新発見を追記（ゼロトラスト蓄積）
                return (
                    previous_content
                    + f"\n\n---\n\n## 追加調査（イテレーション {iteration}）\n\n"
                    + new_content
                )
            return new_content or previous_content

        combined_content = await self._run_specialist_pass(
            factory,
            topic,
            None,
            reference_content,
            run_id=run_id,
            artifact_writer=artifact_writer,
            style=request.style,
        )

        if request.style in _STYLES_WITHOUT_EXEC_SUMMARY:
            discussion_specialists = [
                {"name": name, "expertise": ag._expertise, "research": combined_content[:3000]}
                for name, ag in factory.agents.items()
            ]
            discussion_transcript = await self._run_discussion(
                specialists=discussion_specialists,
                topic=topic,
                artifact_writer=artifact_writer,
                run_id=run_id,
            )
            await self._mark_wbs_done(f"r{run_id}-task-discussion")
            combined_content = combined_content + "\n\n---\n\n" + discussion_transcript
            format_prompt = self._build_format_prompt(topic, combined_content, request.style)
            formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
            if formatted:
                combined_content = formatted
        else:
            summary_prompt = self._build_summary_prompt(topic, combined_content)
            exec_summary = await self._stream_agent_output(self._csm, summary_prompt, "CSM")
            if exec_summary:
                combined_content = (
                    f"## エグゼクティブサマリー\n\n{exec_summary}\n\n---\n\n{combined_content}"
                )

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
            deterministic = self._evaluate_content(content, request.depth)
            if not deterministic.passed:
                return deterministic
            audit = await self._run_audit(content, topic)
            if artifact_writer:
                try:
                    artifact_writer.write_review(run_id, iterations_done, audit)
                except Exception as exc:
                    logger.warning("write_review failed: %s", exc)
            if audit.get("decision") == "REVISE":
                revisions = audit.get("required_revisions", [])
                await self._set_agent_status("PM", "meeting")
                await self._log("running", f"PM: 品質改善会議を開催しています（イテレーション{iterations_done}）")
                improvements_text = "\n".join(f"- {r}" for r in revisions) if revisions else "改善点なし"
                await self._notify("PM", f"レビュー結果に基づき、以下の改善を指示します:\n{improvements_text}")
                if artifact_writer:
                    try:
                        artifact_writer.write_minutes(run_id, iterations_done, topic, revisions)
                    except Exception as exc:
                        logger.warning("write_minutes failed: %s", exc)
                await self._set_agent_status("PM", "done")
                return QualityFeedback(
                    passed=False,
                    score=float(audit.get("overall_score", 0.5)),
                    improvements=revisions,
                )
            return QualityFeedback(passed=True, score=float(audit.get("overall_score", 1.0)))

        self._quality_loop = QualityLoop(evaluator=evaluate)

        final_feedback = await self._quality_loop.run(
            initial_content=combined_content,
            on_iteration=run_research,
        )

        output_path = MarkdownOutput(self._get_agent_workspace()).save(
            combined_content, topic, report_type=request.style
        )
        await self._mark_wbs_done(f"r{run_id}-task-quality")
        await self._mark_wbs_done(f"r{run_id}-task-output")

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
        run_id: int = 0,
        artifact_writer: ArtifactWriter | None = None,
        style: str = "research_report",
    ) -> str:
        sections: list[str] = []
        for i, (name, agent) in enumerate(factory.agents.items()):
            task_message = _build_research_task(topic, feedback, name, reference_content, style=style)
            section = await self._stream_agent_output(
                agent,
                task_message,
                name,
                artifact_writer=artifact_writer,
                run_id=run_id,
            )
            if section:
                sections.append(f"## {name}\n\n{section}")
            await self._mark_wbs_done(f"r{run_id}-task-specialist-{i}")
            if section and artifact_writer:
                try:
                    draft_path = artifact_writer.write_specialist_draft(run_id, name, section)
                    await self._notify(
                        "CSM",
                        f"📄 {name} の調査結果を保存しました:\n`{draft_path}`",
                    )
                except Exception as exc:
                    logger.warning("write_specialist_draft failed: %s", exc)
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
        issues: list[str] = []

        min_length = {"quick": 300, "standard": 800, "deep": 2000}.get(depth, 800)
        if len(content) < min_length:
            issues.append(f"内容が不十分です（{len(content)}文字 / 目標{min_length}文字）")

        if issues:
            return QualityFeedback(
                passed=False,
                score=max(0.1, 1.0 - len(issues) * 0.2),
                improvements=issues,
            )
        return QualityFeedback(passed=True, score=1.0)

    async def _run_audit(self, content: str, topic: str) -> dict:
        audit_prompt = self._build_audit_prompt(topic, content)
        await self._set_agent_status("Auditor", "reviewing")
        raw = await self._stream_agent_output(self._auditor, audit_prompt, "Auditor")
        await self._set_agent_status("Auditor", "done")
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"decision": "APPROVE", "overall_score": 0.7}

    async def run_interactive(
        self,
        depth: str = "standard",
        output_format: str = "markdown",
    ) -> None:
        session = SessionState()

        if not self._ui:
            topic = input("テーマを入力してください: ")
            request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
            session_id = self._make_session_id(topic)
            await self.run(request, run_id=0, session_id=session_id)
            return

        while True:
            await self._ui.append_agent_message(
                "CSM",
                "こんにちは！リサーチするテーマを入力してください。"
                if session.run_count == 0
                else "次のテーマまたは追加依頼を入力してください。終了する場合は「終了」と入力してください。",
            )
            topic = await self._ui.wait_for_user_message()
            await self._log("running", f"テーマ: {topic}")

            if _is_negative(topic):
                await self._ui.append_agent_message("CSM", "ありがとうございました。調査を終了します。")
                break

            while True:
                await self._ui.append_agent_message("CSM", _format_topic_confirmation(topic, depth))
                answer = await self._ui.wait_for_user_message()
                if _is_affirmative(answer):
                    break
                if _is_negative(answer):
                    topic = None
                    break
                topic = answer

            if topic is None:
                await self._ui.append_agent_message("CSM", "承知しました。調査を終了します。")
                break

            style_menu = "\n".join(f"{k}: {v[1]}" for k, v in _STYLE_OPTIONS.items())
            await self._ui.append_agent_message(
                "CSM",
                f"レポートのスタイルを選択してください:\n{style_menu}\n\n番号を入力してください（デフォルト: 1）",
            )
            style_input = await self._ui.wait_for_user_message()
            style = _STYLE_OPTIONS.get(style_input.strip(), _STYLE_OPTIONS["1"])[0]

            session.run_count += 1
            run_id = session.run_count
            if not session.session_id:
                session.session_id = self._make_session_id(topic)
            request = ResearchRequest(topic=topic, depth=depth, output_format=output_format, style=style)
            try:
                result = await self.run(request, run_id=run_id, session_id=session.session_id)
                session.current_topic = topic
                session.last_report_path = result.output_path
                await self._log("done", f"完了: {result.output_path}")
            except Exception as exc:
                err_msg = f"エラーが発生しました: {exc}"
                tb = traceback.format_exc()
                logger.error("run_interactive error:\n%s", tb)
                await self._notify("System", err_msg)
                await self._log("running", err_msg)
                await self._ui.append_log("running", tb)
                raise

    @staticmethod
    def _make_session_id(topic: str) -> str:
        """セッション識別子を生成する: YYYYMMDD_HHMMSS_{sanitized_topic}"""
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "_", topic)[:20]
        return f"{time_str}_{slug}"

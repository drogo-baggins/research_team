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
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from research_team.orchestrator.book_pipeline import BookOutline

logger = logging.getLogger(__name__)

from research_team.output.run_progress import RunProgress, SpecialistProgress
from research_team.ui.control_ui import MODE_MODIFY_SENTINEL
from research_team.agents.csm import ClientSuccessManager
from research_team.agents.auditor import Auditor
from research_team.agents.modify_agent import ModifyAgent
from research_team.agents.dynamic.factory import DynamicAgentFactory
from research_team.agents.pm import ProjectManager as PMAgent
from research_team.agents.team_builder import TeamBuilder
from research_team.project.manager import ProjectManager as ProjectFileManager
from research_team.orchestrator.quality_loop import QualityFeedback, QualityLoop
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas
from research_team.orchestrator.document_editor import DocumentEditorAgent, edit_document
from research_team.output.artifact_writer import ArtifactWriter
from research_team.output.markdown import MarkdownOutput
from research_team.output.pdf import PDFOutput
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
    locales: list[str] = field(default_factory=lambda: ["ja", "en"])


@dataclass
class ResearchResult:
    content: str
    output_path: str
    quality_score: float
    iterations: int


@dataclass
class RegenerateRequest:
    """既存 run のアーティファクトを再利用してレポートを再生成する。"""

    run_id: int
    artifacts_dir: str  # manifest_run{N}.json の親ディレクトリ
    re_research_specialists: list[str]  # 再調査対象のスペシャリスト名（空=整形のみ）
    style: str | None = None  # None = manifest の style を引き継ぐ
    overwrite_report: bool = True


@dataclass
class CompletedSession:
    """完了済みセッションのメタデータ。"""

    session_id: str
    topic: str
    run_id: int
    style: str
    created_at: str
    artifacts_dir: Path
    manifest_path: Path
    report_path: str = ""
    project_id: str | None = None
    project_topic: str | None = None


@dataclass
class SessionState:
    current_topic: str = ""
    last_report_path: str = ""
    last_run_id: int = 0
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
        "本文中のインライン引用（例: ([タイトル](URL))）は削除せずそのまま残してください。"
        "末尾に「## Sources」セクションを設け、使用した出典URLを箇条書きでリストアップしてください。"
    ),
    "book_chapter": (
        "書籍の一章として記述してください。"
        "章タイトル・節タイトルを設け、詳細かつ叙述的に展開してください。"
        "導入・本論・まとめの構成を守り、読者が通読できる完成した章にしてください。"
    ),
}

_STYLES_WITHOUT_EXEC_SUMMARY = {"book_chapter", "magazine_column"}

_REGEN_KEYWORDS = [
    "変えて",
    "修正して",
    "直して",
    "書き直して",
    "形式に",
    "スタイルを",
    "再整形",
    "深掘り",
    "このレポート",
    "前のレポート",
    "さっきのレポート",
    "このセクション",
    "この節",
    "もっと詳しく",
]


def _parse_regenerate_intent(text: str, last_run_id: int) -> RegenerateRequest | None:
    """
    ユーザー入力が既存レポートへの修正依頼かどうかを判定する。
    修正依頼なら RegenerateRequest を返し、新規テーマなら None を返す。
    """
    normalized = text.strip()
    if last_run_id == 0:
        return None
    if any(kw in normalized for kw in _REGEN_KEYWORDS):
        return RegenerateRequest(
            run_id=last_run_id,
            artifacts_dir="",  # 呼び出し側で設定
            re_research_specialists=[],
        )
    return None


class ResearchCancelledError(Exception):
    pass


class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm_agent = PMAgent()
        self._auditor = Auditor()
        self._modify_agent = ModifyAgent()
        self._doc_editor = DocumentEditorAgent()
        self._project_manager = ProjectFileManager(workspace_dir=self._workspace_dir)
        self._team_builder = TeamBuilder()
        self._search_engine = SearchEngineFactory.create(control_ui=ui)
        self._quality_loop = QualityLoop()
        self._search_server: SearchServer | None = None
        self._search_port: int = 0
        self._session_artifacts_dir: str | None = None

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

    def _build_wbs_milestones(
        self,
        topic: str,
        specialists: list[dict],
        run_id: int = 0,
        style: str = "",
        book_outline: "BookOutline | None" = None,
    ) -> list[dict]:
        output_tasks = [
            {"id": f"r{run_id}-task-quality", "title": "品質評価・改善ループ", "assignee": "QualityLoop", "done": False},
            {"id": f"r{run_id}-task-output", "title": "Markdown出力", "assignee": "System", "done": False},
        ]
        if style in _STYLES_WITHOUT_EXEC_SUMMARY:
            output_tasks.insert(0, {
                "id": f"r{run_id}-task-discussion",
                "title": "スペシャリスト対談",
                "assignee": "Discussion",
                "done": False,
            })
        milestones: list[dict] = [
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
        ]
        if style == "book_chapter":
            if book_outline is not None:
                sections = book_outline.all_sections()
                writing_tasks = [
                    {
                        "id": f"r{run_id}-section-{sec.section_id}",
                        "title": f"{sec.chapter_title} ＞ {sec.section_title}",
                        "assignee": sec.specialist_hint or "Specialist",
                        "done": False,
                    }
                    for sec in sections
                ]
            else:
                writing_tasks = [
                    {
                        "id": f"r{run_id}-task-writing-pending",
                        "title": "セクション分解中…",
                        "assignee": "PM",
                        "done": False,
                    }
                ]
            milestones.append({
                "id": f"r{run_id}-milestone-writing",
                "title": "書籍執筆フェーズ",
                "tasks": writing_tasks,
            })
        milestones.append({
            "id": f"r{run_id}-milestone-output",
            "title": "出力フェーズ",
            "tasks": output_tasks,
        })
        return milestones

    async def _push_wbs(self, topic: str, specialists: list[dict], run_id: int = 0, style: str = "") -> None:
        if not self._ui or not hasattr(self._ui, "set_wbs"):
            return
        milestones = self._build_wbs_milestones(topic, specialists, run_id=run_id, style=style)
        try:
            await self._ui.set_wbs(milestones)
        except Exception as exc:
            logger.warning("_push_wbs failed: %s", exc)

    async def _push_book_writing_milestone(
        self,
        topic: str,
        specialists: list[dict],
        outline: "BookOutline",
        run_id: int,
        style: str,
    ) -> None:
        if not self._ui or not hasattr(self._ui, "set_wbs"):
            return
        milestones = self._build_wbs_milestones(
            topic, specialists, run_id=run_id, style=style, book_outline=outline
        )
        try:
            await self._ui.set_wbs(milestones)
        except Exception as exc:
            logger.warning("_push_book_writing_milestone failed: %s", exc)

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
            async with asyncio.timeout(timeout_sec) as _timeout_cm:
                if self._ui is not None:
                    _loop = asyncio.get_running_loop()
                    _saved_remaining: list[float] = []

                    def _pause_timeout() -> None:
                        when = _timeout_cm.when()
                        if when is not None:
                            _saved_remaining.clear()
                            _saved_remaining.append(max(0.0, when - _loop.time()))
                            _timeout_cm.reschedule(None)

                    def _resume_timeout() -> None:
                        if _saved_remaining:
                            _timeout_cm.reschedule(_loop.time() + _saved_remaining.pop())

                    self._ui.set_approval_hooks(_pause_timeout, _resume_timeout)
                try:
                    async for event in agent.run(
                        message,
                        workspace_dir=self._session_artifacts_dir or self._get_agent_workspace(),
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
                                    logger.debug(
                                        "tool_execution_end raw event.data keys=%s data=%s",
                                        list(event.data.keys()),
                                        event.data,
                                    )
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
                finally:
                    if self._ui is not None:
                        self._ui.set_approval_hooks(None, None)
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

    async def run_research(self, request: ResearchRequest, run_id: int = 0, session_id: str = "") -> ResearchResult:
        return await self.run(request, run_id=run_id, session_id=session_id)


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

    @staticmethod
    def _strip_chapter_prefix(title: str) -> str:
        import re as _re
        return _re.sub(r"^第\d+章[\s\u3000]*", "", title).strip()

    @staticmethod
    def _strip_section_preamble(content: str) -> str:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("#"):
                return "\n".join(lines[i:])
        return content

    @staticmethod
    def _strip_section_suffix(content: str) -> str:
        _EDITORIAL_MARKERS = [
            "\n## 執筆完了",
            "\n## 実装内容",
            "\n## 完了",
            "\n**字数：",
            "\n**実装内容：",
            "\n**執筆内容：",
            "\n---\n\n執筆しました",
            "\n---\n\n以上、",
            "\n以上で",
            "\n執筆いたしました",
            "\n執筆しました",
        ]
        for marker in _EDITORIAL_MARKERS:
            idx = content.find(marker)
            if idx != -1:
                content = content[:idx].rstrip()
        return content

    def _assemble_book_from_outline(
        self,
        outline: "BookOutline",
        section_paths: dict[str, dict],
        discussion_artifact_path: str | None = None,
        topic: str = "",
    ) -> str:
        from pathlib import Path as _Path

        title_line = f"# {topic.split(chr(10))[0].strip()}\n\n" if topic else ""

        toc_lines = ["## 目次", ""]
        for ch in outline.chapters:
            ch_idx = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            toc_lines.append(f"**第{ch_idx}章　{ch_title}**")
            for sec in ch.get("sections", []):
                sec_idx = sec["section_index"]
                sec_title = sec["section_title"]
                toc_lines.append(f"　　第{ch_idx}.{sec_idx}節　{sec_title}")
            toc_lines.append("")

        chapter_parts: list[str] = []
        for ch in outline.chapters:
            ch_idx = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            ch_lines: list[str] = [f"## 第{ch_idx}章　{ch_title}", ""]
            for sec in ch.get("sections", []):
                sec_idx = sec["section_index"]
                section_id = f"ch{ch_idx:02d}_sec{sec_idx:02d}"
                entry = section_paths.get(section_id, {})
                artifact_path = entry.get("artifact_path", "")
                content = ""
                if artifact_path:
                    try:
                        raw = _Path(artifact_path).read_text(encoding="utf-8")
                        sep_idx = raw.find("---\n\n")
                        content = raw[sep_idx + 5:].strip() if sep_idx != -1 else raw.strip()
                        content = self._strip_section_preamble(content)
                        content = self._strip_section_suffix(content)
                    except Exception as exc:
                        logger.warning("_assemble_book: failed to read %s: %s", artifact_path, exc)
                if content:
                    ch_lines.append(content)
                    ch_lines.append("")
            chapter_parts.append("\n".join(ch_lines))

        toc = "\n".join(toc_lines)
        body = "\n\n".join(chapter_parts)
        result = f"{title_line}{toc}\n\n---\n\n{body}"

        if discussion_artifact_path:
            try:
                disc = _Path(discussion_artifact_path).read_text(encoding="utf-8").strip()
                result += f"\n\n---\n\n{disc}"
            except Exception as exc:
                logger.warning("_assemble_book: failed to read discussion: %s", exc)

        return result

    def _build_format_prompt(self, topic: str, content: str, style: str, modification_text: str = "") -> str:
        max_chars = os.environ.get("RT_MAX_SUMMARY_CHARS")
        body = content[:int(max_chars)] if max_chars else content
        style_instruction = _STYLE_INSTRUCTIONS.get(style, "")
        modification_section = (
            f"【修正指示】以下の点を修正してください：{modification_text}\n"
            if modification_text
            else ""
        )
        return (
            f"以下は「{topic}」についての専門家調査結果（生データ）です。\n\n"
            f"{body}\n\n"
            f"上記の調査データを元に、完成した読み物として整形してください。\n"
            f"{modification_section}"
            f"【形式指示】{style_instruction}\n"
            f"【引用・出典の保持（必須）】本文中のインライン引用（例: ([タイトル](URL))）は"
            f"削除せずそのまま残してください。"
            f"調査データ内の「## Sources」「## 参考文献」セクションに含まれる出典URLは、"
            f"整形後も「## Sources」セクションとして末尾に必ず含めてください。\n"
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
        resume_from: RunProgress | None = None,
        resume_writer: "ArtifactWriter | None" = None,
    ) -> ResearchResult:
        preliminary_writer = resume_writer or self._make_artifact_writer(session_id)
        self._session_artifacts_dir = str(preliminary_writer._dir)
        try:
            return await self._run_research_inner(
                topic=topic,
                request=request,
                reference_content=reference_content,
                run_id=run_id,
                session_id=session_id,
                resume_from=resume_from,
                resume_writer=preliminary_writer,
            )
        finally:
            self._session_artifacts_dir = None

    async def _run_research_inner(
        self,
        topic: str,
        request: ResearchRequest,
        reference_content: str = "",
        run_id: int = 0,
        session_id: str = "",
        resume_from: RunProgress | None = None,
        resume_writer: "ArtifactWriter | None" = None,
    ) -> ResearchResult:
        if resume_from:
            specialists = [
                {"name": sp.name, "expertise": sp.expertise}
                for sp in resume_from.all_specialists
            ]
            factory = DynamicAgentFactory()
            for spec in specialists:
                factory.create_specialist(
                    name=spec["name"],
                    expertise=spec["expertise"],
                    system_prompt=f"あなたは{spec['expertise']}の専門家です。{topic}について調査します。",
                    locales=request.locales,
                )
            await self._push_wbs(topic, specialists, run_id=run_id, style=request.style)
            artifact_writer: ArtifactWriter = resume_writer  # type: ignore[assignment]
            progress = resume_from
        else:
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
                    locales=request.locales,
                )

            await self._push_wbs(topic, specialists, run_id=run_id, style=request.style)

            if not await self._wbs_approval_loop(
                pm_output=pm_output,
                specialists=specialists,
                request=request,
                topic=topic,
                run_id=run_id,
            ):
                raise ResearchCancelledError

            artifact_writer = resume_writer  # type: ignore[assignment]
            try:
                wbs_path = artifact_writer.write_wbs(run_id, topic, specialists)
                await self._notify(
                    "CSM",
                    f"📋 WBS を保存しました:\n`{wbs_path}`",
                )
            except Exception as exc:
                logger.warning("write_wbs failed: %s", exc)
                wbs_path = ""

            progress = RunProgress(
                run_id=run_id,
                topic=topic,
                style=request.style,
                depth=request.depth,
                locales=request.locales,
                all_specialists=[
                    SpecialistProgress(name=s["name"], expertise=s["expertise"])
                    for s in specialists
                ],
                wbs_artifact_path=wbs_path,
                created_at=datetime.now().isoformat(),
            )
            try:
                artifact_writer.write_run_progress(progress)
            except Exception as exc:
                logger.warning("write_run_progress failed: %s", exc)

        pre_completed: dict[str, str] = {}
        if resume_from:
            for sp in resume_from.completed_specialists:
                if sp.artifact_path:
                    try:
                        pre_completed[sp.name] = Path(sp.artifact_path).read_text(encoding="utf-8")
                    except Exception:
                        pre_completed[sp.name] = ""
                else:
                    pre_completed[sp.name] = ""

        def _on_specialist_done(name: str, draft_path: str) -> None:
            progress.mark_specialist_done(name, draft_path)
            try:
                artifact_writer.write_run_progress(progress)
            except Exception as exc:
                logger.warning("write_run_progress failed: %s", exc)

        iterations_done = 0

        async def run_research(
            iteration: int,
            feedback: QualityFeedback,
            previous_content: str = "",
        ) -> str:
            nonlocal specialist_artifact_paths
            specialist_result = await self._run_specialist_pass(
                factory,
                topic,
                feedback,
                reference_content,
                run_id=run_id,
                artifact_writer=artifact_writer,
                style=request.style,
            )
            if isinstance(specialist_result, tuple):
                new_content, specialist_artifact_paths = specialist_result
            else:
                new_content = specialist_result
                specialist_artifact_paths = {}
            if previous_content and new_content:
                # 前回内容を保持し、新発見を追記（ゼロトラスト蓄積）
                return (
                    previous_content
                    + f"\n\n---\n\n## 追加調査（イテレーション {iteration}）\n\n"
                    + new_content
                )
            return new_content or previous_content

        specialist_result = await self._run_specialist_pass(
            factory,
            topic,
            None,
            reference_content,
            run_id=run_id,
            artifact_writer=artifact_writer,
            style=request.style,
            pre_completed=pre_completed,
            on_specialist_done=_on_specialist_done,
        )
        if isinstance(specialist_result, tuple):
            combined_content, specialist_artifact_paths = specialist_result
        else:
            combined_content = specialist_result
            specialist_artifact_paths = {}
        discussion_artifact_path: str | None = None
        book_section_paths: dict[str, dict] = {}
        book_outline: "BookOutline | None" = None

        if request.style == "book_chapter":
            from research_team.orchestrator.book_pipeline import BookChapterPipeline
            outline = await self._decompose_book_sections(topic, combined_content, request.depth)
            if outline and outline.all_sections():
                book_outline = outline
                await self._notify("CSM", f"📚 セクション構造を設計しました（{len(outline.all_sections())}節）")
                await self._push_book_writing_milestone(
                    topic=topic,
                    specialists=specialists,
                    outline=outline,
                    run_id=run_id,
                    style=request.style,
                )
                pipeline = BookChapterPipeline(
                    stream_fn=self._stream_agent_output,
                    specialists=specialists,
                )
                book_content, book_section_paths = await pipeline.run(
                    topic=topic,
                    outline=outline,
                    raw_data=combined_content,
                    agents=factory.agents,
                    artifact_writer=artifact_writer,
                    run_id=run_id,
                    notify_fn=self._notify,
                    mark_done_fn=lambda sid: self._mark_wbs_done(f"r{run_id}-section-{sid}"),
                )
                if book_content:
                    combined_content = book_content
            else:
                logger.warning("book_chapter: outline decomposition failed, falling back to standard flow")
                await self._notify("CSM", "⚠️ セクション分解に失敗しました。標準フローで続行します。")

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
            if artifact_writer:
                try:
                    discussion_candidates = sorted(
                        artifact_writer._dir.glob(f"discussion_run{run_id}_*.md"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if discussion_candidates:
                        discussion_artifact_path = str(discussion_candidates[0])
                except Exception as exc:
                    logger.warning("resolve discussion_artifact_path failed: %s", exc)
            await self._mark_wbs_done(f"r{run_id}-task-discussion")
            combined_content = combined_content + "\n\n---\n\n" + discussion_transcript

        if request.style == "book_chapter" and book_outline:
            combined_content = self._assemble_book_from_outline(
                outline=book_outline,
                section_paths=book_section_paths,
                discussion_artifact_path=discussion_artifact_path,
                topic=topic,
            )
        elif request.style == "magazine_column":
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

        _DISCUSSION_MARKER = "\n\n---\n\n# 対談トランスクリプト"
        _discussion_suffix = ""
        _edit_body = combined_content
        if request.style == "book_chapter":
            disc_idx = combined_content.rfind(_DISCUSSION_MARKER)
            if disc_idx != -1:
                _discussion_suffix = combined_content[disc_idx:]
                _edit_body = combined_content[:disc_idx]

        combined_content = await edit_document(
            self._stream_agent_output,
            self._doc_editor,
            topic,
            _edit_body,
            request.style,
        )

        if _discussion_suffix:
            combined_content += _discussion_suffix

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
            deterministic = self._evaluate_content(content, request.depth, style=request.style)
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

        output_path = MarkdownOutput(str(artifact_writer._dir.parent)).save(
            combined_content, topic, report_type=request.style
        )
        try:
            await PDFOutput(str(artifact_writer._dir.parent)).save_async(combined_content, output_path)
        except Exception as exc:
            logger.warning("PDF output failed: %s", exc)
        try:
            artifact_writer.write_run_manifest(
                run_id=run_id,
                topic=topic,
                style=request.style,
                specialists=specialists,
                artifact_paths=specialist_artifact_paths,
                discussion_artifact_path=discussion_artifact_path,
                report_path=output_path,
                book_section_paths=book_section_paths,
            )
        except Exception as exc:
            logger.warning("write_run_manifest failed: %s", exc)
        await self._mark_wbs_done(f"r{run_id}-task-quality")
        await self._mark_wbs_done(f"r{run_id}-task-output")

        try:
            artifact_writer.clear_run_progress()
        except Exception as exc:
            logger.warning("clear_run_progress failed: %s", exc)

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

    async def _run_regenerate(
        self,
        request: RegenerateRequest,
        regen_request_text: str,
        session_id: str,
    ) -> ResearchResult:
        from research_team.output.run_manifest import RunManifest
        from research_team.output.artifact_reconstructor import ArtifactReconstructor

        manifest_path = Path(request.artifacts_dir) / f"manifest_run{request.run_id}.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"RunManifest が見つかりません: {manifest_path}")

        self._session_artifacts_dir = request.artifacts_dir
        try:
            return await self._run_regenerate_inner(request, regen_request_text, session_id)
        finally:
            self._session_artifacts_dir = None

    async def _run_regenerate_inner(
        self,
        request: RegenerateRequest,
        regen_request_text: str,
        session_id: str,
    ) -> ResearchResult:
        from research_team.output.run_manifest import RunManifest
        from research_team.output.artifact_reconstructor import ArtifactReconstructor

        manifest_path = Path(request.artifacts_dir) / f"manifest_run{request.run_id}.json"

        manifest = RunManifest.load(manifest_path)
        style = request.style or manifest.style
        topic = manifest.topic

        # 再調査対象スペシャリストの artifact を更新（現実装では空リスト = 整形のみ）
        if request.re_research_specialists:
            # フェーズ2: スペシャリスト再調査（現在は未実装、空リストで到達しない）
            logger.warning("re_research_specialists is not yet implemented; skipping re-research")

        # combined_content を再構成
        reconstructor = ArtifactReconstructor()
        combined_content = reconstructor.reconstruct(manifest)

        # CSM 整形
        if style in _STYLES_WITHOUT_EXEC_SUMMARY:
            format_prompt = self._build_format_prompt(topic, combined_content, style, regen_request_text)
            formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
            if formatted:
                combined_content = formatted
        else:
            summary_prompt = self._build_summary_prompt(topic, combined_content)
            exec_summary = await self._stream_agent_output(self._csm, summary_prompt, "CSM")
            if exec_summary:
                combined_content = f"## エグゼクティブサマリー\n\n{exec_summary}\n\n---\n\n{combined_content}"

        # 上書き or 新規保存
        output_path_arg = Path(manifest.report_path) if request.overwrite_report else None
        session_dir = str(Path(request.artifacts_dir).parent)
        output_path = MarkdownOutput(session_dir).save(
            combined_content,
            topic,
            report_type=style,
            output_path=output_path_arg,
        )
        try:
            await PDFOutput(session_dir).save_async(combined_content, output_path)
        except Exception as exc:
            logger.warning("PDF output failed: %s", exc)

        return ResearchResult(
            content=combined_content,
            output_path=output_path,
            quality_score=1.0,
            iterations=0,
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
        pre_completed: dict[str, str] | None = None,
        on_specialist_done: "Callable[[str, str], None] | None" = None,
    ) -> tuple[str, dict[str, str]]:
        sections: list[str] = []
        artifact_paths: dict[str, str] = {}
        for i, (name, agent) in enumerate(factory.agents.items()):
            if pre_completed and name in pre_completed:
                section = pre_completed[name]
                if section:
                    sections.append(f"## {name}\n\n{section}")
                await self._mark_wbs_done(f"r{run_id}-task-specialist-{i}")
                continue

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
                    artifact_paths[name] = draft_path
                    await self._notify(
                        "CSM",
                        f"📄 {name} の調査結果を保存しました:\n`{draft_path}`",
                    )
                    if on_specialist_done is not None:
                        on_specialist_done(name, draft_path)
                except Exception as exc:
                    logger.warning("write_specialist_draft failed: %s", exc)
        return "\n\n".join(sections), artifact_paths

    async def _decompose_book_sections(
        self,
        topic: str,
        raw_content: str,
        depth: str = "standard",
    ) -> "BookOutline | None":
        """PMにセクション分解を依頼し、BookOutlineを返す。失敗時はNone。"""
        from research_team.orchestrator.book_pipeline import parse_outline_from_pm_output
        chapter_count = {"quick": 2, "standard": 3, "deep": 5}.get(depth, 3)
        prompt = (
            f"テーマ「{topic}」の書籍を執筆します。\n"
            f"以下の調査データをもとに、{chapter_count}章構成で章・節構造を設計してください。\n"
            f"各章には3〜5節を設けてください。\n\n"
            f"【調査データ】\n{raw_content[:20000]}\n\n"
            f"必ず以下のJSON形式のみを出力してください。説明文・前置きは一切含めないでください。\n"
            f"```json\n"
            f"[\n"
            f"  {{\n"
            f"    \"chapter_index\": 1,\n"
            f"    \"chapter_title\": \"第1章 タイトル\",\n"
            f"    \"sections\": [\n"
            f"      {{\n"
            f"        \"section_index\": 1,\n"
            f"        \"section_title\": \"1-1 節タイトル\",\n"
            f"        \"key_points\": [\"論点A\", \"論点B\", \"論点C\"],\n"
            f"        \"specialist_hint\": \"この節に最適な専門分野\"\n"
            f"      }}\n"
            f"    ]\n"
            f"  }}\n"
            f"]\n"
            f"```"
        )
        raw = await self._stream_agent_output(self._pm_agent, prompt, "PM (セクション分解)")
        return parse_outline_from_pm_output(raw)

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

    def _evaluate_content(self, content: str, depth: str, style: str = "") -> QualityFeedback:
        issues: list[str] = []
        if style == "book_chapter":
            min_length = {"quick": 3000, "standard": 8000, "deep": 15000}.get(depth, 8000)
        else:
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

    async def _wbs_approval_loop(
        self,
        pm_output: str,
        specialists: list[dict],
        request: ResearchRequest,
        topic: str,
        run_id: int,
        max_revisions: int = 5,
    ) -> bool:
        if not self._ui or not hasattr(self._ui, "show_wbs_approval"):
            return True

        await self._notify("PM", "WBSを作成しました。右パネルで内容を確認し、調査深度・出力スタイルを選択してください。")

        for _ in range(max_revisions):
            result = await self._ui.show_wbs_approval(
                depth=request.depth,
                style=request.style,
                locales=request.locales,
            )

            if result is None:
                return False

            if result.get("approved"):
                request.depth = result["depth"]
                request.style = result["style"]
                request.locales = result.get("locales", request.locales)
                set_locales = getattr(self._search_engine, "set_preferred_locales", None)
                if callable(set_locales):
                    set_locales(request.locales)
                return True

            feedback_text = result.get("feedback", "")
            if feedback_text:
                revision_prompt = (
                    f"ユーザーの修正依頼:\n{feedback_text}\n\n"
                    f"テーマ: {topic}\n"
                    f"現在のWBS:\n{pm_output}\n\n"
                    f"改善されたWBSと品質目標を提示してください。"
                )
                pm_output = await self._stream_agent_output(self._pm_agent, revision_prompt, "PM")
                await self._push_wbs(topic, specialists, run_id=run_id, style=request.style)

        return True

    async def run_interactive(
        self,
        depth: str = "standard",
        output_format: str = "markdown",
    ) -> None:
        session = SessionState()

        if self._ui and hasattr(self._ui, "set_mode_change_callback"):
            self._ui.set_mode_change_callback(self._on_mode_change)

        if not self._ui:
            topic = input("テーマを入力してください: ")
            request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
            session_id = self._make_session_id(topic)
            await self.run(request, run_id=0, session_id=session_id)
            return

        resume_data = self._detect_resumable_session()
        if resume_data:
            resume_progress, resume_writer = resume_data
            completed_names = [s.name for s in resume_progress.completed_specialists]
            pending_names = [s.name for s in resume_progress.pending_specialists]
            status_lines = [""]
            for sp in resume_progress.all_specialists:
                mark = "✅" if sp.completed else "❌"
                status_lines.append(f"  {mark} {sp.name}（{sp.expertise}）")
            status_lines.append("")
            resume_prompt = (
                f"前回の「{resume_progress.topic}」の調査が未完了です。\n"
                f"\n進捗：{''.join(status_lines)}\n"
                f"続きから再開しますか？（「はい」で再開 / 「いいえ」で最初から）"
            )
            await self._ui.append_agent_message("CSM", resume_prompt)
            user_answer = await self._ui.wait_for_user_message()
            if _is_affirmative(user_answer):
                session.session_id = resume_writer._dir.parent.name
                session.run_count += 1
                run_id = resume_progress.run_id
                request = ResearchRequest(
                    topic=resume_progress.topic,
                    depth=resume_progress.depth,
                    output_format=output_format,
                    style=resume_progress.style,
                    locales=resume_progress.locales,
                )
                await self._start_search_server()
                try:
                    result = await self._run_research(
                        resume_progress.topic,
                        request,
                        reference_content="",
                        run_id=run_id,
                        session_id=session.session_id,
                        resume_from=resume_progress,
                        resume_writer=resume_writer,
                    )
                    session.current_topic = resume_progress.topic
                    session.last_report_path = result.output_path
                    session.last_run_id = run_id
                    await self._log("done", f"完了: {result.output_path}")
                except ResearchCancelledError:
                    await self._ui.append_agent_message("CSM", "承知しました。調査をキャンセルしました。")
                except Exception as exc:
                    err_msg = f"エラーが発生しました: {exc}"
                    tb = traceback.format_exc()
                    logger.error("run_interactive (resume) error:\n%s", tb)
                    await self._notify("System", err_msg)
                    await self._log("running", err_msg)
                    await self._ui.append_log("running", tb)
                    raise
                finally:
                    await self._stop_search_server()
            else:
                resume_writer.clear_run_progress()
                await self._notify("CSM", "前回の進捗を破棄しました。新規調査を開始します。")

        while True:
            mode = getattr(self._ui, "get_current_mode", lambda: "new_request")() if self._ui else "new_request"
            if mode == "modify":
                await self._run_modify_session(session, output_format)
                continue

            if session.run_count == 0:
                await self._ui.append_agent_message(
                    "CSM",
                    "調査テーマを入力してください。",
                )
            else:
                await self._ui.append_agent_message(
                    "CSM",
                    "次のテーマまたは追加依頼を入力してください。終了する場合は「終了」と入力してください。",
                )
            topic = await self._ui.wait_for_user_message()
            await self._log("running", f"テーマ: {topic}")

            if topic == MODE_MODIFY_SENTINEL:
                continue

            if _is_negative(topic):
                await self._ui.append_agent_message("CSM", "ありがとうございました。調査を終了します。")
                break

            # 再生成意図の判定（既存runの整形・再生成）
            regen = _parse_regenerate_intent(topic, last_run_id=session.last_run_id)
            if regen is not None:
                if not session.session_id:
                    session.session_id = self._make_session_id(topic)
                artifact_writer = self._make_artifact_writer(session.session_id)
                regen.artifacts_dir = str(artifact_writer._dir)
                try:
                    result = await self._run_regenerate(regen, topic, session.session_id)
                    session.last_report_path = result.output_path
                    await self._notify("CSM", f"✅ レポートを更新しました:\n`{result.output_path}`")
                    await self._log("done", f"再生成完了: {result.output_path}")
                    continue
                except FileNotFoundError as exc:
                    logger.warning("Manifest not found for regenerate: %s", exc)
                    await self._notify("CSM", "⚠️ 前回の調査データが見つかりません。新規調査として実行します。")
                except Exception as exc:
                    logger.warning("Regenerate failed: %s", exc)
                    await self._notify("CSM", f"⚠️ 再生成に失敗しました: {exc}\n新規調査として実行します。")

            session.run_count += 1
            run_id = session.run_count
            if not session.session_id:
                session.session_id = self._make_session_id(topic)
            request = ResearchRequest(topic=topic, depth=depth, output_format=output_format)
            try:
                result = await self.run(request, run_id=run_id, session_id=session.session_id)
                session.current_topic = topic
                session.last_report_path = result.output_path
                session.last_run_id = run_id
                await self._log("done", f"完了: {result.output_path}")
            except ResearchCancelledError:
                await self._ui.append_agent_message("CSM", "承知しました。調査をキャンセルしました。")
            except Exception as exc:
                err_msg = f"エラーが発生しました: {exc}"
                tb = traceback.format_exc()
                logger.error("run_interactive error:\n%s", tb)
                await self._notify("System", err_msg)
                await self._log("running", err_msg)
                await self._ui.append_log("running", tb)
                raise

    async def _run_modify_session(self, session: SessionState, output_format: str) -> None:
        assert self._ui is not None
        completed = self.list_completed_sessions()
        if not completed:
            await self._notify("ModifyAgent", "修正可能な成果物が見つかりません。パネルで「新規依頼」モードに切り替えてテーマを入力してください。")
            return

        session_id = await self._ui.wait_for_session_selection()
        if session_id is None:
            await self._notify("ModifyAgent", "キャンセルしました。")
            return

        chosen = next((s for s in completed if s.session_id == session_id), None)
        if chosen is None:
            await self._notify("ModifyAgent", "選択されたセッションが見つかりません。")
            return

        topic_short = chosen.topic[:40].replace("\n", " ")
        original_content = await self._load_session_content(chosen)
        if original_content is None:
            return

        await self._notify(
            "ModifyAgent",
            f"「{topic_short}」を読み込みました。\n修正内容を詳しく入力してください。",
        )
        mod_request = await self._ui.wait_for_user_message()
        if _is_negative(mod_request):
            await self._notify("ModifyAgent", "キャンセルしました。")
            return

        modified_content = original_content
        await self._start_search_server()
        try:
            for attempt in range(3):
                await self._log("running", f"修正適用中... ({attempt + 1}/3)")
                modify_prompt = self._build_modify_prompt(chosen.topic, modified_content, mod_request)
                result = await self._stream_agent_output(self._modify_agent, modify_prompt, "ModifyAgent")
                if result:
                    modified_content = result

                audit = await self._run_audit(modified_content, chosen.topic)
                if audit.get("decision") == "APPROVE":
                    break
                if attempt < 2:
                    revisions = audit.get("required_revisions", [])
                    mod_request = mod_request + "\n\n【Auditor指摘事項】\n" + "\n".join(f"- {r}" for r in revisions)
        finally:
            await self._stop_search_server()

        output_path_arg = Path(chosen.report_path) if chosen.report_path else None
        output_path = MarkdownOutput(str(chosen.artifacts_dir.parent)).save(
            modified_content,
            chosen.topic,
            report_type=chosen.style,
            output_path=output_path_arg,
        )
        try:
            await PDFOutput(str(chosen.artifacts_dir.parent)).save_async(modified_content, output_path)
        except Exception as exc:
            logger.warning("PDF output failed in modify session: %s", exc)

        session.session_id = chosen.session_id
        session.last_report_path = output_path
        session.run_count += 1
        await self._notify("ModifyAgent", f"✅ レポートを更新しました:\n`{output_path}`")
        await self._log("done", f"変更完了: {output_path}")

    async def _load_session_content(self, chosen: "CompletedSession") -> str | None:
        from research_team.output.run_manifest import RunManifest
        from research_team.output.artifact_reconstructor import ArtifactReconstructor

        manifest_path = chosen.artifacts_dir / f"manifest_run{chosen.run_id}.json"
        if not manifest_path.exists():
            manifest_path = chosen.manifest_path
        try:
            manifest = RunManifest.load(manifest_path)
            content = ArtifactReconstructor().reconstruct(manifest)
            if content:
                return content
        except Exception as exc:
            logger.warning("ArtifactReconstructor failed (%s), falling back to report_path", exc)

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            report_path = Path(manifest_data.get("report_path", ""))
            if report_path.exists():
                return report_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Fallback report_path read failed: %s", exc)

        await self._notify("ModifyAgent", "⚠️ 成果物の読み込みに失敗しました。手動でファイルを確認してください。")
        return None

    @staticmethod
    def _build_modify_prompt(topic: str, content: str, modification_request: str) -> str:
        return (
            f"以下は「{topic}」に関する調査レポートです。\n\n"
            f"【修正依頼】\n{modification_request}\n\n"
            f"【元のレポート】\n{content[:40000]}\n\n"
            f"上記修正依頼に従い、レポート全体を修正して返してください。\n"
            f"修正後の完全なレポート本文のみを出力し、完了報告や説明文は含めないこと。"
        )

    async def _run_modify_mode(self, session: SessionState, output_format: str) -> None:
        assert self._ui is not None
        completed = self.list_completed_sessions()
        if not completed:
            await self._ui.append_agent_message("CSM", "修正可能な成果物が見つかりません。新しいテーマを入力してください。")
            return

        lines = ["修正するセッションを番号で選択してください：\n"]
        for i, s in enumerate(completed, 1):
            topic_short = s.topic[:40].replace("\n", " ")
            lines.append(f"**{i}.** [{s.created_at}] {topic_short}（{s.style}）")
        await self._ui.append_agent_message("CSM", "\n".join(lines))

        sel_input = await self._ui.wait_for_user_message()
        try:
            sel_idx = int(sel_input.strip()) - 1
            if not (0 <= sel_idx < len(completed)):
                raise ValueError
        except ValueError:
            await self._ui.append_agent_message("CSM", "無効な番号です。最初からやり直してください。")
            return

        chosen = completed[sel_idx]
        topic_short = chosen.topic[:40].replace("\n", " ")
        await self._ui.append_agent_message(
            "CSM",
            f"「{topic_short}」の成果物を選択しました。\n修正内容を入力してください。",
        )
        modification_text = await self._ui.wait_for_user_message()

        regen = RegenerateRequest(
            run_id=chosen.run_id,
            artifacts_dir=str(chosen.artifacts_dir),
            re_research_specialists=[],
            overwrite_report=True,
        )
        try:
            result = await self._run_regenerate(regen, modification_text, chosen.session_id)
            session.session_id = chosen.session_id
            session.last_report_path = result.output_path
            session.run_count += 1
            await self._notify("CSM", f"✅ レポートを更新しました:\n`{result.output_path}`")
            await self._log("done", f"再生成完了: {result.output_path}")
        except FileNotFoundError as exc:
            logger.warning("Manifest not found: %s", exc)
            await self._notify("CSM", f"⚠️ 成果物データが見つかりません: {exc}")
        except Exception as exc:
            logger.warning("Regenerate failed: %s", exc)
            await self._notify("CSM", f"⚠️ 修正に失敗しました: {exc}")

    def _detect_resumable_session(self) -> tuple[RunProgress, ArtifactWriter] | None:
        active_id = self._project_manager.get_active_id()
        if active_id:
            artifacts_dir = self._project_manager.project_files_dir(active_id) / "artifacts"
            writer = ArtifactWriter(artifacts_dir)
            progress = writer.load_run_progress()
            if progress:
                return progress, writer

        sessions_dir = Path(self._workspace_dir) / "sessions"
        if sessions_dir.exists():
            candidates = sorted(
                sessions_dir.glob("*/artifacts/run_progress.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                writer = ArtifactWriter(candidates[0].parent)
                progress = writer.load_run_progress()
                if progress:
                    return progress, writer

        return None

    def list_completed_sessions(self) -> list[CompletedSession]:
        best: dict[str, CompletedSession] = {}

        sessions_dir = Path(self._workspace_dir) / "sessions"
        if sessions_dir.exists():
            for manifest_path in sessions_dir.glob("*/artifacts/manifest_run*.json"):
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    session_id = manifest_path.parent.parent.name
                    run_id = data.get("run_id", 1)
                    existing = best.get(session_id)
                    if existing is None or run_id > existing.run_id:
                        best[session_id] = CompletedSession(
                            session_id=session_id,
                            topic=data.get("topic", ""),
                            run_id=run_id,
                            style=data.get("style", "research_report"),
                            created_at=datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            artifacts_dir=manifest_path.parent,
                            manifest_path=manifest_path,
                            report_path=data.get("report_path", ""),
                        )
                except Exception:
                    continue

        projects_dir = Path(self._workspace_dir) / "projects"
        if projects_dir.exists():
            for manifest_path in projects_dir.glob("*/files/artifacts/manifest_run*.json"):
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    project_id = manifest_path.parent.parent.parent.name
                    session_id = f"project:{project_id}"
                    run_id = data.get("run_id", 1)
                    project_topic = ""
                    try:
                        meta_path = manifest_path.parent.parent.parent / "meta.json"
                        if meta_path.exists():
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                            project_topic = meta.get("topic", "")
                    except Exception:
                        pass
                    existing = best.get(session_id)
                    if existing is None or run_id > existing.run_id:
                        best[session_id] = CompletedSession(
                            session_id=session_id,
                            topic=data.get("topic", ""),
                            run_id=run_id,
                            style=data.get("style", "research_report"),
                            created_at=datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            artifacts_dir=manifest_path.parent,
                            manifest_path=manifest_path,
                            report_path=data.get("report_path", ""),
                            project_id=project_id,
                            project_topic=project_topic,
                        )
                except Exception:
                    continue

        return sorted(best.values(), key=lambda s: s.created_at, reverse=True)

    @staticmethod
    def _make_session_id(topic: str) -> str:
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "_", topic)[:20]
        return f"{time_str}_{slug}"

    def _list_sessions_for_ui(self) -> list[dict]:
        return [
            {
                "session_id": s.session_id,
                "topic": s.topic,
                "style": s.style,
                "created_at": s.created_at,
                "report_path": s.report_path,
                "project_id": s.project_id,
                "project_topic": s.project_topic,
            }
            for s in self.list_completed_sessions()
        ]

    async def _on_mode_change(self, mode: str) -> None:
        if not self._ui or not hasattr(self._ui, "render_session_list"):
            return
        if mode == "modify":
            sessions = self._list_sessions_for_ui()
            await self._ui.render_session_list(sessions)
        else:
            await self._ui.render_session_list([])

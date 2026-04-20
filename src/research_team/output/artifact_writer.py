from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


class ArtifactWriter:
    def __init__(self, artifacts_dir: Path) -> None:
        self._dir = artifacts_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def write_wbs(self, run_id: int, topic: str, specialists: list[dict]) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        lines = [
            f"# WBS — Run {run_id} ({date_str})",
            "",
            f"**テーマ:** {topic}",
            "",
            "## 専門家チーム",
            "",
        ]
        for s in specialists:
            lines.append(f"- **{s['name']}** ({s['expertise']})")
        lines += [
            "",
            "## タスク",
            "",
            "- [ ] PM: WBS・品質目標定義",
            "- [ ] TeamBuilder: チーム編成",
        ]
        for s in specialists:
            lines.append(f"- [ ] {s['name']}: 調査実施")
        lines += [
            "- [ ] QualityLoop: 品質評価・改善",
            "- [ ] System: Markdown出力",
        ]
        path = self._dir / f"wbs_run{run_id}_{date_str}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def write_review(self, run_id: int, iteration: int, audit_result: dict) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        decision = audit_result.get("decision", "UNKNOWN")
        score = audit_result.get("overall_score", 0.0)
        revisions = audit_result.get("required_revisions", [])
        lines = [
            f"# レビュー記録 — Run {run_id} / Iteration {iteration} ({date_str})",
            "",
            f"**判定:** {decision}  ",
            f"**スコア:** {score:.2f}",
            "",
            "## 指摘事項",
            "",
        ]
        if revisions:
            for rev in revisions:
                lines.append(f"- {rev}")
        else:
            lines.append("指摘なし")
        path = self._dir / f"review_run{run_id}_iter{iteration}_{date_str}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def write_minutes(self, run_id: int, iteration: int, topic: str, feedback_improvements: list[str]) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        lines = [
            f"# 打ち合わせ議事録 — Run {run_id} / Iteration {iteration} ({date_str})",
            "",
            f"**テーマ:** {topic}  ",
            f"**参加者:** PM, Auditor, Specialists",
            "",
            "## 議題",
            "",
            "品質評価結果の確認と次イテレーションのアクションアイテム",
            "",
            "## 決定事項・アクションアイテム",
            "",
        ]
        if feedback_improvements:
            for imp in feedback_improvements:
                lines.append(f"- [ ] {imp}")
        else:
            lines.append("品質基準を満たしているため追加調査なし")
        path = self._dir / f"minutes_run{run_id}_iter{iteration}_{date_str}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def write_discussion(self, run_id: int, transcript: str) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        path = self._dir / f"discussion_run{run_id}_{date_str}.md"
        lines = [
            f"# 対談トランスクリプト — Run {run_id} ({date_str})",
            "",
            transcript,
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def write_specialist_draft(self, run_id: int, specialist_name: str, content: str) -> str:
        """スペシャリスト1名の調査結果を中間MDとして保存する。"""
        date_str = datetime.now().strftime("%Y%m%d")
        safe_name = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "_", specialist_name)
        path = self._dir / f"specialist_{safe_name}_run{run_id}_{date_str}.md"
        header = f"# 調査中間成果物 — {specialist_name} / Run {run_id} ({date_str})\n\n"
        path.write_text(header + content, encoding="utf-8")
        return str(path)

    def write_book_section(
        self,
        run_id: int,
        section_id: str,
        chapter_title: str,
        section_title: str,
        content: str,
    ) -> str:
        """書籍セクション単位の執筆結果を保存する。"""
        date_str = datetime.now().strftime("%Y%m%d")
        path = self._dir / f"book_{section_id}_run{run_id}_{date_str}.md"
        header = (
            f"# 書籍セクション — {section_id} / Run {run_id} ({date_str})\n\n"
            f"**章:** {chapter_title}  \n"
            f"**節:** {section_title}\n\n"
            "---\n\n"
        )
        path.write_text(header + content, encoding="utf-8")
        return str(path)

    def write_raw_tool_result(
        self,
        run_id: int,
        specialist_name: str,
        tool_name: str,
        call_index: int,
        result_data: dict,
    ) -> str:
        """web_search / web_fetch の生結果を raw/ サブディレクトリに即時保存する。"""
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "_", specialist_name)
        raw_dir = self._dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_name}_run{run_id}_{tool_name}_{call_index:03d}_{date_str}.md"
        path = raw_dir / filename

        if tool_name == "web_search":
            query = result_data.get("query", "")
            results = result_data.get("results", [])
            lines = [
                f"# web_search — {specialist_name} / Run {run_id} / #{call_index}",
                "",
                f"**クエリ:** {query}",
                f"**件数:** {len(results)}",
                "",
                "## 結果",
                "",
            ]
            for i, r in enumerate(results, 1):
                lines.append(f"### {i}. {r.get('title', '(no title)')}")
                lines.append(f"- URL: {r.get('url', '')}")
                lines.append(f"- スニペット: {r.get('content', '')}")
                lines.append("")
        elif tool_name == "web_fetch":
            url = result_data.get("url", "")
            content = result_data.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            lines = [
                f"# web_fetch — {specialist_name} / Run {run_id} / #{call_index}",
                "",
                f"**URL:** {url}",
                "",
                "## 取得内容",
                "",
                content,
            ]
        else:
            lines = [
                f"# {tool_name} — {specialist_name} / Run {run_id} / #{call_index}",
                "",
                "```json",
                json.dumps(result_data, ensure_ascii=False, indent=2),
                "```",
            ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def write_run_manifest(
        self,
        run_id: int,
        topic: str,
        style: str,
        specialists: list[dict],
        artifact_paths: dict[str, str],
        discussion_artifact_path: str | None,
        report_path: str,
    ) -> str:
        from research_team.output.run_manifest import RunManifest, SpecialistEntry

        entries = [
            SpecialistEntry(
                name=s["name"],
                expertise=s["expertise"],
                artifact_path=artifact_paths.get(s["name"], ""),
            )
            for s in specialists
        ]
        manifest = RunManifest(
            run_id=run_id,
            topic=topic,
            style=style,
            specialists=entries,
            discussion_artifact_path=discussion_artifact_path,
            report_path=report_path,
        )
        path = self._dir / f"manifest_run{run_id}.json"
        manifest.save(path)
        return str(path)

    @classmethod
    def for_session(cls, workspace_dir: Path, session_id: str) -> "ArtifactWriter":
        """プロジェクト不在時のフォールバック用。workspace/sessions/{session_id}/artifacts/ を使う。"""
        artifacts_dir = workspace_dir / "sessions" / session_id / "artifacts"
        return cls(artifacts_dir)

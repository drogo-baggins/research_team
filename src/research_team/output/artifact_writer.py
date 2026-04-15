from __future__ import annotations

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

    def write_specialist_draft(self, run_id: int, specialist_name: str, content: str) -> str:
        """スペシャリスト1名の調査結果を中間MDとして保存する。"""
        date_str = datetime.now().strftime("%Y%m%d")
        safe_name = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "_", specialist_name)
        path = self._dir / f"specialist_{safe_name}_run{run_id}_{date_str}.md"
        header = f"# 調査中間成果物 — {specialist_name} / Run {run_id} ({date_str})\n\n"
        path.write_text(header + content, encoding="utf-8")
        return str(path)

    @classmethod
    def for_session(cls, workspace_dir: Path, session_id: str) -> "ArtifactWriter":
        """プロジェクト不在時のフォールバック用。workspace/sessions/{session_id}/artifacts/ を使う。"""
        artifacts_dir = workspace_dir / "sessions" / session_id / "artifacts"
        return cls(artifacts_dir)

from __future__ import annotations

from pathlib import Path

from research_team.output.run_manifest import RunManifest

_HEADER_LINES = 2  # "# 調査中間成果物 — ..." + 空行


class ArtifactReconstructor:
    """RunManifest のアーティファクトから combined_content を再構成する。"""

    def reconstruct(self, manifest: RunManifest) -> str:
        sections: list[str] = []

        for entry in manifest.specialists:
            path = Path(entry.artifact_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"スペシャリストアーティファクトが見つかりません: {entry.artifact_path}"
                )
            raw = path.read_text(encoding="utf-8")
            lines = raw.split("\n")
            body = "\n".join(lines[_HEADER_LINES:]).strip()
            sections.append(body)

        combined = "\n\n".join(sections)

        if manifest.discussion_artifact_path:
            disc_path = Path(manifest.discussion_artifact_path)
            if disc_path.exists():
                combined += "\n\n---\n\n" + disc_path.read_text(encoding="utf-8").strip()

        return combined

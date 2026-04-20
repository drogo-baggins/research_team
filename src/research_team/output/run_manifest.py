from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SpecialistEntry:
    name: str
    expertise: str
    artifact_path: str  # specialist_*.md の絶対パス


@dataclass
class RunManifest:
    run_id: int
    topic: str
    style: str
    specialists: list[SpecialistEntry]
    discussion_artifact_path: str | None
    report_path: str

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["specialists"] = [SpecialistEntry(**s) for s in data["specialists"]]
        return cls(**data)

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

FILENAME = "run_progress.json"


@dataclass
class SpecialistProgress:
    name: str
    expertise: str
    artifact_path: str = ""
    completed: bool = False


@dataclass
class RunProgress:
    run_id: int
    topic: str
    style: str
    depth: str
    locales: list[str]
    all_specialists: list[SpecialistProgress]
    wbs_artifact_path: str
    created_at: str
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def completed_specialists(self) -> list[SpecialistProgress]:
        return [s for s in self.all_specialists if s.completed]

    @property
    def pending_specialists(self) -> list[SpecialistProgress]:
        return [s for s in self.all_specialists if not s.completed]

    def mark_specialist_done(self, name: str, artifact_path: str) -> None:
        for sp in self.all_specialists:
            if sp.name == name:
                sp.completed = True
                sp.artifact_path = artifact_path
                break
        self.updated_at = datetime.now().isoformat()

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "RunProgress":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["all_specialists"] = [
            SpecialistProgress(**s) for s in data["all_specialists"]
        ]
        return cls(**data)

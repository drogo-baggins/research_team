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
class BookSectionEntry:
    section_id: str
    chapter_title: str
    section_title: str
    artifact_path: str


@dataclass
class RunManifest:
    run_id: int
    topic: str
    style: str
    specialists: list[SpecialistEntry]
    discussion_artifact_path: str | None
    report_path: str
    book_sections: list[BookSectionEntry] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["specialists"] = [SpecialistEntry(**s) for s in data["specialists"]]
        raw_sections = data.get("book_sections") or []
        data["book_sections"] = [BookSectionEntry(**s) for s in raw_sections]
        return cls(**data)

from __future__ import annotations

from pydantic import BaseModel, Field

from research_team.orchestrator.book_pipeline import (
    BookSection,
    parse_outline_from_pm_output,
)

__all__ = ["BookOutline", "BookSection", "parse_outline_from_pm_output"]


class BookOutline(BaseModel):
    topic: str = ""
    chapters: list[dict] = Field(default_factory=list)

    def all_sections(self) -> list[BookSection]:
        result: list[BookSection] = []
        for ch in self.chapters:
            ch_idx = ch["chapter_index"]
            ch_title = ch["chapter_title"]
            for sec in ch.get("sections", []):
                result.append(BookSection(
                    chapter_index=ch_idx,
                    section_index=sec["section_index"],
                    chapter_title=ch_title,
                    section_title=sec["section_title"],
                    key_points=sec.get("key_points", []),
                    specialist_hint=sec.get("specialist_hint", ""),
                ))
        return result

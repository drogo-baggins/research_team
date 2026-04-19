from __future__ import annotations
from pydantic import BaseModel, Field, computed_field


class BookSection(BaseModel):
    chapter_index: int
    section_index: int
    chapter_title: str
    section_title: str
    key_points: list[str] = Field(default_factory=list)
    specialist_hint: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def section_id(self) -> str:
        return f"ch{self.chapter_index:02d}_sec{self.section_index:02d}"


class BookOutline(BaseModel):
    chapters: list[dict]

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

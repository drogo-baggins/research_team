from __future__ import annotations
import json
import re
import logging
from typing import Any, Callable, Awaitable
from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger(__name__)


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


def parse_outline_from_pm_output(raw: str) -> "BookOutline | None":
    """PMの出力テキストから ```json``` ブロックを抽出してBookOutlineを返す。失敗時はNone。"""
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if not match:
        match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if not match:
        logger.warning("parse_outline_from_pm_output: no JSON block found")
        return None
    try:
        data = json.loads(match.group(1))
        if not isinstance(data, list):
            return None
        for ch in data:
            if "chapter_index" not in ch or "chapter_title" not in ch or "sections" not in ch:
                return None
        return BookOutline(chapters=data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("parse_outline_from_pm_output: JSON parse failed: %s", exc)
        return None

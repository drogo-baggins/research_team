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


class BookChapterPipeline:

    def __init__(
        self,
        stream_fn: Callable[..., Awaitable[str]],
        specialists: list[dict],
    ) -> None:
        self._stream_fn = stream_fn
        self._specialists = specialists

    def _pick_agent(self, section: BookSection, agents: dict[str, Any]) -> tuple[str, Any]:
        hint = section.specialist_hint.lower()
        for name, agent in agents.items():
            expertise = getattr(agent, "_expertise", "").lower()
            if hint and hint in expertise:
                return name, agent
        first_name = next(iter(agents))
        return first_name, agents[first_name]

    def _build_section_prompt(
        self,
        topic: str,
        section: BookSection,
        raw_data: str,
        previous_sections_summary: str,
    ) -> str:
        key_points_text = "\n".join(f"  - {p}" for p in section.key_points)
        prev_context = (
            f"【前節までの内容（重複・矛盾を避けること）】\n{previous_sections_summary}\n\n"
            if previous_sections_summary
            else ""
        )
        return (
            f"あなたは「{topic}」について書籍の一章を執筆しています。\n\n"
            f"【担当節】{section.chapter_title} ＞ {section.section_title}\n\n"
            f"【必ず触れるべき論点】\n{key_points_text}\n\n"
            f"{prev_context}"
            f"【調査生データ（参照・引用可）】\n{raw_data[:20000]}\n\n"
            f"上記をもとに、節「{section.section_title}」を1,500〜3,000字で詳細かつ叙述的に執筆してください。\n"
            f"節見出し（### レベル）から始めてください。説明文・前置きは不要です。\n"
            f"【引用必須】調査データ内の出典を参照した場合は、各主張の末尾にインライン引用"
            f"（例: ([タイトル](URL))）を付けてください。"
            f"節の末尾に「## Sources」セクションを設け、使用した出典URLを箇条書きでリストアップしてください。"
        )

    async def run(
        self,
        topic: str,
        outline: BookOutline,
        raw_data: str,
        agents: dict[str, Any],
        artifact_writer: Any | None = None,
        run_id: int = 0,
        notify_fn: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        sections = outline.all_sections()
        written: list[str] = []
        previous_summary = ""

        for section in sections:
            agent_name, agent = self._pick_agent(section, agents)
            prompt = self._build_section_prompt(
                topic=topic,
                section=section,
                raw_data=raw_data,
                previous_sections_summary=previous_summary,
            )
            text = await self._stream_fn(agent, prompt, agent_name)
            if text:
                written.append(f"### {section.section_title}\n\n{text}")
                previous_summary += f"\n- {section.section_title}: {text[:300]}..."
                if artifact_writer:
                    try:
                        artifact_writer.write_book_section(
                            run_id=run_id,
                            section_id=section.section_id,
                            chapter_title=section.chapter_title,
                            section_title=section.section_title,
                            content=text,
                        )
                    except Exception as exc:
                        logger.warning("write_book_section failed: %s", exc)
                if notify_fn:
                    await notify_fn(
                        "CSM",
                        f"📝 {section.section_id} 「{section.section_title}」執筆完了",
                    )

        return "\n\n".join(written)

from __future__ import annotations
import json
import re
import logging
from typing import Any, Callable, Awaitable
from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger(__name__)

_MIN_SECTION_BODY_CHARS = 500
_MAX_SECTION_RETRIES = 2

_EDITORIAL_SUFFIX_MARKERS = [
    "\n## 執筆完了",
    "\n## 実装内容",
    "\n## 完了",
    "\n**字数：",
    "\n**実装内容：",
    "\n**執筆内容：",
    "\n---\n\n執筆しました",
    "\n---\n\n以上、",
    "\n以上で",
    "\n執筆いたしました",
    "\n執筆しました",
]

# LLM が出力先頭に書きがちなメタテキストのパターン（正規表現）
# 「調査を開始いたします」「ユーザーのご指示を理解しました」などの作業ログ行を除去する
import re as _re
_META_PREFIX_PATTERNS = [
    # 「調査を開始...」「調査が完了...」「調査データが揃いました」等
    _re.compile(r"^(?:調査を|調査が|調査データ|先行調査|それでは[、，]?調査|より詳細な).{0,200}(?:します|いたします|しました|揃いました|取得します)[。\n]", _re.DOTALL),
    # 「ユーザーのご指示を理解しました」
    _re.compile(r"^ユーザーのご指示.{0,300}(?:します|いたします|しました)[。\n]", _re.DOTALL),
    # 「それでは、「節タイトル」についての詳細な調査を行い...執筆いたします。」
    _re.compile(r"^それでは[、，]?「.{0,100}」.{0,300}(?:執筆いたします|執筆します)[。\n]", _re.DOTALL),
    # 「**第N章 ... > N-N ...**」のような章節ラベル再掲行
    _re.compile(r"^\*\*第\d+[章部].{0,200}\*\*\s*\n"),
    # 「では、本文を執筆いたします。」単体行
    _re.compile(r"^(?:では[、，]?|それでは[、，]?)?本文を執筆(?:いたし|し)ます[。]\s*\n"),
    # 「了解/了承/承知いたしました。…執筆いたします。」（承諾→執筆宣言の組み合わせ）
    # 本文が同一行に続く場合（例: 「了解いたしました。執筆いたします。本文の内容…」）も「執筆いたします。」まで除去する
    _re.compile(r"^(?:了解|了承|承知)[いたし]*ました[。.].{0,500}(?:執筆いたします|執筆します)[。]\s*", _re.DOTALL),
    # 「了解/了承/承知いたしました。」単体承諾行（次行以降が本文）
    _re.compile(r"^(?:了解|了承|承知)[いたし]*ました[。.]\s*\n"),
    # 「まず〜収集/調査/確認します。」単体調査宣言行
    _re.compile(r"^まず[、,]?.{0,100}(?:収集|調査|確認)(?:します|いたします)[。.]\s*\n"),
]


def _strip_meta_prefix(content: str) -> str:
    changed = True
    while changed:
        changed = False
        stripped = content.lstrip()
        for pat in _META_PREFIX_PATTERNS:
            m = pat.match(stripped)
            if m:
                stripped = stripped[m.end():].lstrip()
                changed = True
        content = stripped
    return content


def _strip_editorial_suffix(content: str) -> str:
    for marker in _EDITORIAL_SUFFIX_MARKERS:
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx].rstrip()
    return content


def _extract_body_for_length_check(content: str) -> str:
    sep = "\n---\n"
    sep_idx = content.find(sep)
    if sep_idx != -1:
        return content[sep_idx + len(sep):].strip()
    return content.strip()


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
    topic: str = ""
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
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if not match:
        logger.warning("parse_outline_from_pm_output: no JSON block found")
        return None
    try:
        data = json.loads(match.group(1))
        book_title = ""
        if isinstance(data, dict):
            book_title = data.get("book_title", "")
            chapters = data.get("chapters", [])
        elif isinstance(data, list):
            chapters = data
        else:
            return None
        for ch in chapters:
            if "chapter_index" not in ch or "chapter_title" not in ch or "sections" not in ch:
                return None
        return BookOutline(topic=book_title, chapters=chapters)
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
            f"【出力形式の厳守事項】\n"
            f"- 出力の最初の文字から本文を開始すること。「調査を開始」「ご指示を理解」「では執筆」などの前置きや作業ログを一切書かないこと。\n"
            f"- 見出し行（節タイトル・章タイトル）は書かないこと。本文のみを出力すること。\n"
            f"- 小見出しが必要な場合は #### 以下を使用すること。\n"
            f"- 適切な箇所に Markdown テーブルや箇条書きを使って視覚的に整理すること（最低1箇所）。\n"
            f"【禁止】節末尾に「執筆完了」「完了しました」「執筆いたしました」「実装内容：」「字数：」などの"
            f"完了報告・実行サマリー・メタ情報を絶対に含めないこと。\n"
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
        mark_done_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, dict[str, dict]]:
        sections = outline.all_sections()
        written: list[str] = []
        previous_summary = ""
        section_paths: dict[str, dict] = {}

        for section in sections:
            agent_name, agent = self._pick_agent(section, agents)
            prompt = self._build_section_prompt(
                topic=topic,
                section=section,
                raw_data=raw_data,
                previous_sections_summary=previous_summary,
            )
            text = ""
            for attempt in range(_MAX_SECTION_RETRIES + 1):
                text = await self._stream_fn(agent, prompt, agent_name)
                if not text:
                    continue
                text = _strip_editorial_suffix(text)
                text = _strip_meta_prefix(text)
                body = _extract_body_for_length_check(text)
                if len(body) >= _MIN_SECTION_BODY_CHARS:
                    break
                if attempt < _MAX_SECTION_RETRIES:
                    logger.warning(
                        "book_chapter: section %s output too short (%d chars), retrying (%d/%d)",
                        section.section_id,
                        len(body),
                        attempt + 1,
                        _MAX_SECTION_RETRIES,
                    )
            if text:
                written.append(f"### {section.section_title}\n\n{text}")
                previous_summary += f"\n- {section.section_title}: {text[:300]}..."
                if artifact_writer:
                    try:
                        artifact_path = artifact_writer.write_book_section(
                            run_id=run_id,
                            section_id=section.section_id,
                            chapter_title=section.chapter_title,
                            section_title=section.section_title,
                            content=text,
                        )
                        section_paths[section.section_id] = {
                            "chapter_title": section.chapter_title,
                            "section_title": section.section_title,
                            "artifact_path": artifact_path,
                        }
                    except Exception as exc:
                        logger.warning("write_book_section failed: %s", exc)
                if mark_done_fn:
                    try:
                        await mark_done_fn(section.section_id)
                    except Exception as exc:
                        logger.warning("mark_done_fn failed: %s", exc)
                if notify_fn:
                    await notify_fn(
                        "CSM",
                        f"📝 {section.section_id} 「{section.section_title}」執筆完了",
                    )

        return "\n\n".join(written), section_paths

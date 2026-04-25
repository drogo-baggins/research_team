from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from research_team.agents.base_agent import BaseResearchAgent

if TYPE_CHECKING:
    from collections.abc import Callable, Awaitable

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "agents" / "skills"

_FALLBACK_RATIO = 0.3


def _strip_leading_commentary(text: str) -> str:
    """Strip LLM meta-commentary that appears before the actual markdown content.

    When the LLM outputs editorial notes before the formatted document
    (e.g. "校正が完了しました..." or "## 実施した校正内容"), this function
    discards everything before the first top-level '# ' heading line.
    If no top-level heading is found the text is returned unchanged.
    """
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('# '):
            if i > 0:
                return '\n'.join(lines[i:]).lstrip('\n')
            break
    return text


_STYLE_EDIT_INSTRUCTIONS: dict[str, str] = {
    "book_chapter": (
        "書籍の一章として完成させてください。"
        "全体に適切な前書き（本章の概要・読者への案内）と後書き（まとめ・次章への橋渡し）を追加してください。"
        "章タイトル・節タイトルを内容に即した適切な表現に整えてください。"
    ),
    "magazine_column": (
        "マガジンコラムとして完成させてください。"
        "読者を引き込む魅力的な導入文と、行動を促す締めくくりを確認・改善してください。"
        "見出し構成が読みやすい流れになるよう整えてください。"
    ),
    "research_report": (
        "正式な調査レポートとして完成させてください。"
        "レポートタイトルと各セクションの見出しが内容を的確に表しているか確認・改善してください。"
        "エグゼクティブサマリーがある場合は、その後に本文が続く構成を維持してください。"
    ),
    "executive_memo": (
        "エグゼクティブメモとして完成させてください。"
        "メモのタイトル・件名が内容を端的に示しているか確認・改善してください。"
        "結論・提言が冒頭に明確に配置されていることを確認してください。"
    ),
    "paper": (
        "学術論文として完成させてください。"
        "冒頭に ## Abstract（英語・100-250 words）と ## 要旨（日本語・Abstractの和訳）が存在するか確認し、不足があれば補完してください。"
        "Abstract は必ず英語で記述してください。要旨は必ず日本語で記述してください。"
        "Introduction / Related Work / Methodology / Results / Discussion / Conclusion / References "
        "の各セクション見出しが揃っているか確認・整備してください（これらは日本語で記述）。"
        "References セクションは '[著者名 発行年] タイトル. URL' 形式で統一してください。"
        "LLMの作業説明・謝罪文は削除し、論文本文のみを残してください。"
    ),
}


class DocumentEditorAgent(BaseResearchAgent):
    @property
    def name(self) -> str:
        return "DocumentEditor"

    @property
    def skill_path(self) -> Path:
        return _SKILLS_DIR / "document_editor"


def _build_edit_prompt(topic: str, content: str, style: str) -> str:
    style_instruction = _STYLE_EDIT_INSTRUCTIONS.get(style, _STYLE_EDIT_INSTRUCTIONS["research_report"])
    return (
        f"【出力制約・最重要】整形済みのMarkdown本文のみを出力すること。"
        f"冒頭に「校正が完了しました」「以下の整形を行いました」「実施した校正内容」などの"
        f"作業説明・要約・前置き文を一切書いてはならない。"
        f"出力の最初の行は必ず `#` または `##` で始まるMarkdown見出しであること。\n\n"
        f"以下は「{topic}」についての最終レポート（校正前）です。\n\n"
        f"【スタイル固有の指示】{style_instruction}\n\n"
        f"【共通指示】\n"
        f"- LLMの作業説明・謝罪文・中間生産物の名残を除去してください。\n"
        f"  除去対象の例：\n"
        f"  「〜を執筆しました」「〜が完了いたしました」「〜を完了しました」\n"
        f"  「以下に執筆します」「以下のとおり執筆いたします」「承知いたしました」「了解しました」\n"
        f"  「検索します」「調査します」「確認しました」「実施しました」\n"
        f"  「以下の通りまとめました」「以下にまとめます」\n"
        f"  上記に準じる一人称のメタ発言（「〜します」「〜しました」で始まりLLMの行動を述べる文）はすべて削除してください。\n"
        f"  また「執筆完了のサマリー」「執筆内容の構成」「執筆完了の確認」などLLMの自己レポートセクション（見出し＋内容）も削除してください。\n"
        f"  さらに「検索計画」「調査計画」「クエリ一覧」など調査プロセスを示すセクション（見出し＋内容）も削除してください。\n"
        f"- 出典URL・`## Sources` セクションは変更・削除しないでください。\n"
        f"- 調査データ・統計・事実の内容は一切変更しないでください。\n"
        f"- 整形済みのMarkdown本文のみを出力し、説明文・前置き等は含めないでください。\n\n"
        f"---\n\n{content}"
    )


async def edit_document(
    stream_fn: "Callable[..., Awaitable[str]]",
    agent: DocumentEditorAgent,
    topic: str,
    content: str,
    style: str,
) -> str:
    if not content or not content.strip():
        return content

    prompt = _build_edit_prompt(topic, content, style)
    try:
        result = await stream_fn(agent, prompt, "DocumentEditor")
    except Exception as exc:
        logger.warning("edit_document: stream_fn failed: %s", exc)
        return content

    if not result or not result.strip():
        logger.warning("edit_document: empty output, using original")
        return content

    if len(result) < len(content) * _FALLBACK_RATIO:
        logger.warning(
            "edit_document: output too short (%d < %d * %.1f), using original",
            len(result),
            len(content),
            _FALLBACK_RATIO,
        )
        return content

    return _strip_leading_commentary(result)

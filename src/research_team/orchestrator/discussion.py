from __future__ import annotations

import os
from collections.abc import Callable, Awaitable
from pathlib import Path

from research_team.agents.dynamic.factory import DynamicSpecialistAgent

_TEMPLATES = Path(__file__).parent.parent / "agents" / "dynamic" / "templates"
_OPENING_TEMPLATE = _TEMPLATES / "discussion_persona.md.template"
_DEBATE_TEMPLATE = _TEMPLATES / "discussion_debate.md.template"
_MODERATOR_TEMPLATE = _TEMPLATES / "discussion_moderator.md.template"

_PERSONALITY_MAP = [
    ("懐疑的・批判的思考家", "具体例や反例から入る", "「データなき主張は仮説に過ぎない」", "根拠のない楽観論"),
    ("楽観的・ビジョン思考家", "大局観・未来像から入る", "「テクノロジーは必ず人間を解放する」", "短期的・局所的な悲観論"),
    ("実務家・現場重視", "現場の実例・コスト感覚から入る", "「理論より実装が真実を語る」", "現場を知らない理想論"),
    ("歴史家・文脈重視", "歴史的先例・パターンから入る", "「新しい問題の90%は既に解かれている」", "歴史を無視した断絶論"),
    ("倫理学者・社会影響重視", "価値観・社会的影響から入る", "「技術の目的は人間の尊厳を守ること」", "倫理を後回しにする効率優先論"),
]


_LABELS = list("ABCDEFGHIJ")


def generate_personas(specialists: list[dict]) -> list[dict]:
    personas = []
    for i, spec in enumerate(specialists):
        p = _PERSONALITY_MAP[i % len(_PERSONALITY_MAP)]
        personas.append({
            "name": spec["name"],
            "expertise": spec["expertise"],
            "label": _LABELS[i % len(_LABELS)],
            "personality": p[0],
            "speaking_style": p[1],
            "core_belief": p[2],
            "pet_peeve": p[3],
        })
    return personas


def _build_participants_list(personas: list[dict]) -> str:
    return "、".join(f"{p['label']}（{p['expertise']}）" for p in personas)


class DiscussionOrchestrator:
    def __init__(
        self,
        stream_fn: Callable[..., Awaitable[str]],
        turns: int = 2,
    ) -> None:
        self._stream_fn = stream_fn
        self._default_turns = turns

    async def _call(self, system_prompt: str, message: str, name: str, expertise: str) -> str:
        agent = DynamicSpecialistAgent(
            name=name,
            expertise=expertise,
            system_prompt=system_prompt,
            mode="discussion",
        )
        result = await self._stream_fn(agent, message, name)
        return result.strip() if result else ""

    async def _opening_utterance(
        self,
        spec: dict,
        persona: dict,
        topic: str,
        discussion_so_far: str,
        participants: str,
    ) -> str:
        template = _OPENING_TEMPLATE.read_text(encoding="utf-8")
        system_prompt = template.format(
            name=spec["name"],
            expertise=persona.get("expertise", spec.get("expertise", "")),
            my_label=persona.get("label", "A"),
            participants=participants,
            personality=persona.get("personality", ""),
            speaking_style=persona.get("speaking_style", ""),
            core_belief=persona.get("core_belief", ""),
            pet_peeve=persona.get("pet_peeve", ""),
            discussion_so_far=discussion_so_far,
            own_research=spec.get("research", ""),
        )
        return await self._call(
            system_prompt,
            f"テーマ「{topic}」について発言してください。",
            spec["name"],
            persona.get("expertise", spec.get("expertise", "")),
        )

    async def _extract_dispute(self, discussion_log: list[str], topic: str) -> str:
        template = _MODERATOR_TEMPLATE.read_text(encoding="utf-8")
        system_prompt = template.format(
            topic=topic,
            discussion_so_far="\n".join(discussion_log),
        )
        result = await self._call(
            system_prompt,
            "この議論の最も鋭い争点を1文で抽出してください。",
            "ファシリテーター",
            "討論ファシリテーション",
        )
        return result or "この政権の高支持率は構造的に脆弱か否か"

    async def _debate_utterance(
        self,
        spec: dict,
        persona: dict,
        topic: str,
        discussion_so_far: str,
        dispute_point: str,
        participants: str,
    ) -> str:
        template = _DEBATE_TEMPLATE.read_text(encoding="utf-8")
        system_prompt = template.format(
            name=spec["name"],
            expertise=persona.get("expertise", spec.get("expertise", "")),
            my_label=persona.get("label", "A"),
            participants=participants,
            personality=persona.get("personality", ""),
            speaking_style=persona.get("speaking_style", ""),
            core_belief=persona.get("core_belief", ""),
            pet_peeve=persona.get("pet_peeve", ""),
            dispute_point=dispute_point,
            discussion_so_far=discussion_so_far,
            own_research=spec.get("research", ""),
        )
        return await self._call(
            system_prompt,
            f"争点「{dispute_point}」について、直前の発言に応答してください。",
            spec["name"],
            persona.get("expertise", spec.get("expertise", "")),
        )

    async def run(
        self,
        specialists: list[dict],
        personas: list[dict],
        topic: str,
    ) -> str:
        debate_turns = int(os.environ.get("RT_DISCUSSION_TURNS", str(self._default_turns)))
        persona_map = {p["name"]: p for p in personas}
        participants = _build_participants_list(personas)

        discussion_log: list[str] = []
        lines: list[str] = [f"# スペシャリスト対談: {topic.split(chr(10))[0].strip()}", ""]

        for spec in specialists:
            discussion_so_far = (
                "\n".join(discussion_log)
                if discussion_log
                else "（まだ発言はありません。最初の発言者としてテーマを提起してください）"
            )
            utterance = await self._opening_utterance(
                spec, persona_map.get(spec["name"], {}), topic, discussion_so_far, participants
            )
            entry = f"**{spec['name']}**: {utterance}" if utterance else f"**{spec['name']}**: （発言なし）"
            discussion_log.append(entry)
            lines.append(entry)
            lines.append("")

        dispute_point = await self._extract_dispute(discussion_log, topic)
        lines.append(f"> **争点**: {dispute_point}")
        lines.append("")

        for _turn in range(debate_turns):
            for spec in specialists:
                utterance = await self._debate_utterance(
                    spec,
                    persona_map.get(spec["name"], {}),
                    topic,
                    "\n".join(discussion_log),
                    dispute_point,
                    participants,
                )
                entry = f"**{spec['name']}**: {utterance}" if utterance else f"**{spec['name']}**: （発言なし）"
                discussion_log.append(entry)
                lines.append(entry)
                lines.append("")

        return "\n".join(lines)


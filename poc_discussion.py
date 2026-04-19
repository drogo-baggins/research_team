from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from research_team.agents.dynamic.factory import DynamicSpecialistAgent
from research_team.orchestrator.discussion import DiscussionOrchestrator, generate_personas
from research_team.pi_bridge.types import AgentEvent

SESSION_DIR = Path(__file__).parent / "workspace" / "sessions" / \
    "20260418_173204_高市政権は発足以来高い支持率をキープして" / "artifacts"

TOPIC = "高市政権の高支持率は持続するか、それとも脆弱な基盤の上に成り立っているか"

DEBATE_TURNS = 2

SPECIALISTS_META = [
    {
        "name": "政治アナリスト",
        "expertise": "日本国内政治・選挙分析",
        "research_file": "specialist_政治アナリスト_run1_20260418.md",
    },
    {
        "name": "国際政治・地政学アナリスト",
        "expertise": "国際政治・日米関係・地政学",
        "research_file": "specialist_国際政治・地政学アナリスト_run1_20260418.md",
    },
    {
        "name": "メディア・世論分析家",
        "expertise": "メディア分析・世論形成・SNS動向",
        "research_file": "specialist_メディア・世論分析家_run1_20260418.md",
    },
]


def load_research(filename: str) -> str:
    path = SESSION_DIR / filename
    if not path.exists():
        return "(調査データなし)"
    text = path.read_text(encoding="utf-8")
    idx = text.find("\n# ")
    return text[idx:].strip() if idx >= 0 else text.strip()


async def stream_fn(agent: DynamicSpecialistAgent, message: str, agent_name: str) -> str:
    parts: list[str] = []
    print(f"\n  [{agent_name}] 発言生成中...", flush=True)

    async for event in agent.run(message, workspace_dir=None, search_port=0):
        event: AgentEvent
        if event.type == "message_update":
            ame = event.data.get("assistantMessageEvent", {})
            if ame.get("type") == "text_delta":
                delta = ame.get("delta", "")
                if delta:
                    parts.append(delta)
                    print(delta, end="", flush=True)
        elif event.type == "extension_error":
            err = event.data.get("error", "")
            print(f"\n  ⚠️ extension_error: {err}", flush=True)

    print()
    return "".join(parts).strip()


async def main() -> None:
    print("=" * 70)
    print(f"POC: DiscussionOrchestrator / トピック: {TOPIC} / 開幕1回 + 争点抽出 + 集中討論{DEBATE_TURNS}回")
    print("=" * 70)

    specialists: list[dict] = []
    for meta in SPECIALISTS_META:
        research = load_research(meta["research_file"])
        specialists.append({
            "name": meta["name"],
            "expertise": meta["expertise"],
            "research": research[:3000],
        })
        print(f"✅ {meta['name']}: {len(research)} 文字 読み込み完了")

    personas = generate_personas(specialists)
    for p in personas:
        print(f"  {p['name']}: {p['personality']} / 「{p['core_belief']}」")

    print("\n--- ディスカッション開始 ---\n")
    orchestrator = DiscussionOrchestrator(stream_fn=stream_fn, turns=DEBATE_TURNS)
    transcript = await orchestrator.run(specialists=specialists, personas=personas, topic=TOPIC)

    print("\n" + "=" * 70)
    print(transcript)

    out_path = Path(__file__).parent / "poc_discussion_output.md"
    out_path.write_text(transcript, encoding="utf-8")
    print(f"\n✅ 保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())


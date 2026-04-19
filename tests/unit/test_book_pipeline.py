from research_team.orchestrator.book_pipeline import BookSection, BookOutline, parse_outline_from_pm_output, BookChapterPipeline
import asyncio
from unittest.mock import AsyncMock, MagicMock

def test_book_section_fields():
    sec = BookSection(
        chapter_index=1,
        section_index=2,
        chapter_title="第1章 市場概観",
        section_title="1-2 競合動向",
        key_points=["A社の動向", "B社の戦略"],
        specialist_hint="経済アナリスト",
    )
    assert sec.section_id == "ch01_sec02"
    assert sec.chapter_index == 1
    assert sec.section_index == 2

def test_book_outline_all_sections():
    outline = BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "第1章",
            "sections": [
                {"section_index": 1, "section_title": "1-1", "key_points": [], "specialist_hint": ""},
                {"section_index": 2, "section_title": "1-2", "key_points": [], "specialist_hint": ""},
            ],
        }
    ])
    sections = outline.all_sections()
    assert len(sections) == 2
    assert sections[0].section_id == "ch01_sec01"
    assert sections[1].section_id == "ch01_sec02"


def test_parse_outline_valid_json():
    raw = '''
    考えてみます。
    ```json
    [
      {
        "chapter_index": 1,
        "chapter_title": "第1章 概観",
        "sections": [
          {"section_index": 1, "section_title": "1-1 背景", "key_points": ["A", "B"], "specialist_hint": "歴史"}
        ]
      }
    ]
    ```
    以上です。
    '''
    outline = parse_outline_from_pm_output(raw)
    assert outline is not None
    sections = outline.all_sections()
    assert len(sections) == 1
    assert sections[0].chapter_title == "第1章 概観"
    assert sections[0].key_points == ["A", "B"]

def test_parse_outline_invalid_returns_none():
    outline = parse_outline_from_pm_output("JSONがありません")
    assert outline is None

def test_parse_outline_wrong_schema_returns_none():
    raw = '```json\n[{"chapter_title": "章"}]\n```'
    outline = parse_outline_from_pm_output(raw)
    assert outline is None


def _make_outline() -> BookOutline:
    return BookOutline(chapters=[
        {
            "chapter_index": 1,
            "chapter_title": "第1章",
            "sections": [
                {"section_index": 1, "section_title": "1-1", "key_points": ["A"], "specialist_hint": "経済"},
                {"section_index": 2, "section_title": "1-2", "key_points": ["B"], "specialist_hint": "技術"},
            ],
        }
    ])

def test_build_section_prompt_contains_key_points():
    pipeline = BookChapterPipeline(
        stream_fn=AsyncMock(return_value="text"),
        specialists=[{"name": "経済アナリスト", "expertise": "経済・金融"}],
    )
    section = BookSection(
        chapter_index=1, section_index=1,
        chapter_title="第1章", section_title="1-1",
        key_points=["論点X", "論点Y"],
        specialist_hint="経済",
    )
    prompt = pipeline._build_section_prompt(
        topic="テスト",
        section=section,
        raw_data="調査データ...",
        previous_sections_summary="前節の要約",
    )
    assert "論点X" in prompt
    assert "論点Y" in prompt
    assert "前節の要約" in prompt

def test_run_returns_combined_text():
    call_count = 0

    async def mock_stream(agent, prompt, name, **kwargs):
        nonlocal call_count
        call_count += 1
        return f"section_text_{call_count}"

    pipeline = BookChapterPipeline(
        stream_fn=mock_stream,
        specialists=[
            {"name": "経済アナリスト", "expertise": "経済・金融"},
            {"name": "技術者", "expertise": "技術"},
        ],
    )
    outline = _make_outline()
    result = asyncio.run(
        pipeline.run(
            topic="テスト",
            outline=outline,
            raw_data="調査生データ",
            agents={"経済アナリスト": MagicMock(), "技術者": MagicMock()},
        )
    )
    assert "section_text_1" in result
    assert "section_text_2" in result
    assert call_count == 2

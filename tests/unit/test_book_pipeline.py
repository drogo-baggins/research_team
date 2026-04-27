from research_team.orchestrator.book_pipeline import BookSection, BookOutline, parse_outline_from_pm_output, BookChapterPipeline, _strip_meta_prefix
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


def test_parse_outline_object_format_with_book_title():
    raw = '''
    ```json
    {
      "book_title": "副交感神経の科学",
      "chapters": [
        {
          "chapter_index": 1,
          "chapter_title": "第1章 概観",
          "sections": [
            {"section_index": 1, "section_title": "1-1 背景", "key_points": ["A"], "specialist_hint": "歴史"}
          ]
        }
      ]
    }
    ```
    '''
    outline = parse_outline_from_pm_output(raw)
    assert outline is not None
    assert outline.topic == "副交感神経の科学"
    sections = outline.all_sections()
    assert len(sections) == 1
    assert sections[0].chapter_title == "第1章 概観"


def test_parse_outline_object_format_no_book_title():
    raw = '''
    ```json
    {
      "chapters": [
        {
          "chapter_index": 1,
          "chapter_title": "第1章 概観",
          "sections": [
            {"section_index": 1, "section_title": "1-1 背景", "key_points": [], "specialist_hint": ""}
          ]
        }
      ]
    }
    ```
    '''
    outline = parse_outline_from_pm_output(raw)
    assert outline is not None
    assert outline.topic == ""

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


def test_build_section_prompt_forbids_meta_prefix():
    pipeline = BookChapterPipeline(
        stream_fn=AsyncMock(return_value="text"),
        specialists=[],
    )
    section = BookSection(
        chapter_index=1, section_index=1,
        chapter_title="第1章", section_title="1-1",
        key_points=[],
        specialist_hint="",
    )
    prompt = pipeline._build_section_prompt(
        topic="テスト",
        section=section,
        raw_data="",
        previous_sections_summary="",
    )
    assert "前置きや作業ログを一切書かないこと" in prompt


def test_build_section_prompt_requires_visual_element():
    pipeline = BookChapterPipeline(
        stream_fn=AsyncMock(return_value="text"),
        specialists=[],
    )
    section = BookSection(
        chapter_index=1, section_index=1,
        chapter_title="第1章", section_title="1-1",
        key_points=[],
        specialist_hint="",
    )
    prompt = pipeline._build_section_prompt(
        topic="テスト",
        section=section,
        raw_data="",
        previous_sections_summary="",
    )
    assert "テーブル" in prompt or "箇条書き" in prompt


class TestStripMetaPrefix:
    def test_strips_investigation_start(self):
        content = "調査を開始いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_user_instruction_acknowledgment(self):
        content = "ユーザーのご指示を理解しました。1,500字で執筆いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_soredewa_pattern(self):
        content = "それでは、「1-1 テーマ」についての詳細な調査を行い、執筆いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_chapter_label_reprise(self):
        content = "**第1章 タイトル > 1-1 節タイトル**\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_clean_content_unchanged(self):
        content = "本文が最初から始まっています。重要な内容です。"
        result = _strip_meta_prefix(content)
        assert result == content

    def test_strips_multiple_layers(self):
        content = "調査を開始いたします。データを収集します。\nそれでは、「節」についての詳細な調査を行い、執筆いたします。\n\n本文です。"
        result = _strip_meta_prefix(content)
        assert "本文です" in result
        assert "調査を開始" not in result

    def test_strips_ryokai_plus_execution_declaration(self):
        content = "了解いたしました。節「2-2 テーマ」を詳しく調査・執筆いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")
        assert "了解" not in result

    def test_strips_ryosho_plus_execution_declaration(self):
        content = "了承いたしました。第5章 5-2節についての内容を執筆いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_shochi_plus_execution_declaration(self):
        content = "承知いたしました。第4章 4-2節を執筆いたします。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_ryokai_with_body_on_same_line(self):
        content = "了解いたしました。第3章 3-1節についての内容を執筆いたします。AIエージェント時代において、マスターデータ管理は重要です。"
        result = _strip_meta_prefix(content)
        assert result.startswith("AIエージェント時代")
        assert "了解" not in result

    def test_strips_standalone_ryokai_line(self):
        content = "了解いたしました。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_strips_mazu_chousa_declaration(self):
        content = "まず、必要な情報を収集します。\n\n本文が始まります。"
        result = _strip_meta_prefix(content)
        assert result.startswith("本文が始まります")

    def test_does_not_strip_body_starting_with_ryokai_context(self):
        content = "本文は了解を得た後から始まります。重要な内容が続きます。"
        result = _strip_meta_prefix(content)
        assert result == content

def test_run_returns_combined_text():
    call_count = 0
    long_body = "十分な本文です。" * 80

    async def mock_stream(agent, prompt, name, **kwargs):
        nonlocal call_count
        call_count += 1
        return f"section_text_{call_count}\n\n{long_body}"

    pipeline = BookChapterPipeline(
        stream_fn=mock_stream,
        specialists=[
            {"name": "経済アナリスト", "expertise": "経済・金融"},
            {"name": "技術者", "expertise": "技術"},
        ],
    )
    outline = _make_outline()
    result, section_paths = asyncio.run(
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

from research_team.orchestrator.book_pipeline import BookSection, BookOutline, parse_outline_from_pm_output

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

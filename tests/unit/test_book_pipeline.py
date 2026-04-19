from research_team.orchestrator.book_pipeline import BookSection, BookOutline

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

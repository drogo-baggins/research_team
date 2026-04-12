import pytest
from research_team.search.human import HumanSearchEngine


@pytest.mark.skip(reason="Manual E2E test - requires real browser")
async def test_human_search_google():
    engine = HumanSearchEngine()
    try:
        results = await engine.search("Python asyncio tutorial", max_results=2)
        assert len(results) > 0, "検索結果が0件"
        for r in results:
            assert r.url.startswith("http")
            assert len(r.content) > 100, f"コンテンツが短すぎる: {r.url}"
            print(f"✓ {r.title[:50]} — {len(r.content)} chars")
    finally:
        await engine.close()


@pytest.mark.skip(reason="Manual E2E test - requires real browser")
async def test_human_fetch_url():
    engine = HumanSearchEngine()
    try:
        result = await engine.fetch("https://www.python.org")
        assert "Python" in result.title
        assert len(result.content) > 100
        print(f"✓ {result.title} — {len(result.content)} chars")
    finally:
        await engine.close()

"""
Google SERP 新形式 DOM に対する統合テスト。

`#rso` コンテナ + `h3` を含む `<a>` タグという現在の Google DOM 構造を
再現した静的 HTML を Playwright で読み込み、`GoogleSearchExtractor` が
結果を正しく抽出できることを確認する。

本番 Google への接続は不要。
"""

import asyncio
import sys
import textwrap
from playwright.async_api import async_playwright

sys.path.insert(0, "src")
from research_team.search.google_extractor import GoogleSearchExtractor

MOCK_HTML = textwrap.dedent("""
<!DOCTYPE html>
<html>
<head><title>test - Google Search</title></head>
<body>
  <div id="rso">
    <div data-hveid="1">
      <a href="https://example.com/page1">
        <h3>Result One</h3>
      </a>
      <div><span>Snippet for result one describing the page content.</span></div>
    </div>
    <div data-hveid="2">
      <a href="https://example.org/page2">
        <h3>Result Two</h3>
      </a>
      <div><span>Snippet for result two.</span></div>
    </div>
    <div data-hveid="3">
      <a href="https://docs.python.org/3/library/asyncio.html">
        <h3>asyncio — Python docs</h3>
      </a>
      <div><span>Official Python asyncio documentation.</span></div>
    </div>
    <div data-hveid="4">
      <a href="https://maps.google.com/maps?q=tokyo">
        <h3>Google Maps - Tokyo</h3>
      </a>
    </div>
    <div>
      <a href="https://example.com/no-h3-link">
        No h3 here - should be excluded
      </a>
    </div>
  </div>
</body>
</html>
""").strip()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(MOCK_HTML)

        extractor = GoogleSearchExtractor()
        results = await extractor.extract(page, max_results=10)

        print(f"\nExtracted {len(results)} results:")
        for i, r in enumerate(results):
            print(f"  [{i}] url={r.url!r}  title={r.title!r}")

        await browser.close()

        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        urls = [r.url for r in results]
        assert "https://example.com/page1" in urls, "page1 missing"
        assert "https://example.org/page2" in urls, "page2 missing"
        assert "https://docs.python.org/3/library/asyncio.html" in urls, "asyncio missing"
        assert not any("google.com" in u for u in urls), "Google URL leaked through"
        assert not any("no-h3" in u for u in urls), "non-h3 link leaked through"

        assert results[0].title == "Result One"
        assert results[1].title == "Result Two"
        assert results[2].title == "asyncio — Python docs"

        print("\n✅ All assertions passed - GoogleSearchExtractor works correctly with current Google DOM structure")


asyncio.run(main())

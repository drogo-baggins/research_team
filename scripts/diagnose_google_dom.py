"""
Google SERP DOM 診断スクリプト。

使い方:
    python scripts/diagnose_google_dom.py "OCI wallet python"

a[href^="/url?"] セレクターが現在の Google DOM でマッチするかどうか、
また実際にどのセレクターが結果リンクに使われているかを調べる。
"""

import asyncio
import sys
import json
from playwright.async_api import async_playwright


QUERY = sys.argv[1] if len(sys.argv) > 1 else "site:example.com test"
GOOGLE_URL = f"https://www.google.com/search?q={QUERY.replace(' ', '+')}&hl=en"

# 複数のセレクター候補を試す
SELECTORS = [
    'a[href^="/url?"]',           # 従来の相対リダイレクト形式
    'a[href*="google.com/url?"]', # 絶対リダイレクト形式
    'a[jsname]',                   # jsname 属性付きリンク（新しいUI）
    'h3 a',                        # h3内リンク
    'a[data-ved]',                 # data-ved 属性付きリンク
    '#search a[href]',             # 検索結果内リンク全般
]

DUMP_JS = """
() => {
  const links = Array.from(document.querySelectorAll('#search a[href]'));
  return links.slice(0, 20).map(a => ({
    href: a.getAttribute('href'),
    text: (a.textContent || '').trim().slice(0, 60),
    hasH3: !!a.querySelector('h3'),
    jsname: a.getAttribute('jsname'),
    dataVed: a.getAttribute('data-ved'),
  }));
}
"""


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"\n=== Navigating to Google: {GOOGLE_URL} ===\n")
        resp = await page.goto(GOOGLE_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"Status: {resp.status}  URL: {page.url}")

        # ページタイトル確認
        title = await page.title()
        print(f"Page title: {title}")

        # 同意画面チェック
        consent_visible = await page.locator('form[action*="consent"]').count()
        print(f"Consent form count: {consent_visible}")

        print("\n--- Selector match counts ---")
        for sel in SELECTORS:
            count = await page.locator(sel).count()
            print(f"  {sel!r:40s}: {count}")

        print("\n--- First 20 links in #search (raw dump) ---")
        try:
            links = await page.evaluate(DUMP_JS)
            for i, link in enumerate(links):
                print(f"  [{i:2d}] href={link['href']!r:.80}  jsname={link['jsname']!r}  hasH3={link['hasH3']}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # a[href^="/url?"] にマッチしたものの href をダンプ
        old_style_count = await page.locator('a[href^="/url?"]').count()
        print(f"\n--- a[href^='/url?'] matches: {old_style_count} ---")
        if old_style_count:
            hrefs = await page.locator('a[href^="/url?"]').evaluate_all(
                "els => els.map(a => a.getAttribute('href'))"
            )
            for h in hrefs[:10]:
                print(f"  {h!r:.100}")

        # h3 を含むリンクの href
        h3_link_count = await page.locator('h3 a').count()
        print(f"\n--- h3 a matches: {h3_link_count} ---")
        if h3_link_count:
            h3_hrefs = await page.locator('h3 a').evaluate_all(
                "els => els.map(a => ({ href: a.getAttribute('href'), text: (a.textContent||'').trim().slice(0,60) }))"
            )
            for item in h3_hrefs[:10]:
                print(f"  href={item['href']!r:.80}  text={item['text']!r}")

        await browser.close()
        print("\n=== Done ===\n")


asyncio.run(main())

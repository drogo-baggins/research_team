from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

import markdown as md_lib

logger = logging.getLogger(__name__)

_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
    font-size: 11pt;
    line-height: 1.8;
    max-width: 860px;
    margin: 0 auto;
    padding: 2rem;
    color: #1a1a1a;
  }}
  h1 {{ font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: .3em; margin-top: 1.5em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid #aaa; padding-bottom: .2em; margin-top: 1.4em; }}
  h3 {{ font-size: 1.1em; margin-top: 1.2em; }}
  pre {{ background: #f5f5f5; padding: 1em; border-radius: 4px; overflow-x: auto; font-size: 9pt; }}
  code {{ font-family: "Courier New", monospace; font-size: 9pt; background: #f0f0f0; padding: .1em .3em; border-radius: 2px; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 10pt; }}
  th, td {{ border: 1px solid #ccc; padding: .4em .7em; }}
  th {{ background: #f0f0f0; }}
  a {{ color: #0066cc; }}
  .mermaid {{ text-align: center; margin: 1.5em auto; }}
  @media print {{
    body {{ max-width: 100%; padding: 0; }}
    a {{ color: inherit; }}
  }}
</style>
</head>
<body>
{body}
<script src="{mermaid_cdn}"></script>
<script>
  mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
</script>
</body>
</html>
"""

_MERMAID_FENCE_RE = re.compile(
    r"```mermaid\r?\n(.*?)\r?\n```",
    re.DOTALL,
)


def _preprocess_mermaid(content: str) -> str:
    return _MERMAID_FENCE_RE.sub(
        lambda m: f'<div class="mermaid">\n{m.group(1)}\n</div>',
        content,
    )


def _markdown_to_html(content: str) -> str:
    preprocessed = _preprocess_mermaid(content)
    body = md_lib.markdown(
        preprocessed,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return _HTML_TEMPLATE.format(body=body, mermaid_cdn=_MERMAID_CDN)


def _pdf_path_from_md(md_path: str) -> Path:
    return Path(md_path).with_suffix(".pdf")


async def _render_pdf(html: str, output_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            mermaid_count_js = "document.querySelectorAll('.mermaid').length"
            count = await page.evaluate(mermaid_count_js)
            if count > 0:
                await page.wait_for_function(
                    "() => {"
                    "  const all = document.querySelectorAll('.mermaid');"
                    "  const done = document.querySelectorAll('.mermaid[data-processed=\"true\"]');"
                    "  return all.length > 0 && done.length === all.length;"
                    "}",
                    timeout=15000,
                )
            await page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
            )
        finally:
            await browser.close()


class PDFOutput:
    def __init__(self, workspace_dir: str | None = None):
        self._workspace_dir = Path(workspace_dir or os.path.join(os.getcwd(), "workspace"))
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    def save(self, content: str, md_path: str) -> str:
        output_path = _pdf_path_from_md(md_path)
        html = _markdown_to_html(content)
        try:
            asyncio.get_event_loop().run_until_complete(_render_pdf(html, output_path))
        except RuntimeError:
            asyncio.run(_render_pdf(html, output_path))
        logger.info("PDF saved: %s", output_path)
        return str(output_path)

    async def save_async(self, content: str, md_path: str) -> str:
        output_path = _pdf_path_from_md(md_path)
        html = _markdown_to_html(content)
        await _render_pdf(html, output_path)
        logger.info("PDF saved: %s", output_path)
        return str(output_path)

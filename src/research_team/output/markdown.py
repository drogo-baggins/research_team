import os
import re
from datetime import datetime
from pathlib import Path


def _make_title(topic: str) -> str:
    title = re.sub(r"[\r\n]+", " ", topic).strip()
    title = re.sub(r"\s+", " ", title)
    title = title.rstrip("。、？！…")
    if len(title) > 30:
        title = title[:30] + "…"
    return title or "リサーチレポート"


class MarkdownOutput:
    def __init__(self, workspace_dir: str | None = None):
        self._workspace_dir = Path(workspace_dir or os.path.join(os.getcwd(), "workspace"))
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    def save(self, content: str, topic: str, report_type: str = "business") -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        slug = _make_title(topic).replace(" ", "_").replace("/", "-").replace("…", "")
        filename = f"report_{slug}_{date_str}.md"
        output_path = self._workspace_dir / filename

        body, sources_section = self._collect_sources(content)
        header = self._build_header(topic, report_type)
        parts = [header, body]
        if sources_section:
            parts.append(sources_section)
        full_content = "\n\n".join(parts)

        output_path.write_text(full_content, encoding="utf-8")
        return str(output_path)

    def _collect_sources(self, content: str) -> tuple[str, str]:
        """Extract all ## Sources / ## 参考文献 sections, deduplicate, and return (body, unified_sources)."""
        sources: list[str] = []

        def _replace(m: re.Match) -> str:
            for line in m.group(1).splitlines():
                stripped = line.strip()
                if stripped.startswith("-"):
                    sources.append(stripped)
            return ""

        body = re.sub(
            r"## (?:Sources|参考文献)\s*\n((?:.*\n?)*?)(?=\n## |\Z)",
            _replace,
            content,
        )
        unique = list(dict.fromkeys(sources))
        sources_section = "## 参考文献\n\n" + "\n".join(unique) if unique else ""
        return body.strip(), sources_section

    def _build_header(self, topic: str, report_type: str) -> str:
        date_str = datetime.now().strftime("%Y年%m月%d日")
        type_labels = {
            "business": "ビジネス報告",
            "academic": "学術レポート",
            "paper": "論文",
            "book": "書籍",
            "research_report": "調査レポート",
            "executive_memo": "エグゼクティブメモ",
            "magazine_column": "マガジンコラム",
            "book_chapter": "書籍チャプター",
        }
        label = type_labels.get(report_type, "報告書")
        title = _make_title(topic)
        return f"# {title}\n\n**形式:** {label}  \n**作成日:** {date_str}"

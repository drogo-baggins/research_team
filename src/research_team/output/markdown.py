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


def _extract_title_from_content(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return None


def _slugify(title: str) -> str:
    slug = re.sub(r"[\r\n]+", " ", title).strip()
    slug = re.sub(r"\s+", "_", slug)
    slug = slug.replace("/", "-").replace("\\", "-")
    slug = re.sub(r'[<>:"|?*]', "", slug)
    if len(slug) > 50:
        slug = slug[:50]
    return slug or "report"


class MarkdownOutput:
    def __init__(self, workspace_dir: str | None = None):
        self._workspace_dir = Path(workspace_dir or os.path.join(os.getcwd(), "workspace"))
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    def save(self, content: str, topic: str, report_type: str = "business", output_path: Path | str | None = None) -> str:
        body, sources_section = self._collect_sources(content)

        if output_path is not None:
            final_path = Path(output_path)
        else:
            date_str = datetime.now().strftime("%Y%m%d")
            title = _extract_title_from_content(body) or _make_title(topic)
            slug = _slugify(title)
            filename = f"report_{slug}_{date_str}.md"
            final_path = self._workspace_dir / filename

        parts = [body]
        if sources_section:
            parts.append(sources_section)
        full_content = "\n\n".join(parts)

        final_path.write_text(full_content, encoding="utf-8")
        return str(final_path)

    def _collect_sources(self, content: str) -> tuple[str, str]:
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

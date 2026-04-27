from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SOURCES_HEADER_RE = re.compile(r"^##\s+Sources\s*$", re.MULTILINE | re.IGNORECASE)


class BookAssembleTool:
    def _strip_artifact_header(self, raw: str) -> str:
        sep_idx = raw.find("---\n\n")
        if sep_idx == -1:
            return raw.strip()
        return raw[sep_idx + 5:].strip()

    def _strip_section_heading(self, content: str) -> str:
        stripped = content.lstrip()
        lines = stripped.splitlines()
        if not lines:
            return content
        if re.match(r"^#{1,3}\s+", lines[0]):
            rest = "\n".join(lines[1:]).lstrip()
            return rest
        return stripped

    def _strip_sources_suffix(self, content: str) -> str:
        m = _SOURCES_HEADER_RE.search(content)
        if m:
            return content[: m.start()].rstrip()
        return content

    def _extract_sources(self, content: str) -> list[str]:
        m = _SOURCES_HEADER_RE.search(content)
        if not m:
            return []
        sources_block = content[m.end():]
        urls: list[str] = []
        for line in sources_block.splitlines():
            line = line.strip().lstrip("-").strip()
            if line.startswith("http"):
                urls.append(line)
        return urls

    def _read_section(self, artifact_path: str) -> tuple[str, list[str]]:
        try:
            raw = Path(artifact_path).read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("BookAssembleTool: failed to read %s: %s", artifact_path, exc)
            return "", []

        content = self._strip_artifact_header(raw)
        sources = self._extract_sources(content)
        content = self._strip_sources_suffix(content)
        content = self._strip_section_heading(content)
        return content.strip(), sources

    @staticmethod
    def _strip_chapter_prefix(title: str) -> str:
        return re.sub(r"^第\d+[章部]\s*[　\s]?", "", title).strip()

    def assemble(
        self,
        outline: "BookOutline",
        section_paths: dict[str, dict],
        discussion_path: Path | None = None,
        topic: str = "",
    ) -> str:
        all_sources: list[str] = []

        toc_lines = ["## 目次", ""]
        for ch in outline.chapters:
            ci = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            toc_lines.append(f"**第{ci}章　{ch_title}**")
            for sec in ch.get("sections", []):
                si = sec["section_index"]
                sec_title = sec["section_title"]
                toc_lines.append(f"　　第{ci}.{si}節　{sec_title}")
            toc_lines.append("")

        chapter_parts: list[str] = []
        for ch in outline.chapters:
            ci = ch["chapter_index"]
            ch_title = self._strip_chapter_prefix(ch["chapter_title"])
            ch_lines: list[str] = [f"## 第{ci}章　{ch_title}", ""]
            for sec in ch.get("sections", []):
                si = sec["section_index"]
                sec_title = sec["section_title"]
                section_id = f"ch{ci:02d}_sec{si:02d}"
                entry = section_paths.get(section_id, {})
                artifact_path = entry.get("artifact_path", "")

                ch_lines.append(f"### {sec_title}")
                ch_lines.append("")

                if artifact_path:
                    body, sources = self._read_section(artifact_path)
                    all_sources.extend(sources)
                    if body:
                        ch_lines.append(body)
                        ch_lines.append("")

            chapter_parts.append("\n".join(ch_lines))

        title_line = f"# {topic.split(chr(10))[0].strip()}\n\n" if topic else ""
        toc = "\n".join(toc_lines)
        body = "\n\n".join(chapter_parts)

        seen: set[str] = set()
        unique_sources: list[str] = []
        for s in all_sources:
            if s not in seen:
                seen.add(s)
                unique_sources.append(s)

        sources_section = ""
        if unique_sources:
            sources_lines = ["## Sources", ""] + [f"- {s}" for s in unique_sources]
            sources_section = "\n\n" + "\n".join(sources_lines)

        result = f"{title_line}{toc}\n\n---\n\n{body}{sources_section}"

        if discussion_path is not None:
            try:
                disc = Path(discussion_path).read_text(encoding="utf-8").strip()
                disc_lines = disc.splitlines()
                if disc_lines and re.match(r"^#\s+", disc_lines[0]):
                    disc = "\n".join(disc_lines[1:]).lstrip()
                result += f"\n\n---\n\n{disc}"
            except Exception as exc:
                logger.warning("BookAssembleTool: failed to read discussion %s: %s", discussion_path, exc)

        return result

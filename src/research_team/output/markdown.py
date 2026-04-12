import os
from datetime import datetime
from pathlib import Path


class MarkdownOutput:
    def __init__(self, workspace_dir: str | None = None):
        self._workspace_dir = Path(workspace_dir or os.path.join(os.getcwd(), "workspace"))
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    def save(self, content: str, topic: str, report_type: str = "business") -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        slug = topic[:30].replace(" ", "_").replace("/", "-")
        filename = f"report_{slug}_{date_str}.md"
        output_path = self._workspace_dir / filename

        header = self._build_header(topic, report_type)
        full_content = f"{header}\n\n{content}"

        output_path.write_text(full_content, encoding="utf-8")
        return str(output_path)

    def _build_header(self, topic: str, report_type: str) -> str:
        date_str = datetime.now().strftime("%Y年%m月%d日")
        type_labels = {
            "business": "ビジネス報告",
            "academic": "学術レポート",
            "paper": "論文",
            "book": "書籍",
        }
        label = type_labels.get(report_type, "報告書")
        return f"# {topic}\n\n**形式:** {label}  \n**作成日:** {date_str}"

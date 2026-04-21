# Pattern B+フラグ：アーティファクト再利用＋セクション再調査 実装計画

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RunManifest によって WBS↔スペシャリスト↔アーティファクトの対応をプロジェクトレベルで永続化し、既存の調査データを再利用してレポートをスタイル変更・セクション再調査で更新できるようにする。

**Architecture:** RunManifest（JSON）を run ごとに生成し、スペシャリスト名 → アーティファクトパスのマッピングを保持する。RegenerateRequest フローが RunManifest を読み込み、再調査対象のスペシャリストのみ再実行する。ArtifactReconstructor が残りのアーティファクトを結合して combined_content を復元し、CSM 整形のみを再実行する。

**Tech Stack:** Python 3.11、dataclasses、pathlib、既存 pi-agent ブリッジ

---

## 変更ファイル一覧

| 種別 | ファイル | 変更内容 |
|------|---------|---------|
| 新規 | `src/research_team/output/run_manifest.py` | RunManifest dataclass + JSON 永続化 |
| 新規 | `src/research_team/output/artifact_reconstructor.py` | アーティファクトから combined_content を復元 |
| 修正 | `src/research_team/output/artifact_writer.py` | `write_run_manifest()` メソッド追加 |
| 修正 | `src/research_team/output/markdown.py` | `save()` に `output_path` 引数追加（上書きサポート） |
| 修正 | `src/research_team/orchestrator/coordinator.py` | `SessionState` 拡張、`RegenerateRequest`、`_run_regenerate()`、`run_interactive()` の intent 判定 |
| 修正 | `tests/unit/test_artifact_writer.py` | RunManifest 保存テスト追加 |
| 新規 | `tests/unit/test_run_manifest.py` | RunManifest の load/save テスト |
| 新規 | `tests/unit/test_artifact_reconstructor.py` | combined_content 復元テスト |
| 修正 | `tests/unit/test_markdown_output.py` | output_path 上書きテスト追加 |
| 修正 | `tests/unit/test_coordinator.py` | SessionState 拡張・intent 判定テスト追加 |

---

## Chunk 1: RunManifest — WBS↔スペシャリスト↔アーティファクト対応の永続化

### Task 1: RunManifest dataclass と JSON 永続化

**Files:**
- Create: `src/research_team/output/run_manifest.py`
- Create: `tests/unit/test_run_manifest.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_run_manifest.py
import json
from pathlib import Path
from research_team.output.run_manifest import RunManifest, SpecialistEntry


def test_run_manifest_save_and_load(tmp_path):
    entry = SpecialistEntry(
        name="経済アナリスト",
        expertise="経済・金融",
        artifact_path=str(tmp_path / "specialist_経済アナリスト_run1_20260420.md"),
    )
    manifest = RunManifest(
        run_id=1,
        topic="AI産業の未来",
        style="research_report",
        specialists=[entry],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report_AI産業_20260420.md"),
    )
    manifest_path = tmp_path / "manifest_run1.json"
    manifest.save(manifest_path)

    loaded = RunManifest.load(manifest_path)
    assert loaded.run_id == 1
    assert loaded.topic == "AI産業の未来"
    assert len(loaded.specialists) == 1
    assert loaded.specialists[0].name == "経済アナリスト"
    assert loaded.report_path == str(tmp_path / "report_AI産業_20260420.md")


def test_run_manifest_with_discussion(tmp_path):
    manifest = RunManifest(
        run_id=2,
        topic="テスト",
        style="magazine_column",
        specialists=[],
        discussion_artifact_path=str(tmp_path / "discussion_run2_20260420.md"),
        report_path=str(tmp_path / "report_test_20260420.md"),
    )
    manifest_path = tmp_path / "manifest_run2.json"
    manifest.save(manifest_path)
    loaded = RunManifest.load(manifest_path)
    assert loaded.discussion_artifact_path is not None
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
pytest tests/unit/test_run_manifest.py -v
```
期待: `ModuleNotFoundError: No module named 'research_team.output.run_manifest'`

- [ ] **Step 3: 実装**

```python
# src/research_team/output/run_manifest.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SpecialistEntry:
    name: str
    expertise: str
    artifact_path: str  # specialist_*.md の絶対パス


@dataclass
class RunManifest:
    run_id: int
    topic: str
    style: str
    specialists: list[SpecialistEntry]
    discussion_artifact_path: str | None
    report_path: str

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["specialists"] = [SpecialistEntry(**s) for s in data["specialists"]]
        return cls(**data)
```

- [ ] **Step 4: テスト実行（成功確認）**

```bash
pytest tests/unit/test_run_manifest.py -v
```
期待: 2 passed

- [ ] **Step 5: コミット**

```bash
git add src/research_team/output/run_manifest.py tests/unit/test_run_manifest.py
git commit -m "feat: add RunManifest for WBS-specialist-artifact mapping"
```

---

### Task 2: ArtifactWriter に write_run_manifest() を追加

**Files:**
- Modify: `src/research_team/output/artifact_writer.py`
- Modify: `tests/unit/test_artifact_writer.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/unit/test_artifact_writer.py` の末尾に追加：

```python
def test_write_run_manifest(tmp_path):
    from research_team.output.run_manifest import RunManifest
    writer = ArtifactWriter(tmp_path)
    specialists = [
        {"name": "経済アナリスト", "expertise": "経済・金融"},
        {"name": "技術者", "expertise": "AI・機械学習"},
    ]
    artifact_paths = {
        "経済アナリスト": str(tmp_path / "specialist_経済アナリスト_run1_20260420.md"),
        "技術者": str(tmp_path / "specialist_技術者_run1_20260420.md"),
    }
    report_path = str(tmp_path / "report_test_20260420.md")

    path = writer.write_run_manifest(
        run_id=1,
        topic="テスト",
        style="research_report",
        specialists=specialists,
        artifact_paths=artifact_paths,
        discussion_artifact_path=None,
        report_path=report_path,
    )

    manifest = RunManifest.load(Path(path))
    assert manifest.run_id == 1
    assert len(manifest.specialists) == 2
    assert manifest.specialists[0].artifact_path == artifact_paths["経済アナリスト"]
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
pytest tests/unit/test_artifact_writer.py::test_write_run_manifest -v
```
期待: `AttributeError: 'ArtifactWriter' object has no attribute 'write_run_manifest'`

- [ ] **Step 3: 実装を追加**

`artifact_writer.py` の `for_session()` の前に挿入：

```python
def write_run_manifest(
    self,
    run_id: int,
    topic: str,
    style: str,
    specialists: list[dict],
    artifact_paths: dict[str, str],
    discussion_artifact_path: str | None,
    report_path: str,
) -> str:
    from research_team.output.run_manifest import RunManifest, SpecialistEntry

    entries = [
        SpecialistEntry(
            name=s["name"],
            expertise=s["expertise"],
            artifact_path=artifact_paths.get(s["name"], ""),
        )
        for s in specialists
    ]
    manifest = RunManifest(
        run_id=run_id,
        topic=topic,
        style=style,
        specialists=entries,
        discussion_artifact_path=discussion_artifact_path,
        report_path=report_path,
    )
    path = self._dir / f"manifest_run{run_id}.json"
    manifest.save(path)
    return str(path)
```

- [ ] **Step 4: テスト実行（成功確認）**

```bash
pytest tests/unit/test_artifact_writer.py -v
```
期待: 全テスト passed

- [ ] **Step 5: コミット**

```bash
git add src/research_team/output/artifact_writer.py tests/unit/test_artifact_writer.py
git commit -m "feat: add write_run_manifest to ArtifactWriter"
```

---

## Chunk 2: ArtifactReconstructor — アーティファクトから combined_content を復元

### Task 3: ArtifactReconstructor の実装

**Files:**
- Create: `src/research_team/output/artifact_reconstructor.py`
- Create: `tests/unit/test_artifact_reconstructor.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_artifact_reconstructor.py
from pathlib import Path
from research_team.output.artifact_reconstructor import ArtifactReconstructor
from research_team.output.run_manifest import RunManifest, SpecialistEntry


def _write_specialist_file(path: Path, specialist_name: str, content: str) -> None:
    header = f"# 調査中間成果物 — {specialist_name} / Run 1 (20260420)\n\n"
    path.write_text(header + content, encoding="utf-8")


def test_reconstruct_combined_content_basic(tmp_path):
    # specialist ファイルを用意
    path_a = tmp_path / "specialist_経済アナリスト_run1_20260420.md"
    path_b = tmp_path / "specialist_技術者_run1_20260420.md"
    _write_specialist_file(path_a, "経済アナリスト", "## 経済アナリスト\n\n経済の分析内容")
    _write_specialist_file(path_b, "技術者", "## 技術者\n\n技術の分析内容")

    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="research_report",
        specialists=[
            SpecialistEntry("経済アナリスト", "経済・金融", str(path_a)),
            SpecialistEntry("技術者", "AI・機械学習", str(path_b)),
        ],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report.md"),
    )

    reconstructor = ArtifactReconstructor()
    combined = reconstructor.reconstruct(manifest)

    assert "経済の分析内容" in combined
    assert "技術の分析内容" in combined
    # specialist の順序が manifest の順序と一致
    assert combined.index("経済の分析内容") < combined.index("技術の分析内容")


def test_reconstruct_includes_discussion(tmp_path):
    path_a = tmp_path / "specialist_経済アナリスト_run1_20260420.md"
    _write_specialist_file(path_a, "経済アナリスト", "経済の内容")
    disc_path = tmp_path / "discussion_run1_20260420.md"
    disc_path.write_text("# 対談\n\n対談の内容", encoding="utf-8")

    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="magazine_column",
        specialists=[SpecialistEntry("経済アナリスト", "経済・金融", str(path_a))],
        discussion_artifact_path=str(disc_path),
        report_path=str(tmp_path / "report.md"),
    )

    reconstructor = ArtifactReconstructor()
    combined = reconstructor.reconstruct(manifest)

    assert "経済の内容" in combined
    assert "対談の内容" in combined


def test_reconstruct_missing_artifact_raises(tmp_path):
    import pytest
    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="research_report",
        specialists=[
            SpecialistEntry("経済アナリスト", "経済・金融", str(tmp_path / "nonexistent.md")),
        ],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report.md"),
    )
    reconstructor = ArtifactReconstructor()
    with pytest.raises(FileNotFoundError, match="nonexistent.md"):
        reconstructor.reconstruct(manifest)
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
pytest tests/unit/test_artifact_reconstructor.py -v
```
期待: `ModuleNotFoundError`

- [ ] **Step 3: 実装**

```python
# src/research_team/output/artifact_reconstructor.py
from __future__ import annotations

from pathlib import Path

from research_team.output.run_manifest import RunManifest

_HEADER_LINES = 2  # "# 調査中間成果物 — ..." + 空行


class ArtifactReconstructor:
    """RunManifest のアーティファクトから combined_content を再構成する。"""

    def reconstruct(self, manifest: RunManifest) -> str:
        sections: list[str] = []

        for entry in manifest.specialists:
            path = Path(entry.artifact_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"スペシャリストアーティファクトが見つかりません: {entry.artifact_path}"
                )
            raw = path.read_text(encoding="utf-8")
            # ヘッダー行（"# 調査中間成果物 — ..." + 空行）を除去
            lines = raw.split("\n")
            body = "\n".join(lines[_HEADER_LINES:]).strip()
            sections.append(body)

        combined = "\n\n".join(sections)

        if manifest.discussion_artifact_path:
            disc_path = Path(manifest.discussion_artifact_path)
            if disc_path.exists():
                combined += "\n\n---\n\n" + disc_path.read_text(encoding="utf-8").strip()

        return combined
```

- [ ] **Step 4: テスト実行（成功確認）**

```bash
pytest tests/unit/test_artifact_reconstructor.py -v
```
期待: 3 passed

- [ ] **Step 5: コミット**

```bash
git add src/research_team/output/artifact_reconstructor.py tests/unit/test_artifact_reconstructor.py
git commit -m "feat: add ArtifactReconstructor to restore combined_content from artifacts"
```

---

## Chunk 3: MarkdownOutput 上書きサポートと Coordinator 統合

### Task 4: MarkdownOutput.save() に output_path 引数を追加

**Files:**
- Modify: `src/research_team/output/markdown.py`
- Modify: `tests/unit/test_markdown_output.py`（存在する場合）

- [ ] **Step 1: 既存テストを確認**

```bash
pytest tests/unit/ -k "markdown" -v
```

- [ ] **Step 2: 上書きテストを追加**

```python
def test_save_with_existing_path_overwrites(tmp_path):
    existing = tmp_path / "existing_report.md"
    existing.write_text("古いコンテンツ", encoding="utf-8")

    output = MarkdownOutput(tmp_path)
    path = output.save("新しいコンテンツ", "テスト", output_path=existing)

    assert path == str(existing)
    assert "新しいコンテンツ" in existing.read_text(encoding="utf-8")
    assert "古いコンテンツ" not in existing.read_text(encoding="utf-8")
```

- [ ] **Step 3: テスト実行（失敗確認）**

```bash
pytest tests/unit/ -k "markdown" -v
```
期待: `TypeError: save() got an unexpected keyword argument 'output_path'`

- [ ] **Step 4: 実装**

`markdown.py` の `save()` シグネチャを変更：

```python
def save(
    self,
    content: str,
    topic: str,
    report_type: str = "business",
    output_path: Path | str | None = None,
) -> str:
    if output_path is not None:
        final_path = Path(output_path)
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        slug = _make_title(topic).replace(" ", "_").replace("/", "-").replace("…", "")
        filename = f"report_{slug}_{date_str}.md"
        final_path = self._workspace_dir / filename

    body, sources_section = self._collect_sources(content)
    header = self._build_header(topic, report_type)
    parts = [header, body]
    if sources_section:
        parts.append(sources_section)
    full_content = "\n\n".join(parts)

    final_path.write_text(full_content, encoding="utf-8")
    return str(final_path)
```

- [ ] **Step 5: テスト実行（成功確認）**

```bash
pytest tests/unit/ -k "markdown" -v
```
期待: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/output/markdown.py tests/unit/
git commit -m "feat: support output_path override in MarkdownOutput.save()"
```

---

### Task 5: Coordinator への RunManifest 記録の統合

既存の `_run_research()` 完了時に RunManifest を保存し、`SessionState` に `last_run_id` を追加する。

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`
- Modify: `tests/unit/test_coordinator.py`

- [ ] **Step 1: SessionState に last_run_id を追加**

`coordinator.py` の `SessionState` を変更：

```python
@dataclass
class SessionState:
    current_topic: str = ""
    last_report_path: str = ""
    last_run_id: int = 0        # 追加
    session_id: str = ""
```

- [ ] **Step 2: _run_specialist_pass がアーティファクトパスを返すよう修正**

現在 `_run_specialist_pass()` は `str`（combined_content）を返す。アーティファクトパスも返す必要がある。

戻り値を `tuple[str, dict[str, str]]`（combined_content, {specialist_name: artifact_path}）に変更する。

`coordinator.py` の `_run_specialist_pass()` の末尾付近を確認して修正：

```python
# _run_specialist_pass の戻り値を変更
async def _run_specialist_pass(
    self,
    factory,
    topic,
    feedback,
    reference_content,
    run_id,
    artifact_writer,
    style,
) -> tuple[str, dict[str, str]]:   # ← str から tuple に変更
    ...
    # 既存のセクション収集ループ内で artifact_paths を追跡
    artifact_paths: dict[str, str] = {}
    for name, section in zip(names, sections):
        path = artifact_writer.write_specialist_draft(run_id, name, section)
        artifact_paths[name] = path
    ...
    return "\n\n".join(combined_sections), artifact_paths
```

> **注意:** `_run_specialist_pass()` の実際の実装（行 714〜746 付近）を読んで、既存の `artifact_writer.write_specialist_draft()` 呼び出し箇所を確認してから修正すること。

- [ ] **Step 3: _run_research() の最終部に RunManifest 保存を追加**

`MarkdownOutput.save()` の直後：

```python
output_path = MarkdownOutput(self._get_agent_workspace()).save(
    combined_content, topic, report_type=request.style
)

# RunManifest を保存
try:
    artifact_writer.write_run_manifest(
        run_id=run_id,
        topic=topic,
        style=request.style,
        specialists=specialists,
        artifact_paths=specialist_artifact_paths,   # Task 5-Step 2 で取得
        discussion_artifact_path=discussion_artifact_path,  # 既存変数
        report_path=output_path,
    )
except Exception as exc:
    logger.warning("write_run_manifest failed: %s", exc)
```

- [ ] **Step 4: run_interactive() で last_run_id を更新**

```python
result = await self.run(request, run_id=run_id, session_id=session.session_id)
session.current_topic = topic
session.last_report_path = result.output_path
session.last_run_id = run_id           # 追加
```

- [ ] **Step 5: テスト実行**

```bash
pytest tests/unit/ -x -q
```
期待: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat: record RunManifest and last_run_id after each research run"
```

---

## Chunk 4: RegenerateRequest フロー — B+フラグの本体

### Task 6: RegenerateRequest と _run_regenerate() の実装

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`
- Modify: `tests/unit/test_coordinator.py`

- [ ] **Step 1: RegenerateRequest dataclass を追加**

`ResearchResult` の定義の後に追加：

```python
@dataclass
class RegenerateRequest:
    """既存 run のアーティファクトを再利用してレポートを再生成する。"""
    run_id: int
    artifacts_dir: str          # manifest_run{N}.json の親ディレクトリ
    re_research_specialists: list[str]  # 再調査対象のスペシャリスト名（空=整形のみ）
    style: str | None = None    # None = manifest の style を引き継ぐ
    overwrite_report: bool = True
```

- [ ] **Step 2: _run_regenerate() のテストを書く**

```python
# tests/unit/test_coordinator.py に追加
def test_parse_regenerate_intent():
    from research_team.orchestrator.coordinator import _parse_regenerate_intent
    # 整形のみ
    result = _parse_regenerate_intent("コラム形式に変えて", last_run_id=1)
    assert result is not None
    assert result.re_research_specialists == []

    # セクション再調査
    result = _parse_regenerate_intent("経済アナリストのセクションを深掘りして", last_run_id=1)
    assert result is not None
    assert "経済アナリスト" in result.re_research_specialists

    # 新規テーマ（RegenerateRequest を返さない）
    result = _parse_regenerate_intent("量子コンピュータについて調査して", last_run_id=1)
    assert result is None
```

- [ ] **Step 3: _parse_regenerate_intent() を実装**

```python
def _parse_regenerate_intent(text: str, last_run_id: int) -> "RegenerateRequest | None":
    """
    ユーザー入力が既存レポートへの修正依頼かどうかを判定する。
    修正依頼なら RegenerateRequest を返し、新規テーマなら None を返す。
    """
    _REGEN_KEYWORDS = [
        "変えて", "修正して", "直して", "書き直して",
        "形式に", "スタイルを", "再整形", "深掘り",
        "このレポート", "前のレポート", "さっきのレポート",
        "このセクション", "この節", "もっと詳しく",
    ]
    normalized = text.strip()
    if last_run_id == 0:
        return None
    if any(kw in normalized for kw in _REGEN_KEYWORDS):
        # スペシャリスト名が含まれているか（再調査フラグ）
        # 実際のスペシャリスト名はマニフェストからしか取れないため、
        # ここでは空リストを返し、呼び出し側でマニフェストと照合する
        return RegenerateRequest(
            run_id=last_run_id,
            artifacts_dir="",  # 呼び出し側で設定
            re_research_specialists=[],
        )
    return None
```

> **注意:** このキーワードベースの判定は最初の実装として十分。将来的に LLM による意図分類に置き換え可能。

- [ ] **Step 4: _run_regenerate() を実装**

`coordinator.py` に追加：

```python
async def _run_regenerate(
    self,
    request: RegenerateRequest,
    regen_request_text: str,
    session_id: str,
) -> ResearchResult:
    from research_team.output.run_manifest import RunManifest
    from research_team.output.artifact_reconstructor import ArtifactReconstructor

    manifest_path = Path(request.artifacts_dir) / f"manifest_run{request.run_id}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"RunManifest が見つかりません: {manifest_path}")

    manifest = RunManifest.load(manifest_path)
    style = request.style or manifest.style
    topic = manifest.topic

    # 再調査対象スペシャリストの artifact を更新
    if request.re_research_specialists:
        artifact_writer = ArtifactWriter(Path(request.artifacts_dir))
        factory = DynamicAgentFactory()
        for entry in manifest.specialists:
            if entry.name in request.re_research_specialists:
                factory.create_specialist(
                    name=entry.name,
                    expertise=entry.expertise,
                    system_prompt=f"あなたは{entry.expertise}の専門家です。{topic}について調査します。",
                    locales=["ja", "en"],
                )
        new_content, new_paths = await self._run_specialist_pass(
            factory, topic, None, "", run_id=request.run_id,
            artifact_writer=artifact_writer, style=style,
        )
        # manifest の artifact_path を更新
        for entry in manifest.specialists:
            if entry.name in new_paths:
                entry.artifact_path = new_paths[entry.name]

    # combined_content を再構成
    reconstructor = ArtifactReconstructor()
    combined_content = reconstructor.reconstruct(manifest)

    # CSM 整形
    if style in _STYLES_WITHOUT_EXEC_SUMMARY:
        format_prompt = self._build_format_prompt(topic, combined_content, style)
        formatted = await self._stream_agent_output(self._csm, format_prompt, "CSM")
        if formatted:
            combined_content = formatted
    else:
        summary_prompt = self._build_summary_prompt(topic, combined_content)
        exec_summary = await self._stream_agent_output(self._csm, summary_prompt, "CSM")
        if exec_summary:
            combined_content = (
                f"## エグゼクティブサマリー\n\n{exec_summary}\n\n---\n\n{combined_content}"
            )

    # 上書き or 新規保存
    output_path_arg = Path(manifest.report_path) if request.overwrite_report else None
    output_path = MarkdownOutput(self._get_agent_workspace()).save(
        combined_content, topic, report_type=style, output_path=output_path_arg
    )

    return ResearchResult(
        content=combined_content,
        output_path=output_path,
        quality_score=1.0,
        iterations=0,
    )
```

- [ ] **Step 5: テスト実行**

```bash
pytest tests/unit/ -x -q
```
期待: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "feat: add RegenerateRequest and _run_regenerate() for artifact reuse flow"
```

---

### Task 7: run_interactive() の intent 判定に再生成フローを組み込む

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`

- [ ] **Step 1: run_interactive() のループ内に分岐を追加**

```python
# run_interactive() の既存ループ内、topic 取得後

regen = _parse_regenerate_intent(topic, last_run_id=session.last_run_id)
if regen is not None and session.last_run_id > 0:
    # artifacts_dir を設定（session_id から ArtifactWriter と同じパスを算出）
    artifact_writer = self._make_artifact_writer(session.session_id)
    regen.artifacts_dir = str(artifact_writer._dir)
    try:
        result = await self._run_regenerate(regen, topic, session.session_id)
        session.last_report_path = result.output_path
        await self._notify("CSM", f"✅ レポートを更新しました:\n`{result.output_path}`")
    except Exception as exc:
        await self._notify("CSM", f"⚠️ 再生成に失敗しました: {exc}\n新規調査として実行します。")
        # フォールバック: 通常の新規調査
        result = await self.run(
            ResearchRequest(topic=topic, depth=depth, output_format=output_format),
            run_id=run_id,
            session_id=session.session_id,
        )
        session.last_report_path = result.output_path
        session.last_run_id = run_id
else:
    # 既存の通常フロー
    result = await self.run(...)
```

- [ ] **Step 2: テスト実行**

```bash
pytest tests/unit/ -x -q
```
期待: 全テスト passed

- [ ] **Step 3: 全テスト実行（最終確認）**

```bash
pytest tests/unit/ -x -q
```
出力を確認し、0 failures であることを確認する。

- [ ] **Step 4: 最終コミット**

```bash
git add src/research_team/orchestrator/coordinator.py
git commit -m "feat: integrate regenerate intent detection into run_interactive loop"
git push
```

---

## 制約・注意事項

### スペシャリスト再調査フラグの限界
- `_parse_regenerate_intent()` は現在キーワードベース。「経済アナリストを」という文字列が含まれる場合のみ検出できる
- スペシャリスト名とユーザー発話の照合は `_run_regenerate()` 側で RunManifest を使って行う（この計画では最初の実装として空リストで整形のみ対応）
- フェーズ2として LLM による intent 分類（スペシャリスト名抽出込み）に置き換え可能

### `_run_specialist_pass()` の戻り値変更
- Task 5-Step 2 で戻り値を `tuple[str, dict]` に変えるため、品質ループ内の呼び出し箇所（`run_research()` ネスト関数）も修正が必要
- 修正前に `grep -n "_run_specialist_pass" coordinator.py` で全呼び出し箇所を確認すること

### 既存テストへの影響
- `_run_specialist_pass()` の戻り値変更により、既存のモックテストが壊れる可能性がある
- Task 5 の後に `pytest tests/unit/ -x -q` を必ず実行し、壊れたテストを先に直すこと

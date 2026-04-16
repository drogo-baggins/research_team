# Reference Files Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI `--reference-files` オプションと Excel 読み込み対応を追加し、タスク 1-4・1-5 を完成させる。

**Architecture:** `_load_reference_files()` を拡張して `.xlsx`/`.xls` をテキスト変換し、`cli/main.py` に `--reference-files` オプションを追加して `run_interactive()` 経由で `ResearchRequest` に渡す。UI なし（`else` ブランチ）にも同じパスを通す。

**Tech Stack:** Python 3.11+、openpyxl（既存依存）、typer（既存依存）

---

## Chunk 1: Excel 読み込み対応

### Task 1: `_load_reference_files()` に Excel 対応を追加

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py:88-95`
- Test: `tests/unit/test_us1.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_us1.py` の末尾に追加（既存の `test_research_request_with_reference_file_passes_content_to_task` の直後あたり）：

```python
def test_load_reference_files_reads_xlsx(tmp_path):
    """xlsx ファイルがテキストに変換されてロードされる"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["名前", "予算", "備考"])
    ws.append(["XYZプロジェクト", "100億円", "重要案件"])
    xlsx_path = tmp_path / "data.xlsx"
    wb.save(str(xlsx_path))

    from research_team.orchestrator.coordinator import _load_reference_files
    result = _load_reference_files([str(xlsx_path)])

    assert "XYZプロジェクト" in result
    assert "100億円" in result
    assert "重要案件" in result


def test_load_reference_files_reads_xlsx_multiple_sheets(tmp_path):
    """複数シートを持つ xlsx ファイルの全シートが読み込まれる"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "シートA"
    ws1.append(["データA"])
    ws2 = wb.create_sheet("シートB")
    ws2.append(["データB"])
    xlsx_path = tmp_path / "multi.xlsx"
    wb.save(str(xlsx_path))

    from research_team.orchestrator.coordinator import _load_reference_files
    result = _load_reference_files([str(xlsx_path)])

    assert "データA" in result
    assert "データB" in result


def test_load_reference_files_unsupported_extension_raises(tmp_path):
    """未対応の拡張子ではエラーになる"""
    bad_file = tmp_path / "data.pdf"
    bad_file.write_bytes(b"%PDF-1.4 fake content")

    from research_team.orchestrator.coordinator import _load_reference_files
    with pytest.raises(ValueError, match="未対応のファイル形式"):
        _load_reference_files([str(bad_file)])
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/unit/test_us1.py::test_load_reference_files_reads_xlsx -v
```

Expected: FAIL（`UnicodeDecodeError` または `ValueError`）

- [ ] **Step 3: `_load_reference_files()` を実装**

`src/research_team/orchestrator/coordinator.py` の `_load_reference_files()` を以下で置き換える：

```python
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".rst"}
_EXCEL_EXTENSIONS = {".xlsx", ".xls"}


def _load_reference_files(paths: list[str]) -> str:
    parts: list[str] = []
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"参照ファイルが見つかりません: {path}")
        ext = os.path.splitext(path)[1].lower()
        if ext in _EXCEL_EXTENSIONS:
            parts.append(_load_excel(path))
        elif ext in _TEXT_EXTENSIONS or ext == "":
            with open(path, encoding="utf-8") as f:
                parts.append(f.read())
        else:
            raise ValueError(f"未対応のファイル形式です: {ext}（対応: {sorted(_TEXT_EXTENSIONS | _EXCEL_EXTENSIONS)}）")
    return "\n\n".join(parts)


def _load_excel(path: str) -> str:
    """Excel ファイルを読み込み、全シートをテキスト形式に変換する"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet_texts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: list[str] = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(cell) if cell is not None else "" for cell in row]
            if any(c.strip() for c in cells):  # 空行はスキップ
                rows.append("\t".join(cells))
        if rows:
            sheet_texts.append(f"[シート: {sheet_name}]\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(sheet_texts)
```

ファイル先頭の `import os` はすでにあるため追加不要。

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/unit/test_us1.py::test_load_reference_files_reads_xlsx tests/unit/test_us1.py::test_load_reference_files_reads_xlsx_multiple_sheets tests/unit/test_us1.py::test_load_reference_files_unsupported_extension_raises -v
```

Expected: 3 passed

- [ ] **Step 5: 既存テストが壊れていないことを確認**

```
pytest tests/unit/test_us1.py -v
```

Expected: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py tests/unit/test_us1.py
git commit -m "feat: add Excel support to _load_reference_files (task 1-5)"
```

---

## Chunk 2: CLI `--reference-files` オプション追加

### Task 2: `run_interactive()` に `reference_files` パラメータを追加

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py:330-372`
- Test: `tests/unit/test_us1.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_us1.py` に追加：

```python
@pytest.mark.asyncio
async def test_run_interactive_passes_reference_files_to_run(tmp_path):
    """run_interactive に渡した reference_files が run() に届く"""
    ref_file = tmp_path / "ref.txt"
    ref_file.write_text("参照情報テスト", encoding="utf-8")

    ui = _make_mock_ui()
    # テーマ入力 → 「はい」の順でキューに積む
    ui.wait_for_user_message = AsyncMock(side_effect=["テストテーマ", "はい"])

    coord = ResearchCoordinator(workspace_dir=str(tmp_path), ui=ui)

    captured_request: list[ResearchRequest] = []

    async def fake_run(request: ResearchRequest) -> ResearchResult:
        captured_request.append(request)
        from research_team.orchestrator.coordinator import ResearchResult
        return ResearchResult(
            content="調査結果 " * 100,
            output_path=str(tmp_path / "report.md"),
            quality_score=1.0,
            iterations=1,
        )

    with patch.object(coord, "run", side_effect=fake_run):
        await coord.run_interactive(
            depth="quick",
            reference_files=[str(ref_file)],
        )

    assert len(captured_request) == 1
    assert captured_request[0].reference_files == [str(ref_file)]
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/unit/test_us1.py::test_run_interactive_passes_reference_files_to_run -v
```

Expected: FAIL（`TypeError: run_interactive() got an unexpected keyword argument 'reference_files'`）

- [ ] **Step 3: `run_interactive()` に `reference_files` 引数を追加**

`coordinator.py` の `run_interactive` シグネチャと `ResearchRequest` 生成箇所を修正：

```python
async def run_interactive(
    self,
    depth: str = "standard",
    output_format: str = "markdown",
    reference_files: list[str] | None = None,
) -> None:
    # ... （既存の確認フローはそのまま） ...

    request = ResearchRequest(
        topic=topic,
        depth=depth,
        output_format=output_format,
        reference_files=reference_files or [],
    )
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/unit/test_us1.py::test_run_interactive_passes_reference_files_to_run -v
```

Expected: PASS

- [ ] **Step 5: 全テストが壊れていないことを確認**

```
pytest tests/unit/test_us1.py -v
```

Expected: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/orchestrator/coordinator.py tests/unit/test_us1.py
git commit -m "feat: add reference_files param to run_interactive (task 1-4)"
```

---

### Task 3: CLI に `--reference-files` オプションを追加

**Files:**
- Modify: `src/research_team/cli/main.py:16-63`
- Test: `tests/unit/test_us1.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_us1.py` に追加：

```python
def test_start_cli_accepts_reference_files(tmp_path):
    """CLI の start コマンドが --reference-files オプションを受け付ける"""
    from typer.testing import CliRunner
    from research_team.cli.main import app

    ref_file = tmp_path / "ref.txt"
    ref_file.write_text("テスト参照", encoding="utf-8")

    runner = CliRunner()
    # --help でオプション一覧を確認（実際には起動しない）
    result = runner.invoke(app, ["start", "--help"])
    assert "--reference-files" in result.output
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/unit/test_us1.py::test_start_cli_accepts_reference_files -v
```

Expected: FAIL（`--reference-files` が help に出ない）

- [ ] **Step 3: `cli/main.py` に `--reference-files` オプションを追加**

```python
@app.command("start")
def start(
    depth: str = typer.Option("standard", help="調査の深さ: quick|standard|deep"),
    search_mode: Optional[str] = typer.Option(None, help="検索モード: human|tavily|serper"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
    output_format: str = typer.Option("markdown", help="出力形式: markdown|pdf|excel"),
    reference_files: Optional[list[str]] = typer.Option(
        None,
        "--reference-files",
        help="調査の参照ファイルパス（複数指定可、テキスト/.xlsx対応）",
    ),
):
```

`coordinator.run_interactive()` の呼び出し箇所も更新：

```python
await coordinator.run_interactive(
    depth=depth,
    output_format=output_format,
    reference_files=reference_files or [],
)
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/unit/test_us1.py::test_start_cli_accepts_reference_files -v
```

Expected: PASS

- [ ] **Step 5: 全テスト（unit）が通ることを確認**

```
pytest tests/unit/ -v
```

Expected: 全テスト passed

- [ ] **Step 6: コミット**

```bash
git add src/research_team/cli/main.py tests/unit/test_us1.py
git commit -m "feat: add --reference-files CLI option (task 1-4)"
```

---

## Chunk 3: ドキュメント更新

### Task 4: `tasks.md` と `us1_guide.md` を更新

**Files:**
- Modify: `docs/tasks.md`
- Modify: `docs/us1_guide.md`

- [ ] **Step 1: `tasks.md` のタスク 1-4・1-5 を ✅ に更新**

```markdown
| 1-4 | 参照ファイル（テキスト）を調査入力として渡せる | ✅ 実装済 |
| 1-5 | 参照ファイルとして Excel（`.xlsx`）を渡せる | ✅ 実装済 |
```

- [ ] **Step 2: `us1_guide.md` の参照ファイルセクションを更新**

Part 1（ユーザー向け）の「起動方法」の CLI オプション表を更新：

```markdown
| `--reference-files` | ファイルパス（複数可） | なし | 調査の参照資料（テキスト / `.xlsx` 対応） |
```

「操作手順」の「Step 1: 起動」直前に以下のセクションを追加：

```markdown
#### （任意）参照資料を使った調査

調査前に背景情報・前提条件などを記したファイルを渡すと、エージェントがそれを踏まえて調査を行います。

```bash
# テキストファイルを参照資料として渡す
python -m research_team.cli.main start --depth standard --reference-files background.txt

# 複数ファイル・Excel も指定可能
python -m research_team.cli.main start --depth standard \
  --reference-files context.txt \
  --reference-files data.xlsx
```

- `.txt`、`.md`、`.csv` 等のテキスト形式と `.xlsx`（Excel）に対応
- Excel は全シートのセル内容がテキストに変換されて渡されます
- ファイルが存在しない場合はエラーになります
```

Part 2（管理者向け）の参照ファイル実装状況テーブルをすべて ✅ に更新。

- [ ] **Step 3: コミット**

```bash
git add docs/tasks.md docs/us1_guide.md
git commit -m "docs: update reference files status to implemented"
```

---

## 完了確認

全タスク完了後、以下を確認：

```bash
# 全ユニットテスト
pytest tests/unit/ -v

# CLI ヘルプで --reference-files が表示されることを確認
python -m research_team.cli.main start --help
```

`tasks.md` の US-1 が以下の状態になっていること：

| # | タスク | 状態 |
|---|---|---|
| 1-1 | CSM が冒頭でテーマを受け付ける | ✅ |
| 1-2 | 深さオプション CLI 指定 | ✅ |
| 1-3 | CSM 確認フロー | ✅ |
| 1-4 | 参照ファイル（テキスト）CLI 対応 | ✅ |
| 1-5 | 参照ファイル Excel 対応 | ✅ |

# Run-Level Selection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 変更モードのセッション選択単位を「セッションフォルダー（最新run代表）」から「run単位（= 調査テーマ1件）」に変更し、同一フォルダー内の複数テーマを個別に変更依頼できるようにする。

**Architecture:**
- `list_completed_sessions()` の重複排除ロジック（`best` dict）を廃止し、全 run を列挙する
- UIへの選択キーを `session_id`（フォルダー名）から `run_key`（`{session_id}::run{run_id}` 形式）に変更し、`CompletedSession` から逆引きできるようにする
- `wait_for_session_selection()` および JS の `session_selected` シグナルは文字列キーのまま。型変更なし。

**Tech Stack:** Python 3.11, asyncio, Playwright (HTML/JS UI)

---

## ファイルマップ

| ファイル | 変更内容 |
|---|---|
| `src/research_team/orchestrator/coordinator.py` | `list_completed_sessions()` 重複排除廃止、`run_key` 追加、`_list_sessions_for_ui()` / `_run_modify_session()` 対応 |
| `src/research_team/ui/control_page.html` | `_buildSessionRow` のクリックシグナルを `run_key` に変更、styleLabel に `paper` 追加 |
| `src/research_team/ui/control_ui.py` | `wait_for_session_selection()` 戻り値型コメント更新のみ（実装変更なし） |
| `tests/unit/test_run_level_selection.py` | 新規作成 |

---

## Chunk 1: バックエンド — list_completed_sessions を run 列挙に変更

### Task 1: テストを先に書く

**Files:**
- Create: `tests/unit/test_run_level_selection.py`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_run_level_selection.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from research_team.orchestrator.coordinator import ResearchCoordinator


def _make_manifest(tmp_path: Path, session_name: str, run_id: int, topic: str) -> Path:
    artifacts = tmp_path / "sessions" / session_name / "artifacts"
    artifacts.mkdir(parents=True)
    manifest = artifacts / f"manifest_run{run_id}.json"
    manifest.write_text(json.dumps({
        "run_id": run_id,
        "topic": topic,
        "style": "research_report",
        "report_path": "",
    }), encoding="utf-8")
    return manifest


def _make_coordinator(tmp_path: Path) -> ResearchCoordinator:
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    return coord


def test_list_completed_sessions_returns_all_runs(tmp_path):
    """同一フォルダー内の複数 run が全件返される（重複排除なし）"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_テーマA", 2, "テーマB")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 2
    topics = {s.topic for s in sessions}
    assert topics == {"テーマA", "テーマB"}


def test_list_completed_sessions_run_key_format(tmp_path):
    """run_key が '{session_id}::run{run_id}' 形式で設定される"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 1
    assert sessions[0].run_key == "20260425_テーマA::run1"


def test_list_sessions_for_ui_includes_run_key(tmp_path):
    """_list_sessions_for_ui の各エントリに run_key が含まれる"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_テーマA", 2, "テーマB")

    coord = _make_coordinator(tmp_path)
    ui_list = coord._list_sessions_for_ui()

    assert len(ui_list) == 2
    run_keys = {e["run_key"] for e in ui_list}
    assert "20260425_テーマA::run1" in run_keys
    assert "20260425_テーマA::run2" in run_keys


def test_list_completed_sessions_different_folders(tmp_path):
    """異なるフォルダーの run も全件返される"""
    _make_manifest(tmp_path, "20260425_フォルダA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_フォルダB", 1, "テーマB")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 2
```

- [ ] **Step 2: テストが失敗することを確認**

```
python -m pytest tests/unit/test_run_level_selection.py -x -q
```

Expected: FAIL（`run_key` 属性が存在しない、重複排除されて1件しか返らない）

---

### Task 2: `CompletedSession` に `run_key` を追加

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py:70-82`

- [ ] **Step 3: `CompletedSession` に `run_key` フィールドを追加**

`coordinator.py` の `CompletedSession` dataclass に `run_key: str = ""` を追加する。

```python
@dataclass
class CompletedSession:
    session_id: str
    topic: str
    run_id: int
    style: str
    created_at: str
    artifacts_dir: Path
    manifest_path: Path
    report_path: str = ""
    run_key: str = ""        # ← 追加: "{session_id}::run{run_id}"
    project_id: str | None = None
    project_topic: str | None = None
```

---

### Task 3: `list_completed_sessions()` の重複排除を廃止

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py:1767-1830`

- [ ] **Step 4: `sessions` 型を `list` に変更し、`best` dict を廃止**

変更前（重複排除あり）:
```python
def list_completed_sessions(self) -> list[CompletedSession]:
    best: dict[str, CompletedSession] = {}
    ...
    existing = best.get(session_id)
    if existing is None or run_id > existing.run_id:
        best[session_id] = CompletedSession(...)
    ...
    return sorted(best.values(), ...)
```

変更後（全 run 列挙）:
```python
def list_completed_sessions(self) -> list[CompletedSession]:
    results: list[CompletedSession] = []
    
    sessions_dir = Path(self._workspace_dir) / "sessions"
    if sessions_dir.exists():
        for manifest_path in sessions_dir.glob("*/artifacts/manifest_run*.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                session_id = manifest_path.parent.parent.name
                run_id = data.get("run_id", 1)
                results.append(CompletedSession(
                    session_id=session_id,
                    topic=data.get("topic", ""),
                    run_id=run_id,
                    run_key=f"{session_id}::run{run_id}",
                    style=data.get("style", "research_report"),
                    created_at=datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    artifacts_dir=manifest_path.parent,
                    manifest_path=manifest_path,
                    report_path=data.get("report_path", ""),
                ))
            except Exception:
                continue

    projects_dir = Path(self._workspace_dir) / "projects"
    if projects_dir.exists():
        for manifest_path in projects_dir.glob("*/files/artifacts/manifest_run*.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                project_id = manifest_path.parent.parent.parent.name
                session_id = f"project:{project_id}"
                run_id = data.get("run_id", 1)
                project_topic = ""
                try:
                    meta_path = manifest_path.parent.parent.parent / "meta.json"
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        project_topic = meta.get("topic", "")
                except Exception:
                    pass
                results.append(CompletedSession(
                    session_id=session_id,
                    topic=data.get("topic", ""),
                    run_id=run_id,
                    run_key=f"{session_id}::run{run_id}",
                    style=data.get("style", "research_report"),
                    created_at=datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    artifacts_dir=manifest_path.parent,
                    manifest_path=manifest_path,
                    report_path=data.get("report_path", ""),
                    project_id=project_id,
                    project_topic=project_topic,
                ))
            except Exception:
                continue

    return sorted(results, key=lambda s: s.created_at, reverse=True)
```

---

### Task 4: `_list_sessions_for_ui()` と `_run_modify_session()` を `run_key` 対応に変更

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`

- [ ] **Step 5: `_list_sessions_for_ui()` に `run_key` を追加**

```python
def _list_sessions_for_ui(self) -> list[dict]:
    return [
        {
            "run_key": s.run_key,       # ← 追加
            "session_id": s.session_id,
            "topic": s.topic,
            "style": s.style,
            "created_at": s.created_at,
            "report_path": s.report_path,
            "project_id": s.project_id,
            "project_topic": s.project_topic,
        }
        for s in self.list_completed_sessions()
    ]
```

- [ ] **Step 6: `_run_modify_session()` の選択照合を `run_key` に変更**

変更前:
```python
session_id = await self._ui.wait_for_session_selection()
chosen = next((s for s in completed if s.session_id == session_id), None)
```

変更後:
```python
run_key = await self._ui.wait_for_session_selection()
chosen = next((s for s in completed if s.run_key == run_key), None)
```

同様に `_run_modify_mode()` 内の同パターンも変更（grep で確認）。

---

### Task 5: テスト実行・コミット

- [ ] **Step 7: テスト実行**

```
python -m pytest tests/unit/test_run_level_selection.py -x -q
```

Expected: 4 passed

- [ ] **Step 8: 全テスト実行**

```
python -m pytest tests/unit/ -x -q
```

Expected: all passed

- [ ] **Step 9: コミット**

```
git add src/research_team/orchestrator/coordinator.py tests/unit/test_run_level_selection.py
git commit -m "feat: enumerate all runs in list_completed_sessions, add run_key field"
```

---

## Chunk 2: フロントエンド — JS シグナルを run_key に変更

### Task 6: `control_page.html` の session_selected シグナルを run_key に変更

**Files:**
- Modify: `src/research_team/ui/control_page.html`

- [ ] **Step 10: `_buildSessionRow` のクリックハンドラーを変更**

変更前:
```javascript
window.__rt_signal({ type: 'session_selected', session_id: s.session_id });
```

変更後:
```javascript
window.__rt_signal({ type: 'session_selected', session_id: s.run_key });
```

（フィールド名 `session_id` はシグナルプロトコルの後方互換のため変えない。値だけ `run_key` に差し替える）

- [ ] **Step 11: styleLabel に `paper` を追加**

```javascript
const styleLabel = {
  research_report: 'レポート',
  executive_memo: 'メモ',
  magazine_column: 'コラム',
  book_chapter: '書籍',
  paper: '論文'       // ← 追加
}[s.style] || s.style;
```

- [ ] **Step 12: 全テスト実行**

```
python -m pytest tests/unit/ -x -q
```

- [ ] **Step 13: コミット**

```
git add src/research_team/ui/control_page.html
git commit -m "feat: use run_key as session selection signal value, add paper style label"
```

---

## 完了条件チェックリスト

- [ ] `list_completed_sessions()` が同一フォルダー内の複数 run を全件返す
- [ ] `CompletedSession.run_key` が `{session_id}::run{run_id}` 形式で設定される
- [ ] 変更モードの選択リストに同一フォルダー内の複数テーマが個別表示される
- [ ] 選択した run のレポートが変更対象として正しく読み込まれる
- [ ] 全ユニットテスト通過

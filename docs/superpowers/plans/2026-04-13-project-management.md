# Project Management (archive / switch / init) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project archive, switch, and init operations with project-scoped directory isolation so agents can only access the active project's files.

**Architecture:** `ProjectManager` owns the canonical directory layout (`workspace/projects/{id}/{meta,checkpoints/,files/,audit.log}`) and `.active_project` persistence. `ResearchCoordinator` reads the active project and passes `project_files_dir` (not workspace root) to agents and `MarkdownOutput`. Migration is compatibility-first: legacy `workspace/projects/{id}.json` and `{id}_checkpoints/` are read transparently; all new writes go to the new layout.

**Tech Stack:** Python 3.12, pydantic v2, pytest + tmp_path, asyncio

---

## Background

### Current layout (legacy)
```
workspace/
  projects/
    {id}.json
    {id}_checkpoints/
      {label}.json
  report_*.md          ← agent output files, mixed at root
```

### New layout (target)
```
workspace/
  projects/
    {id}/
      meta.json
      checkpoints/
        {label}.json
      files/           ← agent cwd (PiAgentClient + MarkdownOutput)
      audit.log        ← per-project audit log
  .active_project      ← one line: active project id (or empty)
```

### Known bug to fix
`ResearchCoordinator.__init__` creates `ProjectManager()` without `workspace_dir` — always defaults to `./workspace` regardless of the `--workspace` CLI flag.

---

## File Map

| File | Change |
|---|---|
| `src/research_team/project/manager.py` | Add layout methods, `init()`, `switch()`, `get_active_id()`, `set_active_id()`, legacy compat read, fix archive idempotency |
| `src/research_team/project/models.py` | No change |
| `src/research_team/orchestrator/coordinator.py` | Fix `ProjectManager()` bug, resolve `project_files_dir`, pass it to agents/MarkdownOutput |
| `src/research_team/cli/main.py` | Add `project` subcommand group: `init`, `switch`, `archive`, `list` |
| `tests/unit/test_project_manager.py` | Extend with new operations |
| `tests/unit/test_coordinator.py` | Add test for correct workspace_dir threading |

---

## Chunk 1: ProjectManager — new layout + init/switch/active

### Task 1: Directory layout helpers

**Files:**
- Modify: `src/research_team/project/manager.py`
- Test: `tests/unit/test_project_manager.py`

- [ ] **Step 1: Write failing tests for layout helpers**

Add to `tests/unit/test_project_manager.py`:

```python
def test_project_dir_structure(mgr, tmp_path):
    """New layout: projects/{id}/meta.json, checkpoints/, files/"""
    project = Project(topic="Layout test")
    mgr.save(project)
    assert (tmp_path / "projects" / project.id / "meta.json").exists()
    assert (tmp_path / "projects" / project.id / "checkpoints").is_dir()
    assert (tmp_path / "projects" / project.id / "files").is_dir()


def test_project_files_dir(mgr, tmp_path):
    project = Project(topic="Files dir test")
    mgr.save(project)
    assert mgr.project_files_dir(project.id) == tmp_path / "projects" / project.id / "files"
```

- [ ] **Step 2: Run to confirm FAIL**

```
pytest tests/unit/test_project_manager.py::test_project_dir_structure tests/unit/test_project_manager.py::test_project_files_dir -v
```
Expected: FAIL (new layout not implemented)

- [ ] **Step 3: Implement layout helpers in manager.py**

Replace the existing `_project_path` and `_checkpoint_dir` methods, add new helpers. Keep **legacy read** compatibility:

```python
# --- new layout helpers ---

def _project_dir(self, project_id: str) -> Path:
    return self._projects_dir / project_id

def _meta_path(self, project_id: str) -> Path:
    return self._project_dir(project_id) / "meta.json"

def _checkpoints_path(self, project_id: str) -> Path:
    return self._project_dir(project_id) / "checkpoints"

def project_files_dir(self, project_id: str) -> Path:
    return self._project_dir(project_id) / "files"

def _audit_path(self, project_id: str) -> Path:
    return self._project_dir(project_id) / "audit.log"

def _ensure_project_dirs(self, project_id: str) -> None:
    self._project_dir(project_id).mkdir(parents=True, exist_ok=True)
    self._checkpoints_path(project_id).mkdir(exist_ok=True)
    self.project_files_dir(project_id).mkdir(exist_ok=True)

# --- legacy compat (read-only) ---

def _legacy_meta_path(self, project_id: str) -> Path:
    """Old flat layout: projects/{id}.json"""
    return self._projects_dir / f"{project_id}.json"

def _legacy_checkpoints_dir(self, project_id: str) -> Path:
    return self._projects_dir / f"{project_id}_checkpoints"
```

Update `save()`, `load()`, `list_projects()`, `archive()`, `create_checkpoint()`, `restore_checkpoint()` to use new helpers. In `load()`, fall back to legacy path if new path missing.

Key changes to `save()`:
```python
def save(self, project: Project) -> None:
    if project.status == ProjectStatus.ARCHIVED:
        raise PermissionError(f"Project '{project.id}' is archived and cannot be modified")
    self._ensure_project_dirs(project.id)
    path = self._meta_path(project.id)
    self._assert_within_workspace(path)
    project.updated_at = datetime.now(timezone.utc)
    path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
```

Key changes to `load()`:
```python
def load(self, project_id: str) -> Project:
    new_path = self._meta_path(project_id)
    legacy_path = self._legacy_meta_path(project_id)
    if new_path.exists():
        path = new_path
    elif legacy_path.exists():
        path = legacy_path
    else:
        raise FileNotFoundError(f"Project '{project_id}' not found")
    self._assert_within_workspace(path)
    return Project.model_validate_json(path.read_text(encoding="utf-8"))
```

Key changes to `list_projects()`:
```python
def list_projects(self) -> list[Project]:
    results = []
    seen_ids: set[str] = set()
    # New layout: projects/{id}/meta.json
    for meta in sorted(self._projects_dir.glob("*/meta.json")):
        project = Project.model_validate_json(meta.read_text(encoding="utf-8"))
        seen_ids.add(project.id)
        results.append(project)
    # Legacy layout: projects/{id}.json
    for legacy in sorted(self._projects_dir.glob("*.json")):
        project = Project.model_validate_json(legacy.read_text(encoding="utf-8"))
        if project.id not in seen_ids:
            results.append(project)
    return results
```

Key changes to `archive()` — make idempotent:
```python
def archive(self, project_id: str) -> None:
    project = self.load(project_id)
    if project.status == ProjectStatus.ARCHIVED:
        return  # idempotent
    project.status = ProjectStatus.ARCHIVED
    project.updated_at = datetime.now(timezone.utc)
    self._ensure_project_dirs(project_id)
    self._meta_path(project_id).write_text(project.model_dump_json(indent=2), encoding="utf-8")
```

Key changes to `create_checkpoint()` / `restore_checkpoint()` — use `_checkpoints_path`:
```python
def create_checkpoint(self, project_id: str, label: str) -> str:
    source = self._meta_path(project_id)
    if not source.exists():
        source = self._legacy_meta_path(project_id)
    self._assert_within_workspace(source)
    if not source.exists():
        raise FileNotFoundError(f"Project '{project_id}' not found")
    cp_dir = self._checkpoints_path(project_id)
    self._assert_within_workspace(cp_dir)
    cp_dir.mkdir(parents=True, exist_ok=True)
    safe_label = label.replace("/", "_").replace("\\", "_")
    dest = cp_dir / f"{safe_label}.json"
    shutil.copy2(source, dest)
    return str(dest)

def restore_checkpoint(self, project_id: str, label: str) -> Project:
    cp_dir = self._checkpoints_path(project_id)
    # Also try legacy checkpoint dir
    if not cp_dir.exists():
        cp_dir = self._legacy_checkpoints_dir(project_id)
    safe_label = label.replace("/", "_").replace("\\", "_")
    checkpoint = cp_dir / f"{safe_label}.json"
    self._assert_within_workspace(checkpoint)
    if not checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint '{label}' not found for project '{project_id}'")
    project = Project.model_validate_json(checkpoint.read_text(encoding="utf-8"))
    if project.status == ProjectStatus.ARCHIVED:
        project.status = ProjectStatus.ACTIVE
    project.updated_at = datetime.now(timezone.utc)
    self._ensure_project_dirs(project_id)
    self._meta_path(project_id).write_text(project.model_dump_json(indent=2), encoding="utf-8")
    return project
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/unit/test_project_manager.py -v
```
Expected: all existing + 2 new tests PASS

- [ ] **Step 5: Commit**

```
git add src/research_team/project/manager.py tests/unit/test_project_manager.py
git commit -m "feat: migrate ProjectManager to per-project subdirectory layout"
```

---

### Task 2: `init()` — create new project

**Files:**
- Modify: `src/research_team/project/manager.py`
- Test: `tests/unit/test_project_manager.py`

- [ ] **Step 1: Write failing test**

```python
def test_init_creates_project_with_dirs(mgr, tmp_path):
    project = mgr.init("New research topic")
    assert project.id is not None
    assert project.status == ProjectStatus.ACTIVE
    assert (tmp_path / "projects" / project.id / "meta.json").exists()
    assert (tmp_path / "projects" / project.id / "files").is_dir()
    loaded = mgr.load(project.id)
    assert loaded.topic == "New research topic"


def test_init_project_not_in_active_yet(mgr):
    """init() creates project but does NOT auto-activate it"""
    project = mgr.init("Test")
    assert mgr.get_active_id() != project.id
```

- [ ] **Step 2: Run to confirm FAIL**

```
pytest tests/unit/test_project_manager.py::test_init_creates_project_with_dirs tests/unit/test_project_manager.py::test_init_project_not_in_active_yet -v
```

- [ ] **Step 3: Implement `init()`**

Add to `ProjectManager`:
```python
def init(self, topic: str) -> Project:
    project = Project(topic=topic)
    self.save(project)  # save() calls _ensure_project_dirs
    return project
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_project_manager.py -v
```

- [ ] **Step 5: Commit**

```
git add src/research_team/project/manager.py tests/unit/test_project_manager.py
git commit -m "feat: add ProjectManager.init()"
```

---

### Task 3: `.active_project` persistence — `get_active_id()` / `set_active_id()`

**Files:**
- Modify: `src/research_team/project/manager.py`
- Test: `tests/unit/test_project_manager.py`

- [ ] **Step 1: Write failing tests**

```python
def test_active_id_initially_none(mgr):
    assert mgr.get_active_id() is None


def test_set_and_get_active_id(mgr):
    project = mgr.init("Active test")
    mgr.set_active_id(project.id)
    assert mgr.get_active_id() == project.id


def test_active_id_persists_across_instances(tmp_path):
    mgr1 = ProjectManager(workspace_dir=tmp_path)
    project = mgr1.init("Persist test")
    mgr1.set_active_id(project.id)

    mgr2 = ProjectManager(workspace_dir=tmp_path)
    assert mgr2.get_active_id() == project.id


def test_set_active_id_rejects_nonexistent(mgr):
    with pytest.raises(FileNotFoundError):
        mgr.set_active_id("nonexistent-id")


def test_set_active_id_rejects_archived(mgr):
    project = mgr.init("Archived")
    mgr.archive(project.id)
    with pytest.raises(PermissionError, match="archived"):
        mgr.set_active_id(project.id)


def test_clear_active_id(mgr):
    project = mgr.init("Clear test")
    mgr.set_active_id(project.id)
    mgr.set_active_id(None)
    assert mgr.get_active_id() is None
```

- [ ] **Step 2: Run to confirm FAIL**

```
pytest tests/unit/test_project_manager.py::test_active_id_initially_none -v
```

- [ ] **Step 3: Implement `get_active_id()` / `set_active_id()`**

Add to `ProjectManager.__init__`:
```python
self._active_file = self._workspace / ".active_project"
```

Add methods:
```python
def get_active_id(self) -> str | None:
    if not self._active_file.exists():
        return None
    content = self._active_file.read_text(encoding="utf-8").strip()
    return content if content else None

def set_active_id(self, project_id: str | None) -> None:
    if project_id is None:
        self._active_file.write_text("", encoding="utf-8")
        return
    project = self.load(project_id)  # raises FileNotFoundError if missing
    if project.status == ProjectStatus.ARCHIVED:
        raise PermissionError(f"Project '{project_id}' is archived and cannot be activated")
    # Atomic write: temp file + rename
    tmp = self._active_file.with_suffix(".tmp")
    tmp.write_text(project_id, encoding="utf-8")
    tmp.replace(self._active_file)
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_project_manager.py -v
```

- [ ] **Step 5: Commit**

```
git add src/research_team/project/manager.py tests/unit/test_project_manager.py
git commit -m "feat: add active project persistence (.active_project file)"
```

---

### Task 4: `switch()` — switch active project

**Files:**
- Modify: `src/research_team/project/manager.py`
- Test: `tests/unit/test_project_manager.py`

- [ ] **Step 1: Write failing tests**

```python
def test_switch_changes_active_project(mgr):
    p1 = mgr.init("Project 1")
    p2 = mgr.init("Project 2")
    mgr.switch(p1.id)
    assert mgr.get_active_id() == p1.id
    mgr.switch(p2.id)
    assert mgr.get_active_id() == p2.id


def test_switch_to_archived_raises(mgr):
    project = mgr.init("Archived project")
    mgr.archive(project.id)
    with pytest.raises(PermissionError, match="archived"):
        mgr.switch(project.id)


def test_switch_to_nonexistent_raises(mgr):
    with pytest.raises(FileNotFoundError):
        mgr.switch("ghost-id")


def test_switch_returns_project(mgr):
    project = mgr.init("Return test")
    result = mgr.switch(project.id)
    assert result.id == project.id
    assert result.topic == "Return test"
```

- [ ] **Step 2: Run to confirm FAIL**

```
pytest tests/unit/test_project_manager.py::test_switch_changes_active_project -v
```

- [ ] **Step 3: Implement `switch()`**

```python
def switch(self, project_id: str) -> Project:
    self.set_active_id(project_id)  # validates existence + not archived
    return self.load(project_id)
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_project_manager.py -v
```

- [ ] **Step 5: Commit**

```
git add src/research_team/project/manager.py tests/unit/test_project_manager.py
git commit -m "feat: add ProjectManager.switch()"
```

---

## Chunk 2: ResearchCoordinator — fix bug + project_files_dir threading

### Task 5: Fix workspace_dir bug + pass project_files_dir to agents

**Files:**
- Modify: `src/research_team/orchestrator/coordinator.py`
- Test: `tests/unit/test_coordinator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_coordinator.py`:

```python
def test_coordinator_passes_workspace_to_project_manager(tmp_path):
    """Bug fix: ProjectManager must use same workspace_dir as coordinator"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    assert coord._project_manager._workspace == tmp_path
```

- [ ] **Step 2: Run to confirm FAIL**

```
pytest tests/unit/test_coordinator.py::test_coordinator_passes_workspace_to_project_manager -v
```

- [ ] **Step 3: Fix the bug in coordinator.py**

In `ResearchCoordinator.__init__`:
```python
from research_team.project.manager import ProjectManager as ProjectFileManager

class ResearchCoordinator:
    def __init__(self, workspace_dir: str | None = None, ui=None):
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._ui = ui
        self._csm = ClientSuccessManager()
        self._pm_agent = ProjectManager()        # ← rename: this is the PM *agent*
        self._project_manager = ProjectFileManager(workspace_dir=self._workspace_dir)
        self._team_builder = TeamBuilder()
        self._search_engine = SearchEngineFactory.create(control_ui=ui)
        self._quality_loop = QualityLoop()
        self._search_server: SearchServer | None = None
        self._search_port: int = 0
```

Note: `ProjectManager` from `research_team.agents.pm` (the PM agent) and `ProjectManager` from `research_team.project.manager` (the file manager) have the same class name. Rename the import alias to distinguish:

```python
from research_team.agents.pm import ProjectManager as PMAgent
from research_team.project.manager import ProjectManager as ProjectFileManager
```

Update all references to `self._pm` → `self._pm_agent`.

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_coordinator.py -v
```

- [ ] **Step 5: Wire active project → project_files_dir**

Modify `_run_research()` to resolve the active project's files directory when available:

```python
def _get_agent_workspace(self) -> str:
    """Return project files dir if an active project exists, else workspace root."""
    active_id = self._project_manager.get_active_id()
    if active_id:
        return str(self._project_manager.project_files_dir(active_id))
    return self._workspace_dir
```

Update `_stream_agent_output()` — use `_get_agent_workspace()` for the `workspace_dir` parameter passed to `agent.run()`.

Update `_run_research()` — use `_get_agent_workspace()` for `MarkdownOutput`:
```python
output_path = MarkdownOutput(self._get_agent_workspace()).save(
    combined_content, topic, report_type="business"
)
```

- [ ] **Step 6: Write test for project_files_dir threading**

```python
@pytest.mark.asyncio
async def test_coordinator_uses_project_files_dir_when_active(tmp_path):
    """When active project set, agents get project files dir, not workspace root"""
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    project = coord._project_manager.init("Test project")
    coord._project_manager.switch(project.id)

    agent_workspace = coord._get_agent_workspace()
    assert agent_workspace == str(coord._project_manager.project_files_dir(project.id))
    assert agent_workspace != str(tmp_path)


@pytest.mark.asyncio
async def test_coordinator_falls_back_to_workspace_root_when_no_active(tmp_path):
    coord = ResearchCoordinator(workspace_dir=str(tmp_path))
    # No active project set
    assert coord._get_agent_workspace() == str(tmp_path)
```

- [ ] **Step 7: Run all tests**

```
pytest tests/unit/ -v
```
Expected: 76+ tests PASS

- [ ] **Step 8: Commit**

```
git add src/research_team/orchestrator/coordinator.py tests/unit/test_coordinator.py
git commit -m "fix: pass workspace_dir to ProjectManager; route agents to project files dir"
```

---

## Chunk 3: CLI — project subcommands

### Task 6: Add `project` CLI subcommand group

**Files:**
- Modify: `src/research_team/cli/main.py`
- Test: manual smoke test only (CLI integration — no unit test needed)

- [ ] **Step 1: Implement CLI subcommands**

Add to `main.py`:

```python
project_app = typer.Typer(help="プロジェクト管理コマンド")
app.add_typer(project_app, name="project")


@project_app.command("init")
def project_init(
    topic: str = typer.Argument(..., help="調査テーマ"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """新しいプロジェクトを作成してアクティブにする"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    project = mgr.init(topic)
    mgr.switch(project.id)
    typer.echo(f"✅ プロジェクト作成: {project.id}")
    typer.echo(f"   テーマ: {project.topic}")
    typer.echo(f"   作業フォルダ: {mgr.project_files_dir(project.id)}")


@project_app.command("list")
def project_list(
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """プロジェクト一覧を表示する"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    projects = mgr.list_projects()
    active_id = mgr.get_active_id()
    if not projects:
        typer.echo("プロジェクトがありません。")
        return
    for p in projects:
        marker = "▶" if p.id == active_id else " "
        status = "[archived]" if p.status.value == "archived" else ""
        typer.echo(f"{marker} {p.id[:8]}  {p.topic}  {status}")


@project_app.command("switch")
def project_switch(
    project_id: str = typer.Argument(..., help="プロジェクトID（前方一致可）"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """アクティブプロジェクトを切り替える"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    # Support prefix matching (first 8 chars)
    projects = mgr.list_projects()
    matched = [p for p in projects if p.id.startswith(project_id)]
    if not matched:
        typer.echo(f"❌ プロジェクトが見つかりません: {project_id}", err=True)
        raise typer.Exit(1)
    if len(matched) > 1:
        typer.echo(f"❌ 複数のプロジェクトが一致します。IDをより長く指定してください。", err=True)
        raise typer.Exit(1)
    project = mgr.switch(matched[0].id)
    typer.echo(f"✅ 切り替え完了: {project.topic}")
    typer.echo(f"   ID: {project.id}")


@project_app.command("archive")
def project_archive(
    project_id: str = typer.Argument(..., help="プロジェクトID（前方一致可）"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """プロジェクトをアーカイブする（アーカイブ済みは編集・アクティブ化不可）"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    projects = mgr.list_projects()
    matched = [p for p in projects if p.id.startswith(project_id)]
    if not matched:
        typer.echo(f"❌ プロジェクトが見つかりません: {project_id}", err=True)
        raise typer.Exit(1)
    if len(matched) > 1:
        typer.echo(f"❌ 複数のプロジェクトが一致します。IDをより長く指定してください。", err=True)
        raise typer.Exit(1)
    target = matched[0]
    mgr.archive(target.id)
    # If this was the active project, clear active
    if mgr.get_active_id() == target.id:
        mgr.set_active_id(None)
    typer.echo(f"✅ アーカイブ完了: {target.topic}")
```

- [ ] **Step 2: Smoke test (manual)**

```
python -m research_team.cli.main project init "テスト調査テーマ"
python -m research_team.cli.main project list
python -m research_team.cli.main project archive <first-8-chars>
python -m research_team.cli.main project list
```
Expected: init shows created ID, list shows ▶ marker, archive removes marker, archived shows `[archived]`

- [ ] **Step 3: Commit**

```
git add src/research_team/cli/main.py
git commit -m "feat: add project init/list/switch/archive CLI subcommands"
```

---

## Chunk 4: Final verification

### Task 7: Full test suite + regression check

- [ ] **Step 1: Run full test suite**

```
pytest tests/unit/ -v
```
Expected: all tests PASS (no regressions)

- [ ] **Step 2: Verify archive idempotency**

```python
# In Python REPL or quick script:
import tempfile
from pathlib import Path
from research_team.project.manager import ProjectManager

with tempfile.TemporaryDirectory() as d:
    mgr = ProjectManager(workspace_dir=d)
    p = mgr.init("test")
    mgr.archive(p.id)
    mgr.archive(p.id)  # Must not raise
    print("archive idempotency: OK")
```

- [ ] **Step 3: Verify legacy layout compat**

```python
# Create a project in old layout, confirm it's still loadable
import tempfile, json
from pathlib import Path
from research_team.project.manager import ProjectManager
from research_team.project.models import Project

with tempfile.TemporaryDirectory() as d:
    wd = Path(d)
    (wd / "projects").mkdir()
    p = Project(topic="Legacy project")
    (wd / "projects" / f"{p.id}.json").write_text(p.model_dump_json())
    
    mgr = ProjectManager(workspace_dir=wd)
    loaded = mgr.load(p.id)
    assert loaded.topic == "Legacy project"
    print("legacy compat: OK")
```

- [ ] **Step 4: Final commit message**

```
git add .
git commit -m "feat: project archive/switch/init with per-project directory isolation"
```

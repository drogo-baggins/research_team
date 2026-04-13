import tempfile
from pathlib import Path
import pytest
from research_team.project.models import Project, ProjectStatus, Milestone, WBSTask
from research_team.project.manager import ProjectManager


@pytest.fixture
def mgr(tmp_path):
    return ProjectManager(workspace_dir=tmp_path)


def test_save_and_load_roundtrip(mgr):
    project = Project(topic="Climate change impacts")
    mgr.save(project)
    loaded = mgr.load(project.id)
    assert loaded.topic == project.topic
    assert loaded.id == project.id


def test_list_projects_returns_all(mgr):
    p1 = Project(topic="Topic A")
    p2 = Project(topic="Topic B")
    mgr.save(p1)
    mgr.save(p2)
    projects = mgr.list_projects()
    ids = {p.id for p in projects}
    assert p1.id in ids and p2.id in ids


def test_load_nonexistent_raises(mgr):
    with pytest.raises(FileNotFoundError):
        mgr.load("nonexistent-id")


def test_archive_sets_status(mgr):
    project = Project(topic="Archived topic")
    mgr.save(project)
    mgr.archive(project.id)
    loaded = mgr.load(project.id)
    assert loaded.status == ProjectStatus.ARCHIVED


def test_save_archived_raises_permission_error(mgr):
    project = Project(topic="Frozen topic")
    mgr.save(project)
    mgr.archive(project.id)
    archived = mgr.load(project.id)
    with pytest.raises(PermissionError, match="archived"):
        mgr.save(archived)


def test_create_and_restore_checkpoint(mgr):
    project = Project(topic="Before checkpoint")
    mgr.save(project)
    mgr.create_checkpoint(project.id, "v1")
    project2 = mgr.load(project.id)
    project2.topic = "After checkpoint"
    project2.status = ProjectStatus.ACTIVE
    mgr.save(project2)
    restored = mgr.restore_checkpoint(project.id, "v1")
    assert restored.topic == "Before checkpoint"


def test_restore_nonexistent_checkpoint_raises(mgr):
    project = Project(topic="No checkpoint")
    mgr.save(project)
    with pytest.raises(FileNotFoundError):
        mgr.restore_checkpoint(project.id, "ghost")


def test_workspace_escape_denied(tmp_path):
    mgr = ProjectManager(workspace_dir=tmp_path)
    with pytest.raises(PermissionError, match="workspace"):
        mgr._assert_within_workspace(tmp_path.parent / "escape.json")


def test_project_with_milestones_roundtrip(mgr):
    task = WBSTask(title="Gather sources")
    milestone = Milestone(title="Phase 1", tasks=[task])
    project = Project(topic="Deep research", milestones=[milestone])
    mgr.save(project)
    loaded = mgr.load(project.id)
    assert len(loaded.milestones) == 1
    assert loaded.milestones[0].tasks[0].title == "Gather sources"


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


def test_archive_idempotent(mgr):
    project = Project(topic="Idempotent archive")
    mgr.save(project)
    mgr.archive(project.id)
    mgr.archive(project.id)  # must not raise
    loaded = mgr.load(project.id)
    assert loaded.status == ProjectStatus.ARCHIVED


def test_restore_checkpoint_legacy_fallback(tmp_path):
    """Legacy checkpoint in old dir is found even after new checkpoints/ dir exists."""
    mgr = ProjectManager(workspace_dir=tmp_path)
    project = Project(topic="Legacy checkpoint test")
    # Simulate legacy layout: write checkpoint in old flat location
    legacy_cp_dir = tmp_path / "projects" / f"{project.id}_checkpoints"
    legacy_cp_dir.mkdir(parents=True)
    (legacy_cp_dir / "v1.json").write_text(project.model_dump_json(), encoding="utf-8")
    # Now save the project in the NEW layout (creates new checkpoints/ dir)
    mgr.save(project)
    # restore_checkpoint must find v1 in legacy dir even though new checkpoints/ exists
    restored = mgr.restore_checkpoint(project.id, "v1")
    assert restored.topic == "Legacy checkpoint test"


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

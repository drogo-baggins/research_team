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

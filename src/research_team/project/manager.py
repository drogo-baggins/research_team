from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from research_team.project.models import Project, ProjectStatus


class ProjectManager:
    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self._workspace = Path(workspace_dir or "workspace").resolve()
        self._projects_dir = self._workspace / "projects"
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def _project_path(self, project_id: str) -> Path:
        return self._projects_dir / f"{project_id}.json"

    def _checkpoint_dir(self, project_id: str) -> Path:
        return self._projects_dir / f"{project_id}_checkpoints"

    def _assert_within_workspace(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self._workspace)
        except ValueError:
            raise PermissionError(f"Access outside workspace denied: {path}")

    def save(self, project: Project) -> None:
        if project.status == ProjectStatus.ARCHIVED:
            raise PermissionError(f"Project '{project.id}' is archived and cannot be modified")
        path = self._project_path(project.id)
        self._assert_within_workspace(path)
        project.updated_at = datetime.now(timezone.utc)
        path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

    def load(self, project_id: str) -> Project:
        path = self._project_path(project_id)
        self._assert_within_workspace(path)
        if not path.exists():
            raise FileNotFoundError(f"Project '{project_id}' not found")
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def list_projects(self) -> list[Project]:
        return [
            Project.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self._projects_dir.glob("*.json"))
        ]

    def archive(self, project_id: str) -> None:
        project = self.load(project_id)
        project.status = ProjectStatus.ARCHIVED
        project.updated_at = datetime.now(timezone.utc)
        path = self._project_path(project_id)
        path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

    def create_checkpoint(self, project_id: str, label: str) -> str:
        source = self._project_path(project_id)
        self._assert_within_workspace(source)
        if not source.exists():
            raise FileNotFoundError(f"Project '{project_id}' not found")
        checkpoint_dir = self._checkpoint_dir(project_id)
        self._assert_within_workspace(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        safe_label = label.replace("/", "_").replace("\\", "_")
        dest = checkpoint_dir / f"{safe_label}.json"
        shutil.copy2(source, dest)
        return str(dest)

    def restore_checkpoint(self, project_id: str, label: str) -> Project:
        checkpoint_dir = self._checkpoint_dir(project_id)
        safe_label = label.replace("/", "_").replace("\\", "_")
        checkpoint = checkpoint_dir / f"{safe_label}.json"
        self._assert_within_workspace(checkpoint)
        if not checkpoint.exists():
            raise FileNotFoundError(f"Checkpoint '{label}' not found for project '{project_id}'")
        project = Project.model_validate_json(checkpoint.read_text(encoding="utf-8"))
        if project.status == ProjectStatus.ARCHIVED:
            project.status = ProjectStatus.ACTIVE
        project.updated_at = datetime.now(timezone.utc)
        dest = self._project_path(project_id)
        dest.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return project

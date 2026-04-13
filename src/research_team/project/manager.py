from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from research_team.project.models import Project, ProjectStatus


class ProjectManager:
    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self._workspace = Path(workspace_dir or "workspace").resolve()
        self._projects_dir = self._workspace / "projects"
        self._projects_dir.mkdir(parents=True, exist_ok=True)
        self._active_file = self._workspace / ".active_project"

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

    def _legacy_meta_path(self, project_id: str) -> Path:
        return self._projects_dir / f"{project_id}.json"

    def _legacy_checkpoints_dir(self, project_id: str) -> Path:
        return self._projects_dir / f"{project_id}_checkpoints"

    def _assert_within_workspace(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self._workspace)
        except ValueError:
            raise PermissionError(f"Access outside workspace denied: {path}")

    def save(self, project: Project) -> None:
        if project.status == ProjectStatus.ARCHIVED:
            raise PermissionError(f"Project '{project.id}' is archived and cannot be modified")
        path = self._meta_path(project.id)
        self._assert_within_workspace(path)
        self._ensure_project_dirs(project.id)
        project.updated_at = datetime.now(timezone.utc)
        path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

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

    def list_projects(self) -> list[Project]:
        results = []
        seen_ids: set[str] = set()
        for meta in sorted(self._projects_dir.glob("*/meta.json")):
            project = Project.model_validate_json(meta.read_text(encoding="utf-8"))
            seen_ids.add(project.id)
            results.append(project)
        for legacy in sorted(self._projects_dir.glob("*.json")):
            project = Project.model_validate_json(legacy.read_text(encoding="utf-8"))
            if project.id not in seen_ids:
                results.append(project)
        return results

    def archive(self, project_id: str) -> None:
        project = self.load(project_id)
        if project.status == ProjectStatus.ARCHIVED:
            return
        project.status = ProjectStatus.ARCHIVED
        project.updated_at = datetime.now(timezone.utc)
        self._ensure_project_dirs(project_id)
        self._meta_path(project_id).write_text(project.model_dump_json(indent=2), encoding="utf-8")

    def init(self, topic: str) -> Project:
        project = Project(topic=topic)
        self.save(project)
        return project

    def get_active_id(self) -> str | None:
        if not self._active_file.exists():
            return None
        content = self._active_file.read_text(encoding="utf-8").strip()
        return content if content else None

    def set_active_id(self, project_id: str | None) -> None:
        if project_id is None:
            self._active_file.write_text("", encoding="utf-8")
            return
        project = self.load(project_id)
        if project.status == ProjectStatus.ARCHIVED:
            raise PermissionError(f"Project '{project_id}' is archived and cannot be activated")
        tmp = self._active_file.with_suffix(".tmp")
        tmp.write_text(project_id, encoding="utf-8")
        tmp.replace(self._active_file)

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
        safe_label = label.replace("/", "_").replace("\\", "_")
        cp_dir = self._checkpoints_path(project_id)
        checkpoint = cp_dir / f"{safe_label}.json"
        if not checkpoint.exists():
            legacy_cp_dir = self._legacy_checkpoints_dir(project_id)
            legacy_checkpoint = legacy_cp_dir / f"{safe_label}.json"
            if legacy_checkpoint.exists():
                checkpoint = legacy_checkpoint
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

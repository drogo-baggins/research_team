from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WBSTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    assignee: str = ""
    done: bool = False


class Milestone(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    tasks: list[WBSTask] = Field(default_factory=list)
    quality_score_target: float = 0.8


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    milestones: list[Milestone] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

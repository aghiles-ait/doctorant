"""Modèle d'un projet de recherche (project.yaml)."""

from datetime import datetime

from pydantic import BaseModel, Field

from research_lab.workflow.state import ResearchState


class StateChange(BaseModel):
    from_state: ResearchState | None
    to_state: ResearchState
    at: datetime
    actor: str


class Project(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    topic: str = Field(min_length=1)
    state: ResearchState
    created_at: datetime
    updated_at: datetime
    history: list[StateChange] = Field(default_factory=list)

"""Modèles des requêtes bibliographiques et de leur historique."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from research_lab.schemas.paper import Source


class SearchQuery(BaseModel):
    text: str = Field(min_length=1)
    date_from: date | None = None
    date_to: date | None = None
    max_results: int = Field(default=50, ge=1, le=1000)

    @model_validator(mode="after")
    def _check_dates(self) -> "SearchQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from doit précéder date_to")
        return self


class SourceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class SourceResult(BaseModel):
    source: Source
    status: SourceStatus
    provider_query: str | None = None  # requête effectivement envoyée à l'API
    total_available: int | None = None
    hits: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class SearchStatus(StrEnum):
    COMPLETED = "completed"  # toutes les sources ont répondu
    PARTIAL = "partial"  # au moins une source en erreur, résultats fusionnés avec --allow-partial
    FAILED = "failed"  # au moins une source en erreur, corpus inchangé


class SearchExecution(BaseModel):
    """Entrée du journal des recherches (search-log.json)."""

    search_id: str = Field(pattern=r"^SEARCH-\d{3,}$")
    project_id: str
    query: SearchQuery
    sources: list[Source]
    started_at: datetime
    finished_at: datetime
    status: SearchStatus
    results: list[SourceResult]
    new_paper_ids: list[str] = Field(default_factory=list)
    matched_paper_ids: list[str] = Field(default_factory=list)
    tool_version: str
    config_hash: str

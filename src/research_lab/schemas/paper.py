"""Modèles des publications et de leur provenance."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Source(StrEnum):
    ARXIV = "arxiv"
    OPENALEX = "openalex"


class PaperStatus(StrEnum):
    CANDIDATE = "candidate"  # trouvé par la veille, pas encore qualifié
    RETAINED = "retained"  # retenu pour l'état de l'art (sprint 2)
    EXCLUDED = "excluded"


class PaperMetadata(BaseModel):
    """Métadonnées bibliographiques normalisées, telles que renvoyées par une source."""

    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published: date | None = None
    venue: str | None = None
    work_type: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    url: str | None = None

    def has_identifier(self) -> bool:
        return any((self.doi, self.arxiv_id, self.openalex_id))


class SourceHit(BaseModel):
    """Un résultat brut d'une source, avant intégration au corpus."""

    source: Source
    source_id: str
    metadata: PaperMetadata


class Provenance(BaseModel):
    """Trace d'une découverte : quelle source, quelle recherche, quand."""

    source: Source
    source_id: str
    search_id: str
    query: str
    retrieved_at: datetime


class Paper(PaperMetadata):
    """Publication du corpus, avec identifiant interne stable."""

    paper_id: str = Field(pattern=r"^PAPER-\d{3,}$")
    status: PaperStatus = PaperStatus.CANDIDATE
    provenance: list[Provenance] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_identifier(self) -> "Paper":
        if not self.has_identifier():
            raise ValueError(f"{self.paper_id}: aucun identifiant externe (DOI, arXiv ou OpenAlex)")
        return self

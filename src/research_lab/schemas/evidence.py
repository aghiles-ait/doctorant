"""Modèles du texte intégral et des preuves extraites des publications."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class FulltextStatus(StrEnum):
    AVAILABLE = "available"  # PDF téléchargé et texte extrait
    UNAVAILABLE = "unavailable"  # aucune version en accès libre connue
    FAILED = "failed"  # version libre trouvée, mais téléchargement ou extraction en échec


class FulltextRecord(BaseModel):
    """Texte intégral d'une publication, partagé entre les projets."""

    paper_id: str
    status: FulltextStatus
    pdf_url: str | None = None
    pdf_sha256: str | None = None
    text_sha256: str | None = None  # empreinte du texte extrait (knowledge/papers/<id>.pages.json)
    page_count: int | None = None
    extractor: str | None = None
    fetched_at: datetime
    error: str | None = None


class EvidenceType(StrEnum):
    EMPIRICAL_RESULT = "empirical_result"  # résultat mesuré ou observé
    THEORETICAL_RESULT = "theoretical_result"  # théorème, preuve formelle
    METHOD = "method"  # description d'une approche ou d'un système
    DEFINITION = "definition"
    POSITION = "position"  # affirmation ou argument des auteurs, non démontré
    LIMITATION = "limitation"  # limite reconnue par les auteurs


class EvidenceLocation(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"


class Evidence(BaseModel):
    """Extrait vérifié d'une publication, appuyant une affirmation (spec §7, Q2)."""

    evidence_id: str = Field(pattern=r"^EV-\d{3,}$")
    project_id: str
    paper_id: str
    claim: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    location: EvidenceLocation
    page: int | None = Field(default=None, ge=1)
    evidence_type: EvidenceType
    text_sha256: str  # empreinte du texte dans lequel l'extrait a été vérifié
    created_at: datetime
    actor: str
    withdrawn_at: datetime | None = None
    withdrawn_reason: str | None = None

    @model_validator(mode="after")
    def _page_matches_location(self) -> "Evidence":
        if (self.location == EvidenceLocation.FULL_TEXT) != (self.page is not None):
            raise ValueError("une preuve du texte intégral a une page ; une preuve du résumé n'en a pas")
        return self

    @property
    def active(self) -> bool:
        return self.withdrawn_at is None

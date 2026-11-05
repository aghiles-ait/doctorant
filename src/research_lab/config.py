"""Chargement de la configuration (config/*.yaml) et localisation du dépôt."""

import hashlib
import json
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from research_lab.schemas.paper import Source

ROOT_ENV_VAR = "RESEARCH_LAB_ROOT"
_MARKER = Path("config") / "academic-sources.yaml"


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    backoff_seconds: float = Field(default=2.0, ge=0)


class ProviderConfig(BaseModel):
    enabled: bool = True
    base_url: str
    page_size: int = Field(default=100, ge=1)
    timeout_seconds: float = 30.0
    min_interval_seconds: float = 0.0


class FulltextConfig(BaseModel):
    arxiv_pdf_url: str = "https://export.arxiv.org/pdf"
    timeout_seconds: float = 60.0
    min_interval_seconds: float = 3.0
    max_pdf_mb: float = Field(default=50.0, gt=0)
    # En dessous, le PDF est probablement scanné : pas de texte exploitable.
    min_extracted_chars: int = Field(default=500, ge=0)


class SourcesConfig(BaseModel):
    version: str
    default_sources: list[Source]
    default_max_results: int = Field(ge=1)
    retry: RetryConfig = RetryConfig()
    providers: dict[Source, ProviderConfig]
    fulltext: FulltextConfig = FulltextConfig()


class PolicyConfig(BaseModel):
    version: str
    min_corpus_size: int = Field(ge=0)
    allow_partial_search: bool = False
    min_quote_chars: int = Field(default=20, ge=1)
    # Nombre minimal de publications distinctes appuyant un gap pour le déclarer `supported`.
    min_supporting_papers: int = Field(default=2, ge=1)


class ValueDefinition(BaseModel):
    description: str
    weight: float = Field(ge=0)


class EvaluationConfig(BaseModel):
    scale: list[int] = Field(min_length=2)
    require_justification: bool = True
    report_tradeoffs: bool = True
    allow_not_applicable: bool = True


class ValuesConfig(BaseModel):
    """config/research-values.yaml : valeurs servant à évaluer et prioriser les gaps (spec §5)."""

    version: str
    values: dict[str, ValueDefinition] = Field(min_length=1)
    evaluation: EvaluationConfig


class PriorityConfig(BaseModel):
    # Score de priorité = somme pondérée de l'alignement (0-1) et de la force des preuves (0-1).
    weights: dict[str, float] = {"alignment": 0.5, "evidence_strength": 0.5}
    evidence_strength: dict[str, float] = {"low": 0.0, "medium": 0.5, "high": 1.0}


class ScoringConfig(BaseModel):
    version: str
    priority: PriorityConfig = PriorityConfig()


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


class Settings(BaseModel):
    root: Path
    sources: SourcesConfig
    policy: PolicyConfig
    values: ValuesConfig
    scoring: ScoringConfig

    @property
    def projects_dir(self) -> Path:
        return self.root / "research" / "projects"

    @property
    def db_path(self) -> Path:
        return self.root / "knowledge" / "research.db"

    @property
    def papers_dir(self) -> Path:
        return self.root / "knowledge" / "papers"

    def config_hash(self) -> str:
        """Empreinte de la configuration effective, consignée dans chaque recherche."""
        return _digest({"sources": self.sources.model_dump(mode="json"), "policy": self.policy.model_dump(mode="json")})

    def values_hash(self) -> str:
        """Empreinte des valeurs et de la pondération, consignée dans chaque évaluation d'alignement."""
        return _digest({"values": self.values.model_dump(mode="json"), "scoring": self.scoring.model_dump(mode="json")})


def find_root(start: Path | None = None) -> Path:
    if env := os.environ.get(ROOT_ENV_VAR):
        return Path(env).resolve()
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / _MARKER).is_file():
            return directory
    raise FileNotFoundError(f"Dépôt introuvable : aucun {_MARKER} dans {current} ni ses parents (ou définir {ROOT_ENV_VAR})")


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(root: Path | None = None) -> Settings:
    root = root or find_root()
    sources = SourcesConfig.model_validate(_load_yaml(root / "config" / "academic-sources.yaml"))
    policy_raw = _load_yaml(root / "config" / "research-policy.yaml")
    policy = PolicyConfig.model_validate(
        {
            "version": policy_raw.get("version"),
            **policy_raw.get("literature_search", {}),
            **policy_raw.get("literature_review", {}),
            **policy_raw.get("gap_analysis", {}),
        }
    )
    values = ValuesConfig.model_validate(_load_yaml(root / "config" / "research-values.yaml"))
    scoring = ScoringConfig.model_validate(_load_yaml(root / "config" / "scoring.yaml"))
    return Settings(root=root, sources=sources, policy=policy, values=values, scoring=scoring)

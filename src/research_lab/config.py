"""Chargement de la configuration (config/*.yaml) et localisation du dépôt."""

import hashlib
import json
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from research_lab.schemas.paper import Source

ROOT_ENV_VAR = "RESEARCH_LAB_ROOT"
_MARKER = Path("config") / "academic-sources.yaml"


class RetryConfig(BaseModel):
    # arXiv renvoie des 429 même à 3 s d'écart entre requêtes : des attentes de quelques secondes ne suffisent pas.
    max_attempts: int = Field(default=4, ge=1)
    # Attente avant la 2e, 3e, … tentative ; la dernière valeur sert pour les suivantes.
    delays_seconds: list[float] = Field(default=[15.0, 60.0, 180.0], min_length=1)
    # `Retry-After` envoyé par le serveur est respecté, dans cette limite.
    max_retry_after_seconds: float = Field(default=300.0, ge=0)

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Attente après l'échec de la tentative `attempt` (1 pour la première)."""
        if retry_after is not None:
            return min(retry_after, self.max_retry_after_seconds)
        return self.delays_seconds[min(attempt, len(self.delays_seconds)) - 1]


class ProviderConfig(BaseModel):
    enabled: bool = True
    base_url: str
    page_size: int = Field(default=100, ge=1)
    timeout_seconds: float = 30.0
    min_interval_seconds: float = 0.0
    # arXiv : catégories auxquelles la recherche est restreinte (vide : toutes).
    categories: list[str] = []
    # OpenAlex : filtres ajoutés à chaque recherche (syntaxe `filter=` de l'API, par exemple `has_abstract:true`).
    filters: list[str] = []


class FulltextConfig(BaseModel):
    arxiv_pdf_url: str = "https://export.arxiv.org/pdf"
    timeout_seconds: float = 60.0
    min_interval_seconds: float = 3.0
    max_pdf_mb: float = Field(default=50.0, gt=0)
    # En dessous, le PDF est probablement scanné : pas de texte exploitable.
    min_extracted_chars: int = Field(default=500, ge=0)
    # `fulltext show` n'affiche pas plus que ce nombre de caractères par appel : une sortie trop longue
    # peut être tronquée avant d'atteindre le modèle (vécu avec l'agent researcher, 66 727 caractères).
    max_show_chars: int = Field(default=15000, ge=1000)


class SourcesConfig(BaseModel):
    version: str
    default_sources: list[Source]
    default_max_results: int = Field(ge=1)
    retry: RetryConfig = RetryConfig()
    providers: dict[Source, ProviderConfig]
    fulltext: FulltextConfig = FulltextConfig()


class HumanEvaluationConfig(BaseModel):
    """Grille de l'évaluation humaine des gaps et des hypothèses (spec §11)."""

    scale: list[int] = Field(default=[1, 2, 3, 4, 5], min_length=2)
    gap_criteria: dict[str, str] = Field(min_length=1)
    hypothesis_criteria: dict[str, str] = Field(min_length=1)
    min_rated_topics: int = Field(default=3, ge=1)


class PolicyConfig(BaseModel):
    version: str
    min_corpus_size: int = Field(ge=0)
    allow_partial_search: bool = False
    min_quote_chars: int = Field(default=20, ge=1)
    # Une publication incluse dont le texte intégral est disponible doit avoir été affichée en entier
    # (pages du texte principal, jusqu'aux références) avant de clore l'état de l'art.
    require_full_reading: bool = True
    # Recherche plafonnée : en dessous de ce nombre de résultats disponibles, `corpus check` exige de tout
    # examiner (relancer avec --max-results) ; au-dessus, la requête est trop large et le plafond est signalé.
    max_examinable_results: int = Field(default=300, ge=1)
    # Nombre minimal de publications distinctes appuyant un gap pour le déclarer `supported`.
    min_supporting_papers: int = Field(default=2, ge=1)
    # Nombre minimal de solutions actives, comparées entre elles, pour chaque question de recherche.
    min_solution_alternatives: int = Field(default=2, ge=2)
    # Revue critique : preuves du raisonnement que le reviewer doit relire, nombre maximal de tours.
    min_verified_evidence: int = Field(default=5, ge=1)
    max_review_rounds: int = Field(default=3, ge=1)
    evaluation: HumanEvaluationConfig = HumanEvaluationConfig(
        gap_criteria={"reality": "Le manque est réel"}, hypothesis_criteria={"falsifiability": "Réfutable"}
    )


class ModelPrice(BaseModel):
    """Prix en dollars par million de jetons."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_write_5m: float = Field(ge=0)
    cache_write_1h: float = Field(ge=0)
    cache_read: float = Field(ge=0)


class CostsConfig(BaseModel):
    """config/costs.yaml : suivi des coûts des agents (sprint 4)."""

    version: str
    transcripts_dir: str = ""
    research_agents: list[str] = Field(min_length=1)
    prices: dict[str, ModelPrice] = Field(min_length=1)


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
    costs: CostsConfig

    @property
    def projects_dir(self) -> Path:
        return self.root / "research" / "projects"

    @property
    def db_path(self) -> Path:
        return self.root / "knowledge" / "research.db"

    @property
    def papers_dir(self) -> Path:
        return self.root / "knowledge" / "papers"

    @property
    def transcripts_dir(self) -> Path:
        """Transcriptions de Claude Code pour ce dépôt."""
        if self.costs.transcripts_dir:
            return Path(self.costs.transcripts_dir).expanduser()
        return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.root.resolve()))

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
            **policy_raw.get("solution_design", {}),
            **policy_raw.get("scientific_review", {}),
            **({"evaluation": policy_raw["evaluation"]} if "evaluation" in policy_raw else {}),
        }
    )
    values = ValuesConfig.model_validate(_load_yaml(root / "config" / "research-values.yaml"))
    scoring = ScoringConfig.model_validate(_load_yaml(root / "config" / "scoring.yaml"))
    costs = CostsConfig.model_validate(_load_yaml(root / "config" / "costs.yaml"))
    return Settings(root=root, sources=sources, policy=policy, values=values, scoring=scoring, costs=costs)

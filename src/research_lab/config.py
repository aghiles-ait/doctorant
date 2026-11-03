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


class SourcesConfig(BaseModel):
    version: str
    default_sources: list[Source]
    default_max_results: int = Field(ge=1)
    retry: RetryConfig = RetryConfig()
    providers: dict[Source, ProviderConfig]


class PolicyConfig(BaseModel):
    version: str
    min_corpus_size: int = Field(ge=0)
    allow_partial_search: bool = False


class Settings(BaseModel):
    root: Path
    sources: SourcesConfig
    policy: PolicyConfig

    @property
    def projects_dir(self) -> Path:
        return self.root / "research" / "projects"

    def config_hash(self) -> str:
        """Empreinte de la configuration effective, consignée dans chaque recherche."""
        payload = {"sources": self.sources.model_dump(mode="json"), "policy": self.policy.model_dump(mode="json")}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


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
    policy = PolicyConfig.model_validate({"version": policy_raw.get("version"), **policy_raw.get("literature_search", {})})
    return Settings(root=root, sources=sources, policy=policy)

"""Persistance des projets sous forme de fichiers (research/projects/<id>/).

Sprint 1 : project.yaml, papers.json et search-log.json. La migration vers SQLite
(knowledge/research.db) est prévue au sprint 2 derrière la même interface.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from research_lab.schemas.paper import Paper
from research_lab.schemas.project import Project, StateChange
from research_lab.schemas.search import SearchExecution
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import check_transition

_PAPERS = TypeAdapter(list[Paper])
_SEARCH_LOG = TypeAdapter(list[SearchExecution])


class ProjectNotFound(Exception):
    pass


def _atomic_write(path: Path, content: str) -> None:
    """Écrit dans un fichier temporaire puis le renomme : jamais de fichier à moitié écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class ProjectRepository:
    def __init__(self, projects_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        self.dir = projects_dir / project_id

    @property
    def project_file(self) -> Path:
        return self.dir / "project.yaml"

    @property
    def papers_file(self) -> Path:
        return self.dir / "papers.json"

    @property
    def search_log_file(self) -> Path:
        return self.dir / "search-log.json"

    @property
    def scope_file(self) -> Path:
        return self.dir / "scope.md"

    def exists(self) -> bool:
        return self.project_file.is_file()

    # --- Projet -----------------------------------------------------------

    def create(self, topic: str, actor: str) -> Project:
        if self.exists():
            raise FileExistsError(f"Le projet {self.project_id} existe déjà")
        timestamp = now()
        project = Project(
            project_id=self.project_id,
            topic=topic,
            state=ResearchState.NEW,
            created_at=timestamp,
            updated_at=timestamp,
            history=[StateChange(from_state=None, to_state=ResearchState.NEW, at=timestamp, actor=actor)],
        )
        self.save_project(project)
        self.save_papers([])
        self.save_search_log([])
        return project

    def load_project(self) -> Project:
        if not self.exists():
            raise ProjectNotFound(f"Projet introuvable : {self.dir}")
        with self.project_file.open(encoding="utf-8") as f:
            return Project.model_validate(yaml.safe_load(f))

    def save_project(self, project: Project) -> None:
        data = project.model_dump(mode="json")
        _atomic_write(self.project_file, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

    def transition(self, target: ResearchState, actor: str) -> Project:
        project = self.load_project()
        check_transition(project.state, target, self.dir)
        timestamp = now()
        project.history.append(StateChange(from_state=project.state, to_state=target, at=timestamp, actor=actor))
        project.state = target
        project.updated_at = timestamp
        self.save_project(project)
        return project

    # --- Corpus et journal ---------------------------------------------------

    def load_papers(self) -> list[Paper]:
        if not self.papers_file.exists():
            return []
        return _PAPERS.validate_json(self.papers_file.read_bytes())

    def save_papers(self, papers: list[Paper]) -> None:
        _atomic_write(self.papers_file, _PAPERS.dump_json(papers, indent=2).decode() + "\n")

    def load_search_log(self) -> list[SearchExecution]:
        if not self.search_log_file.exists():
            return []
        return _SEARCH_LOG.validate_json(self.search_log_file.read_bytes())

    def save_search_log(self, log: list[SearchExecution]) -> None:
        _atomic_write(self.search_log_file, _SEARCH_LOG.dump_json(log, indent=2).decode() + "\n")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

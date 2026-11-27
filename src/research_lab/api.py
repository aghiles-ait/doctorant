"""Serveur web du laboratoire (`research-lab serve`) : API sur la base, et l'interface React compilée (`web/dist`).

Chaque requête relit la base : l'interface montre toujours l'état courant. Les routes d'écriture font les mêmes
opérations déterministes que la CLI, avec les mêmes contrôles (création et suppression de projet, dépôt de
scope.md, paramètres de config/, transition, recherche, texte intégral, régénération des exports, coûts, sauvegarde). Les décisions humaines restent dans le terminal
(`gate approve`, `gate revise`, `eval rate`) : aucune route ne les expose. Le serveur n'écoute que sur 127.0.0.1
et refuse les écritures venues d'une autre origine.
"""

import getpass
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from research_lab.backup import backup_lab
from research_lab.config import Settings, load_settings
from research_lab.config_edit import ConfigEditError, update_config
from research_lab.costs import sync
from research_lab.fulltext import FulltextFetcher
from research_lab.providers import build_providers
from research_lab.review import ReviewError, fetch_fulltexts
from research_lab.schemas.paper import Source
from research_lab.schemas.search import SearchQuery
from research_lab.scope import scope_sections
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectNotFound, ProjectRepository, pdf_path
from research_lab.watch import SearchNotAllowed, run_search
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError
from research_lab.views import (
    DELIVERABLES,
    DOCUMENTS,
    config_view,
    project_ids,
    project_summary,
    project_view,
    workflow,
)

_DELIVERABLE_FILES = {name for names in DELIVERABLES.values() for name in names}
_PAPER_ID = re.compile(r"^PAPER-\d{3,}$")
_MEDIA_TYPES = {".json": "application/json", ".md": "text/markdown", ".bib": "text/plain", ".yaml": "text/plain"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _actor() -> str:
    return f"{getpass.getuser()} (interface web)"


class NewProject(BaseModel):
    project_id: str
    topic: str


class ConfigUpdate(BaseModel):
    data: dict


class DeleteRequest(BaseModel):
    confirm: str  # identifiant du projet, retapé


class ScopeUpload(BaseModel):
    text: str = Field(min_length=1)


class TransitionRequest(BaseModel):
    target: ResearchState
    force: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    date_from: date | None = None
    date_to: date | None = None
    sources: list[Source] | None = None
    max_results: int | None = Field(default=None, ge=1)
    gap_id: str | None = None


def create_app(root: Path | None = None, web_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="research-lab", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Une page d'un autre site ouverte dans le navigateur ne doit pas pouvoir écrire dans la base.
        origin = request.headers.get("origin")
        if request.method != "GET" and origin and urlparse(origin).hostname not in _LOCAL_HOSTS:
            return JSONResponse({"detail": f"Origine refusée : {origin}"}, status_code=403)
        return await call_next(request)

    @contextmanager
    def lab() -> Iterator[tuple[Settings, Database]]:
        # Une connexion par requête : SQLite ne partage pas une connexion entre les fils du serveur.
        settings = load_settings(root)
        db = Database(settings.db_path)
        try:
            yield settings, db
        finally:
            db.conn.close()

    def repository(settings: Settings, db: Database, project_id: str) -> ProjectRepository:
        if project_id not in project_ids(db):
            raise HTTPException(404, f"Projet inconnu : {project_id}")
        return ProjectRepository(db, settings.projects_dir, project_id, settings.papers_dir)

    @app.get("/api/workflow")
    def get_workflow() -> dict:
        """États du workflow et livrables produits à chaque état."""
        return workflow()

    @app.get("/api/config")
    def get_config() -> dict:
        """Paramètres communs à tous les projets (config/*.yaml), en lecture seule."""
        return config_view(load_settings(root))

    @app.put("/api/config/{name}")
    def put_config(name: str, body: ConfigUpdate) -> dict:
        """Modifie les valeurs d'un fichier de config/, validé avant écriture ; commentaires conservés."""
        before = load_settings(root)
        try:
            update_config(before.root, name, body.data)
        except ConfigEditError as exc:
            raise HTTPException(422, str(exc))
        after = load_settings(root)
        return {
            # Les évaluations sur les valeurs faites avec l'ancienne pondération sont à refaire.
            "values_changed": after.values_hash() != before.values_hash(),
            "config_changed": after.config_hash() != before.config_hash(),
        }

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        with lab() as (settings, db):
            return [
                project_summary(ProjectRepository(db, settings.projects_dir, pid, settings.papers_dir))
                for pid in project_ids(db)
            ]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        with lab() as (settings, db):
            return project_view(repository(settings, db, project_id), settings)

    @app.get("/api/projects/{project_id}/files/{name}")
    def get_file(project_id: str, name: str) -> FileResponse:
        """Livrable du projet ; seuls les noms connus sont servis."""
        with lab() as (settings, db):
            path = repository(settings, db, project_id).dir / name
        if name not in _DELIVERABLE_FILES or not path.is_file():
            raise HTTPException(404, f"Livrable introuvable : {name}")
        return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix, "text/plain"))

    @app.get("/api/projects/{project_id}/documents/{name}", response_class=PlainTextResponse)
    def get_document(project_id: str, name: str) -> str:
        """Texte d'un document rédigé (scope.md, literature-review.md, research-proposal.md)."""
        with lab() as (settings, db):
            path = repository(settings, db, project_id).dir / name
        if name not in DOCUMENTS or not path.is_file():
            raise HTTPException(404, f"Document introuvable : {name}")
        return path.read_text(encoding="utf-8")

    @app.get("/api/papers/{paper_id}/pdf")
    def get_pdf(paper_id: str) -> FileResponse:
        with lab() as (settings, _):
            path = pdf_path(settings.papers_dir, paper_id)
        if not _PAPER_ID.match(paper_id) or not path.is_file():
            raise HTTPException(404, f"PDF introuvable : {paper_id}")
        return FileResponse(path, media_type="application/pdf")

    # --- écritures : mêmes opérations que la CLI -------------------------------

    @app.post("/api/projects", status_code=201)
    def create_project(body: NewProject) -> dict:
        """`project init` : crée un projet à l'état NEW."""
        with lab() as (settings, db):
            repo = ProjectRepository(db, settings.projects_dir, body.project_id, settings.papers_dir)
            try:
                repo.create(body.topic, actor=_actor())
            except FileExistsError as exc:
                raise HTTPException(409, str(exc))
            except ValidationError as exc:
                raise HTTPException(422, f"Projet invalide : {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")
            return project_summary(repo)

    @app.post("/api/projects/{project_id}/delete")
    def delete_project(project_id: str, body: DeleteRequest) -> dict:
        """`project delete` : suppression définitive, confirmée en retapant l'identifiant."""
        if body.confirm != project_id:
            raise HTTPException(422, "Identifiant différent : rien n'a été supprimé")
        with lab() as (settings, db):
            return repository(settings, db, project_id).delete()

    @app.put("/api/projects/{project_id}/documents/scope.md")
    def upload_scope(project_id: str, body: ScopeUpload) -> dict:
        """Dépose scope.md à l'état SCOPING ; ses sections numérotées fondent ensuite les raisons de tri."""
        with lab() as (settings, db):
            repo = repository(settings, db, project_id)
            state = repo.load_project().state
            if state != ResearchState.SCOPING:
                raise HTTPException(409, f"Le périmètre se dépose à l'état {ResearchState.SCOPING} (projet : {state})")
            sections = scope_sections(body.text)
            if not sections:
                raise HTTPException(422, "Aucune section numérotée (« ## 1. Question », « ## 2. Périmètre »…) : "
                                         "les raisons de tri doivent pouvoir les citer (« §2 — … »)")
            repo.scope_file.write_text(body.text, encoding="utf-8")
            return {"sections": sections}

    @app.post("/api/projects/{project_id}/transition")
    def transition(project_id: str, body: TransitionRequest) -> dict:
        """`project transition [--force]` ; les gates restent refusées, forcées ou non."""
        with lab() as (settings, db):
            repo = repository(settings, db, project_id)
            try:
                project = repo.transition(body.target, actor=_actor(), policy=settings.policy, force=body.force)
            except TransitionError as exc:
                raise HTTPException(409, f"Transition refusée : {exc}")
            return {"state": project.state}

    @app.post("/api/projects/{project_id}/search")
    def search(project_id: str, body: SearchRequest) -> dict:
        """`watch search` : une requête, journalisée ; une source en échec laisse le corpus inchangé."""
        with lab() as (settings, db):
            repo = repository(settings, db, project_id)
            query = SearchQuery(
                text=body.query, date_from=body.date_from, date_to=body.date_to,
                max_results=body.max_results or settings.sources.default_max_results,
            )
            try:
                providers = build_providers(settings, body.sources or settings.sources.default_sources)
                execution = run_search(repo, settings, providers, query, gap_id=body.gap_id)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            except (SearchNotAllowed, ProjectNotFound) as exc:
                raise HTTPException(409, str(exc))
            return execution.model_dump(mode="json")

    @app.post("/api/projects/{project_id}/fulltext")
    def fetch_fulltext(project_id: str) -> list[dict]:
        """`fulltext fetch` : texte intégral des publications incluses qui ne l'ont pas encore."""
        with lab() as (settings, db):
            repo = repository(settings, db, project_id)
            try:
                records = list(fetch_fulltexts(repo, settings, FulltextFetcher(settings)))
            except ReviewError as exc:
                raise HTTPException(409, str(exc))
            return [r.model_dump(mode="json", include={"paper_id", "status", "page_count", "error"}) for r in records]

    @app.post("/api/projects/{project_id}/repair")
    def repair(project_id: str) -> dict:
        """`project resume --repair` : régénère les exports depuis la base."""
        with lab() as (settings, db):
            repo = repository(settings, db, project_id)
            repo.export()
            return {"stale_exports": repo.stale_exports()}

    @app.post("/api/costs/sync")
    def costs_sync() -> dict:
        """`costs sync` : consommation lue dans les transcriptions de Claude Code."""
        with lab() as (settings, db):
            return {"responses": sync(db, settings)}

    @app.post("/api/backup")
    def backup() -> dict:
        """`db backup` dans backups/<date>/ à la racine du laboratoire."""
        with lab() as (settings, db):
            target = settings.root / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                version = backup_lab(settings, db, target)
            except FileExistsError as exc:
                raise HTTPException(409, str(exc))
            return {"path": str(target), "schema_version": version}

    if web_dist and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app

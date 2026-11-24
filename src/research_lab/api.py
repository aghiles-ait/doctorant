"""Serveur web du laboratoire (`research-lab serve`) : API en lecture seule sur la base, et l'interface React
compilée (`web/dist`).

Chaque requête relit la base : l'interface montre toujours l'état courant. Aucune route n'écrit ; les décisions
humaines restent dans le terminal (`gate approve`, `eval rate`). Le serveur n'écoute que sur 127.0.0.1.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from research_lab.config import Settings, load_settings
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectRepository, pdf_path
from research_lab.views import DELIVERABLES, DOCUMENTS, project_ids, project_summary, project_view, workflow

_DELIVERABLE_FILES = {name for names in DELIVERABLES.values() for name in names}
_PAPER_ID = re.compile(r"^PAPER-\d{3,}$")
_MEDIA_TYPES = {".json": "application/json", ".md": "text/markdown", ".bib": "text/plain", ".yaml": "text/plain"}


def create_app(root: Path | None = None, web_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="research-lab", docs_url="/api/docs", openapi_url="/api/openapi.json")

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

    if web_dist and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app

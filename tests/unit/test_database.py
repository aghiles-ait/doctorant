"""Base partagée : migrations, garanties d'immuabilité, atomicité, import des projets du sprint 1."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from research_lab.corpus import merge_hits
from research_lab.schemas.paper import Paper, PaperMetadata, Source, SourceHit
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus
from research_lab.storage.database import SCHEMA_VERSION, Database
from research_lab.storage.repositories import (
    ImportConflict,
    ProjectRepository,
    import_project_files,
    load_all_papers,
    next_search_id,
)

T0 = datetime(2026, 11, 3, tzinfo=UTC)


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "research.db")


def _repo(db, tmp_path, project_id="alpha") -> ProjectRepository:
    repo = ProjectRepository(db, tmp_path / "projects", project_id)
    repo.create(f"Topic {project_id}", actor="alice")
    return repo


def _hit(source_id: str, **meta) -> SourceHit:
    return SourceHit(source=Source.OPENALEX, source_id=source_id, metadata=PaperMetadata(**meta))


def _execution(search_id: str, project_id: str) -> SearchExecution:
    return SearchExecution(
        search_id=search_id, project_id=project_id, query=SearchQuery(text="q"), sources=[Source.OPENALEX],
        started_at=T0, finished_at=T0, status=SearchStatus.COMPLETED, results=[], tool_version="0", config_hash="h",
    )


def _search(repo: ProjectRepository, hits: list[SourceHit]) -> SearchExecution:
    """Reproduit ce que fait watch.run_search, sans appel réseau."""
    search_id = next_search_id(repo.db)
    papers = load_all_papers(repo.db)
    report = merge_hits(papers, hits, search_id, "q", T0)
    touched = set(report.touched_paper_ids)
    execution = _execution(search_id, repo.project_id)
    repo.record_search(execution, [p for p in papers if p.paper_id in touched])
    return execution


# --- Migrations ------------------------------------------------------------------


def test_schema_is_created_once_and_reopening_is_harmless(tmp_path, db):
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    _repo(db, tmp_path)
    db.close()
    reopened = Database(tmp_path / "research.db")
    assert reopened.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_newer_schema_is_refused(tmp_path, db):
    db.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    db.close()
    with pytest.raises(RuntimeError, match="plus récent"):
        Database(tmp_path / "research.db")


# --- Garanties portées par SQLite -------------------------------------------------


def test_identifiers_and_history_cannot_be_altered(tmp_path, db):
    repo = _repo(db, tmp_path)
    _search(repo, [_hit("W1", title="A", openalex_id="W1")])
    statements = [
        "UPDATE papers SET paper_id = 'PAPER-999'",
        "DELETE FROM papers",
        "UPDATE searches SET status = 'failed'",
        "DELETE FROM searches",
        "UPDATE state_changes SET actor = 'mallory'",
        "DELETE FROM state_changes",
    ]
    for sql in statements:
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(sql)


def test_paper_without_identifier_is_rejected_by_the_database(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO papers (paper_id, title, authors) VALUES ('PAPER-001', 'T', '[]')")


def test_failed_write_leaves_nothing_behind(tmp_path, db):
    repo = _repo(db, tmp_path)
    papers = [Paper(paper_id="PAPER-001", title="A", openalex_id="W1", provenance=[
        {"source": "openalex", "source_id": "W1", "search_id": "SEARCH-001", "query": "q", "retrieved_at": T0}
    ])]
    # La recherche déclare un autre projet : la clé étrangère échoue au milieu de la transaction.
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_search(_execution("SEARCH-001", "unknown-project"), papers)
    assert db.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0] == 0


# --- Corpus partagé entre projets -------------------------------------------------


def test_paper_found_by_two_projects_keeps_one_id(tmp_path, db):
    alpha, beta = _repo(db, tmp_path, "alpha"), _repo(db, tmp_path, "beta")
    _search(alpha, [_hit("W1", title="Shared", openalex_id="W1"), _hit("W2", title="Alpha only", openalex_id="W2")])
    execution = _search(beta, [_hit("W1", title="Shared", openalex_id="W1"), _hit("W3", title="Beta only", openalex_id="W3")])

    assert execution.search_id == "SEARCH-002"  # identifiants de recherche globaux
    assert [p.paper_id for p in load_all_papers(db)] == ["PAPER-001", "PAPER-002", "PAPER-003"]
    assert [p.paper_id for p in alpha.load_papers()] == ["PAPER-001", "PAPER-002"]
    assert [p.paper_id for p in beta.load_papers()] == ["PAPER-001", "PAPER-003"]
    # Chaque projet ne voit que la provenance de ses propres recherches.
    assert [p.search_id for p in beta.load_papers()[0].provenance] == ["SEARCH-002"]
    assert [s.search_id for s in alpha.load_search_log()] == ["SEARCH-001"]


def test_conflicting_identifiers_are_reported_not_merged(tmp_path, db):
    repo = _repo(db, tmp_path)
    _search(repo, [_hit("W1", title="Preprint", arxiv_id="2501.00001"), _hit("W2", title="Published", doi="10.1000/x")])
    # Cette source révèle que les deux entrées sont la même publication.
    papers = load_all_papers(db)
    report = merge_hits(papers, [_hit("W3", title="Published", doi="10.1000/x", arxiv_id="2501.00001")], "SEARCH-002", "q", T0)
    assert "PAPER-002 et PAPER-001 semblent être la même publication" in report.warnings[0]
    assert papers[1].arxiv_id is None
    repo.record_search(_execution("SEARCH-002", "alpha"), papers)  # aucune violation d'unicité


# --- Import des projets du sprint 1 -----------------------------------------------


def _write_sprint1_project(projects_dir, project_id="legacy", paper_ids=("PAPER-001", "PAPER-002"), search_id="SEARCH-001"):
    folder = projects_dir / project_id
    folder.mkdir(parents=True)
    (folder / "project.yaml").write_text(
        f"project_id: {project_id}\ntopic: Legacy\nstate: LITERATURE_SEARCH\n"
        "created_at: '2026-10-31T15:00:00Z'\nupdated_at: '2026-10-31T15:30:00Z'\n"
        "history:\n- {from_state: null, to_state: NEW, at: '2026-10-31T15:00:00Z', actor: alice}\n"
        "- {from_state: NEW, to_state: SCOPING, at: '2026-10-31T15:10:00Z', actor: alice}\n"
        "- {from_state: SCOPING, to_state: LITERATURE_SEARCH, at: '2026-10-31T15:20:00Z', actor: alice}\n"
    )
    papers = [
        {"paper_id": pid, "title": f"Paper {pid}", "openalex_id": f"W{i}", "status": "candidate",
         "provenance": [{"source": "openalex", "source_id": f"W{i}", "search_id": search_id, "query": "q",
                         "retrieved_at": "2026-10-31T15:33:36Z"}]}
        for i, pid in enumerate(paper_ids, start=1)
    ]
    (folder / "papers.json").write_text(json.dumps(papers))
    (folder / "search-log.json").write_text(json.dumps([_execution(search_id, project_id).model_dump(mode="json")]))
    return folder


def test_import_keeps_identifiers_history_and_backup(tmp_path, db):
    folder = _write_sprint1_project(tmp_path / "projects")
    original = (folder / "papers.json").read_text()

    assert import_project_files(db, tmp_path / "projects", "legacy") == 2

    repo = ProjectRepository(db, tmp_path / "projects", "legacy")
    assert [p.paper_id for p in repo.load_papers()] == ["PAPER-001", "PAPER-002"]
    assert [s.search_id for s in repo.load_search_log()] == ["SEARCH-001"]
    assert len(repo.load_project().history) == 3
    assert (folder / "migration-backup" / "papers.json").read_text() == original
    # Après import, les nouveaux identifiants continuent la numérotation.
    assert next_search_id(db) == "SEARCH-002"


def test_import_conflict_writes_nothing(tmp_path, db):
    other = _repo(db, tmp_path, "other")
    _search(other, [_hit("W99", title="Other paper", openalex_id="W99")])  # occupe PAPER-001 et SEARCH-001
    _write_sprint1_project(tmp_path / "projects")

    with pytest.raises(ImportConflict, match="PAPER-001 existe déjà"):
        import_project_files(db, tmp_path / "projects", "legacy")
    assert not ProjectRepository(db, tmp_path / "projects", "legacy").exists()
    assert db.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1

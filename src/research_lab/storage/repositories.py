"""Accès aux projets et au corpus partagé.

La base SQLite (knowledge/research.db) est la source de vérité. Après chaque écriture,
les fichiers project.yaml, papers.json et search-log.json du projet sont régénérés
pour rester lisibles ; les modifier à la main n'a aucun effet.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from research_lab.config import PolicyConfig
from research_lab.corpus import check_corpus
from research_lab.schemas.evidence import Evidence, FulltextRecord, FulltextStatus
from research_lab.schemas.gap import Alignment, Gap, GapDraft
from research_lab.schemas.gate import Gate, GateDecision, GateSubmission
from research_lab.schemas.paper import Paper, PaperStatus, Provenance, ScreeningDecision
from research_lab.schemas.project import Project, StateChange
from research_lab.schemas.search import SearchExecution
from research_lab.storage.database import Database
from research_lab.validation.outputs import check_literature_review
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import ProjectFacts, check_transition

_PAPERS = TypeAdapter(list[Paper])
_SEARCH_LOG = TypeAdapter(list[SearchExecution])

# Tri numérique des identifiants (PAPER-1000 après PAPER-999).
_PAPER_ORDER = "CAST(substr(paper_id, 7) AS INTEGER)"
_SEARCH_ORDER = "CAST(substr(search_id, 8) AS INTEGER)"
_EVIDENCE_ORDER = "CAST(substr(evidence_id, 4) AS INTEGER)"
_GAP_ORDER = "CAST(substr(gap_id, 5) AS INTEGER)"


class ProjectNotFound(Exception):
    pass


class ImportConflict(Exception):
    pass


class FulltextTampered(Exception):
    pass


def _atomic_write(path: Path, content: str | bytes) -> None:
    """Écrit dans un fichier temporaire puis le renomme : jamais de fichier à moitié écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode() if isinstance(content, str) else content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- Conversions ligne SQLite <-> modèle -------------------------------------


def _paper_row(paper: Paper) -> dict:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": json.dumps(paper.authors, ensure_ascii=False),
        "abstract": paper.abstract,
        "published": paper.published.isoformat() if paper.published else None,
        "venue": paper.venue,
        "work_type": paper.work_type,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "openalex_id": paper.openalex_id,
        "url": paper.url,
    }


def _paper_from_row(row: sqlite3.Row, provenance: list[Provenance], status: str = PaperStatus.CANDIDATE) -> Paper:
    data = dict(row)
    data["authors"] = json.loads(data["authors"])
    data.pop("project_status", None)
    return Paper.model_validate({**data, "status": status, "provenance": provenance})


def _group_provenance(rows: list[sqlite3.Row]) -> dict[str, list[Provenance]]:
    grouped: dict[str, list[Provenance]] = {}
    for row in rows:
        data = dict(row)
        grouped.setdefault(data.pop("paper_id"), []).append(Provenance.model_validate(data))
    return grouped


def _upsert_paper(conn: sqlite3.Connection, paper: Paper) -> None:
    row = _paper_row(paper)
    columns = ", ".join(row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in row if c != "paper_id")
    conn.execute(
        f"INSERT INTO papers ({columns}) VALUES ({', '.join(':' + c for c in row)}) "
        f"ON CONFLICT(paper_id) DO UPDATE SET {updates}",
        row,
    )


def _insert_provenance(conn: sqlite3.Connection, paper_id: str, prov: Provenance) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO provenance (paper_id, search_id, source, source_id, query, retrieved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (paper_id, prov.search_id, prov.source, prov.source_id, prov.query, prov.retrieved_at.isoformat()),
    )


def _insert_search(conn: sqlite3.Connection, execution: SearchExecution) -> None:
    conn.execute(
        "INSERT INTO searches (search_id, project_id, gap_id, started_at, status, record) VALUES (?, ?, ?, ?, ?, ?)",
        (
            execution.search_id,
            execution.project_id,
            execution.gap_id,
            execution.started_at.isoformat(),
            execution.status,
            execution.model_dump_json(),
        ),
    )


def _insert_state_change(conn: sqlite3.Connection, project_id: str, change: StateChange) -> None:
    conn.execute(
        "INSERT INTO state_changes (project_id, from_state, to_state, at, actor) VALUES (?, ?, ?, ?, ?)",
        (project_id, change.from_state, change.to_state, change.at.isoformat(), change.actor),
    )


# --- Corpus partagé -----------------------------------------------------------


def load_all_papers(db: Database) -> list[Paper]:
    """Toutes les publications de la base, tous projets confondus (pour la déduplication)."""
    provenance = _group_provenance(
        db.conn.execute(
            "SELECT paper_id, source, source_id, search_id, query, retrieved_at FROM provenance ORDER BY rowid"
        ).fetchall()
    )
    rows = db.conn.execute(f"SELECT * FROM papers ORDER BY {_PAPER_ORDER}").fetchall()
    return [_paper_from_row(row, provenance[row["paper_id"]]) for row in rows]


def next_search_id(db: Database) -> str:
    row = db.conn.execute(f"SELECT search_id FROM searches ORDER BY {_SEARCH_ORDER} DESC LIMIT 1").fetchone()
    highest = int(row["search_id"].split("-")[1]) if row else 0
    return f"SEARCH-{highest + 1:03d}"


def next_evidence_id(db: Database) -> str:
    row = db.conn.execute(f"SELECT evidence_id FROM evidence ORDER BY {_EVIDENCE_ORDER} DESC LIMIT 1").fetchone()
    highest = int(row["evidence_id"].split("-")[1]) if row else 0
    return f"EV-{highest + 1:03d}"


def next_gap_id(db: Database) -> str:
    row = db.conn.execute(f"SELECT gap_id FROM gaps ORDER BY {_GAP_ORDER} DESC LIMIT 1").fetchone()
    highest = int(row["gap_id"].split("-")[1]) if row else 0
    return f"GAP-{highest + 1:03d}"


# --- Texte intégral (partagé entre projets, fichiers dans knowledge/papers/) ----------


def pdf_path(papers_dir: Path, paper_id: str) -> Path:
    return papers_dir / f"{paper_id}.pdf"


def pages_path(papers_dir: Path, paper_id: str) -> Path:
    return papers_dir / f"{paper_id}.pages.json"


def load_fulltext(db: Database, paper_id: str) -> FulltextRecord | None:
    row = db.conn.execute("SELECT * FROM fulltexts WHERE paper_id = ?", (paper_id,)).fetchone()
    return FulltextRecord.model_validate(dict(row)) if row else None


def save_fulltext(
    db: Database, papers_dir: Path, record: FulltextRecord, pdf: bytes | None, pages_json: bytes | None
) -> None:
    """Écrit les fichiers puis l'enregistrement : la base ne référence jamais un fichier absent."""
    if record.status == FulltextStatus.AVAILABLE:
        if pdf is None or pages_json is None:
            raise ValueError("un texte disponible exige le PDF et le texte extrait")
        _atomic_write(pdf_path(papers_dir, record.paper_id), pdf)
        _atomic_write(pages_path(papers_dir, record.paper_id), pages_json)
    row = record.model_dump(mode="json")
    columns = ", ".join(row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in row if c != "paper_id")
    with db.transaction() as conn:
        conn.execute(
            f"INSERT INTO fulltexts ({columns}) VALUES ({', '.join(':' + c for c in row)}) "
            f"ON CONFLICT(paper_id) DO UPDATE SET {updates}",
            row,
        )


def read_pages(db: Database, papers_dir: Path, paper_id: str) -> tuple[list[str], str]:
    """Texte intégral page par page et son empreinte, après contrôle d'intégrité."""
    record = load_fulltext(db, paper_id)
    if record is None or record.status != FulltextStatus.AVAILABLE:
        raise FileNotFoundError(f"Pas de texte intégral disponible pour {paper_id}")
    data = pages_path(papers_dir, paper_id).read_bytes()
    digest = sha256(data)
    if digest != record.text_sha256:
        raise FulltextTampered(f"{pages_path(papers_dir, paper_id)} a été modifié depuis son extraction")
    return json.loads(data), digest


# --- Projet -------------------------------------------------------------------


class ProjectRepository:
    def __init__(self, db: Database, projects_dir: Path, project_id: str) -> None:
        self.db = db
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
        row = self.db.conn.execute("SELECT 1 FROM projects WHERE project_id = ?", (self.project_id,)).fetchone()
        return row is not None

    def has_unimported_files(self) -> bool:
        """Projet créé avant la base SQLite (sprint 1) et pas encore importé."""
        return not self.exists() and self.project_file.is_file()

    def create(self, topic: str, actor: str) -> Project:
        if self.exists():
            raise FileExistsError(f"Le projet {self.project_id} existe déjà")
        if self.has_unimported_files():
            raise FileExistsError(
                f"{self.project_file} existe mais n'est pas dans la base : `research-lab db import-files {self.project_id}`"
            )
        timestamp = now()
        project = Project(
            project_id=self.project_id,
            topic=topic,
            state=ResearchState.NEW,
            created_at=timestamp,
            updated_at=timestamp,
            history=[StateChange(from_state=None, to_state=ResearchState.NEW, at=timestamp, actor=actor)],
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, topic, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (project.project_id, project.topic, project.state, timestamp.isoformat(), timestamp.isoformat()),
            )
            _insert_state_change(conn, project.project_id, project.history[0])
        self.export()
        return project

    def load_project(self) -> Project:
        row = self.db.conn.execute("SELECT * FROM projects WHERE project_id = ?", (self.project_id,)).fetchone()
        if row is None:
            raise ProjectNotFound(f"Projet introuvable dans la base : {self.project_id}")
        history = self.db.conn.execute(
            "SELECT from_state, to_state, at, actor FROM state_changes WHERE project_id = ? ORDER BY rowid",
            (self.project_id,),
        ).fetchall()
        return Project.model_validate({**dict(row), "history": [dict(h) for h in history]})

    def facts(self, policy: PolicyConfig) -> ProjectFacts:
        """État vérifiable du projet, sur lequel reposent les préconditions des transitions."""
        papers = self.load_papers()
        evidence = self.load_evidence()
        included = [p for p in papers if p.status == PaperStatus.INCLUDED]
        attempted = {r["paper_id"] for r in self.db.conn.execute("SELECT paper_id FROM fulltexts")}
        review_file = self.dir / "literature-review.md"
        review_text = review_file.read_text(encoding="utf-8") if review_file.exists() else None
        return ProjectFacts(
            project_dir=self.dir,
            corpus_status=check_corpus(papers, self.load_search_log(), policy.min_corpus_size).status,
            candidate_count=sum(p.status == PaperStatus.CANDIDATE for p in papers),
            included_count=len(included),
            without_fulltext_attempt=[p.paper_id for p in included if p.paper_id not in attempted],
            active_evidence_count=sum(e.active for e in evidence),
            review_errors=check_literature_review(review_text, papers, evidence).errors,
        )

    def transition(self, target: ResearchState, actor: str, policy: PolicyConfig) -> Project:
        project = self.load_project()
        check_transition(project.state, target, self.facts(policy))
        change = StateChange(from_state=project.state, to_state=target, at=now(), actor=actor)
        with self.db.transaction() as conn:
            self._apply_state_change(conn, change)
        self.export()
        return self.load_project()

    def _apply_state_change(self, conn: sqlite3.Connection, change: StateChange) -> None:
        """Change l'état si le projet est toujours dans l'état d'origine (sinon, une autre écriture est passée)."""
        updated = conn.execute(
            "UPDATE projects SET state = ?, updated_at = ? WHERE project_id = ? AND state = ?",
            (change.to_state, change.at.isoformat(), self.project_id, change.from_state),
        ).rowcount
        if not updated:
            raise RuntimeError(f"{self.project_id} n'est plus à l'état {change.from_state}")
        _insert_state_change(conn, self.project_id, change)

    # --- Corpus et journal du projet -----------------------------------------

    def paper_ids(self) -> set[str]:
        rows = self.db.conn.execute("SELECT paper_id FROM project_papers WHERE project_id = ?", (self.project_id,))
        return {r["paper_id"] for r in rows}

    def load_papers(self) -> list[Paper]:
        """Publications du projet ; la provenance est limitée aux recherches de ce projet."""
        provenance = _group_provenance(
            self.db.conn.execute(
                "SELECT pr.paper_id, pr.source, pr.source_id, pr.search_id, pr.query, pr.retrieved_at "
                "FROM provenance pr JOIN searches s USING (search_id) WHERE s.project_id = ? ORDER BY pr.rowid",
                (self.project_id,),
            ).fetchall()
        )
        rows = self.db.conn.execute(
            f"SELECT p.*, pp.status AS project_status FROM papers p JOIN project_papers pp USING (paper_id) "
            f"WHERE pp.project_id = ? ORDER BY {_PAPER_ORDER}",
            (self.project_id,),
        ).fetchall()
        return [_paper_from_row(row, provenance[row["paper_id"]], row["project_status"]) for row in rows]

    def load_search_log(self) -> list[SearchExecution]:
        rows = self.db.conn.execute(
            f"SELECT record FROM searches WHERE project_id = ? ORDER BY {_SEARCH_ORDER}", (self.project_id,)
        )
        return [SearchExecution.model_validate_json(r["record"]) for r in rows]

    def record_search(self, execution: SearchExecution, touched: list[Paper]) -> None:
        """Enregistre une recherche et ses résultats en une seule transaction.

        `touched` contient les publications créées ou complétées par cette recherche ;
        celles qui ne sont pas encore dans le projet y sont rattachées.
        """
        in_project = self.paper_ids()
        with self.db.transaction() as conn:
            _insert_search(conn, execution)
            for paper in touched:
                _upsert_paper(conn, paper)
                if paper.paper_id not in in_project:
                    conn.execute(
                        "INSERT INTO project_papers (project_id, paper_id, status) VALUES (?, ?, ?)",
                        (self.project_id, paper.paper_id, PaperStatus.CANDIDATE),
                    )
                for prov in paper.provenance:
                    if prov.search_id == execution.search_id:
                        _insert_provenance(conn, paper.paper_id, prov)
        self.export()

    # --- Tri -----------------------------------------------------------------------

    def get_paper(self, paper_id: str) -> Paper | None:
        return next((p for p in self.load_papers() if p.paper_id == paper_id), None)

    def record_decision(self, decision: ScreeningDecision) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO screening_decisions (project_id, paper_id, decision, reason, actor, at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, decision.paper_id, decision.decision, decision.reason, decision.actor,
                 decision.at.isoformat()),
            )
            conn.execute(
                "UPDATE project_papers SET status = ? WHERE project_id = ? AND paper_id = ?",
                (decision.decision, self.project_id, decision.paper_id),
            )
        self.export()

    def load_decisions(self) -> list[ScreeningDecision]:
        rows = self.db.conn.execute(
            "SELECT * FROM screening_decisions WHERE project_id = ? ORDER BY rowid", (self.project_id,)
        )
        return [ScreeningDecision.model_validate(dict(r)) for r in rows]

    # --- Preuves --------------------------------------------------------------------

    def load_evidence(self) -> list[Evidence]:
        rows = self.db.conn.execute(
            f"SELECT * FROM evidence WHERE project_id = ? ORDER BY {_EVIDENCE_ORDER}", (self.project_id,)
        )
        return [Evidence.model_validate(dict(r)) for r in rows]

    def add_evidence(self, evidence: Evidence) -> None:
        row = evidence.model_dump(mode="json")
        with self.db.transaction() as conn:
            conn.execute(f"INSERT INTO evidence ({', '.join(row)}) VALUES ({', '.join(':' + c for c in row)})", row)
        self.export()

    def withdraw_evidence(self, evidence_id: str, reason: str) -> None:
        with self.db.transaction() as conn:
            updated = conn.execute(
                "UPDATE evidence SET withdrawn_at = ?, withdrawn_reason = ? "
                "WHERE evidence_id = ? AND project_id = ? AND withdrawn_at IS NULL",
                (now().isoformat(), reason, evidence_id, self.project_id),
            ).rowcount
        if not updated:
            raise ValueError(f"{evidence_id} n'existe pas dans ce projet ou est déjà retiré")
        self.export()

    # --- Gaps -------------------------------------------------------------------------

    def _gap_versions(self, where: str, params: tuple) -> list[Gap]:
        rows = self.db.conn.execute(
            "SELECT g.gap_id, g.project_id, g.created_at, v.version, v.record, v.reason, v.actor, v.at "
            f"FROM gaps g JOIN gap_versions v USING (gap_id) WHERE {where} ORDER BY {_GAP_ORDER}, v.version",
            params,
        ).fetchall()
        return [
            Gap.model_validate({
                **json.loads(r["record"]), "gap_id": r["gap_id"], "project_id": r["project_id"],
                "version": r["version"], "created_at": r["created_at"], "updated_at": r["at"],
                "actor": r["actor"], "reason": r["reason"],
            })
            for r in rows
        ]

    def load_gaps(self) -> list[Gap]:
        """Version courante de chaque gap du projet."""
        return self._gap_versions(
            "g.project_id = ? AND v.version = (SELECT MAX(version) FROM gap_versions WHERE gap_id = g.gap_id)",
            (self.project_id,),
        )

    def gap_history(self, gap_id: str) -> list[Gap]:
        return self._gap_versions("g.project_id = ? AND g.gap_id = ?", (self.project_id, gap_id))

    def save_gap_version(self, gap: Gap) -> None:
        """Enregistre une version de gap ; la version 1 crée le gap."""
        draft = GapDraft.model_validate(gap.model_dump(include=set(GapDraft.model_fields)))
        with self.db.transaction() as conn:
            if gap.version == 1:
                conn.execute(
                    "INSERT INTO gaps (gap_id, project_id, created_at) VALUES (?, ?, ?)",
                    (gap.gap_id, self.project_id, gap.created_at.isoformat()),
                )
            conn.execute(
                "INSERT INTO gap_versions (gap_id, version, status, record, reason, actor, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (gap.gap_id, gap.version, gap.status, draft.model_dump_json(), gap.reason, gap.actor,
                 gap.updated_at.isoformat()),
            )
            for role, ids in (("supporting", gap.supporting_evidence), ("contradicting", gap.contradicting_evidence)):
                conn.executemany(
                    "INSERT INTO gap_evidence (gap_id, version, evidence_id, role) VALUES (?, ?, ?, ?)",
                    [(gap.gap_id, gap.version, evidence_id, role) for evidence_id in ids],
                )
        self.export()

    def searches_by_gap(self) -> dict[str, list[SearchExecution]]:
        """Recherches contradictoires (Q3) du projet, regroupées par gap."""
        grouped: dict[str, list[SearchExecution]] = {}
        for search in self.load_search_log():
            if search.gap_id:
                grouped.setdefault(search.gap_id, []).append(search)
        return grouped

    def load_alignments(self) -> dict[str, Alignment]:
        """Dernière évaluation de chaque gap du projet au regard des valeurs."""
        rows = self.db.conn.execute(
            "SELECT a.record FROM alignments a JOIN gaps g USING (gap_id) WHERE g.project_id = ? ORDER BY a.rowid",
            (self.project_id,),
        )
        return {(a := Alignment.model_validate_json(r["record"])).gap_id: a for r in rows}

    def add_alignment(self, alignment: Alignment) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO alignments (gap_id, gap_version, record, values_hash, actor, at) VALUES (?, ?, ?, ?, ?, ?)",
                (alignment.gap_id, alignment.gap_version, alignment.model_dump_json(), alignment.values_hash,
                 alignment.actor, alignment.at.isoformat()),
            )
        self.export()

    # --- Gates -----------------------------------------------------------------------

    def load_gate_submissions(self, gate: Gate) -> list[GateSubmission]:
        rows = self.db.conn.execute(
            "SELECT record FROM gate_submissions WHERE project_id = ? AND gate = ? ORDER BY round",
            (self.project_id, gate),
        )
        return [GateSubmission.model_validate_json(r["record"]) for r in rows]

    def load_gate_decisions(self, gate: Gate) -> list[GateDecision]:
        rows = self.db.conn.execute(
            "SELECT record FROM gate_decisions WHERE project_id = ? AND gate = ? ORDER BY round",
            (self.project_id, gate),
        )
        return [GateDecision.model_validate_json(r["record"]) for r in rows]

    def record_gate_submission(self, submission: GateSubmission, change: StateChange) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO gate_submissions (project_id, gate, round, submitted_at, actor, record) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, submission.gate, submission.round, submission.submitted_at.isoformat(),
                 submission.actor, submission.model_dump_json()),
            )
            self._apply_state_change(conn, change)
        self.export()

    def record_gate_decision(self, decision: GateDecision, change: StateChange) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO gate_decisions (project_id, gate, round, decision, approver, at, comment, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.project_id, decision.gate, decision.round, decision.decision, decision.approver,
                 decision.at.isoformat(), decision.comment, decision.model_dump_json()),
            )
            self._apply_state_change(conn, change)
        self.export()

    # --- Exports lisibles ------------------------------------------------------

    def gate_export(self, gate: Gate) -> list[dict]:
        """gate-1.json : chaque tour de validation, avec son dossier et la décision humaine."""
        decisions = {d.round: d for d in self.load_gate_decisions(gate)}
        return [
            {
                "round": s.round,
                "submission": s.model_dump(mode="json"),
                "decision": decisions[s.round].model_dump(mode="json") if s.round in decisions else None,
            }
            for s in self.load_gate_submissions(gate)
        ]

    def gaps_export(self) -> list[dict]:
        """gaps.json : version courante de chaque gap, avec les publications et recherches associées (spec §4.3)."""
        evidence = {e.evidence_id: e for e in self.load_evidence()}
        searches = self.searches_by_gap()
        papers_of = lambda ids: sorted({evidence[i].paper_id for i in ids if i in evidence})  # noqa: E731
        return [
            {
                **gap.model_dump(mode="json"),
                "supporting_papers": papers_of(gap.supporting_evidence),
                "contradicting_papers": papers_of(gap.contradicting_evidence),
                "contradictory_searches": [s.search_id for s in searches.get(gap.gap_id, [])],
            }
            for gap in self.load_gaps()
        ]

    def alignment_export(self) -> list[dict]:
        """alignment.json : gaps actifs classés par score de priorité ; les non évalués à la fin."""
        alignments = self.load_alignments()
        rows = []
        for gap in self.load_gaps():
            if not gap.active:
                continue
            alignment = alignments.get(gap.gap_id)
            rows.append({
                "gap_id": gap.gap_id,
                "title": gap.title,
                "status": gap.status,
                "evidence_strength": gap.evidence_strength,
                "alignment_score": alignment.alignment_score if alignment else None,
                "priority_score": alignment.priority_score if alignment else None,
                "stale": alignment.gap_version != gap.version if alignment else None,
                "alignment": alignment.model_dump(mode="json", exclude={"gap_id"}) if alignment else None,
            })
        rows.sort(key=lambda r: -1 if r["priority_score"] is None else r["priority_score"], reverse=True)
        return [{"rank": rank, **row} for rank, row in enumerate(rows, start=1)]

    def evidence_matrix(self) -> list[dict]:
        """Matrice de preuves : pour chaque publication incluse, ses preuves actives."""
        evidence = [e for e in self.load_evidence() if e.active]
        matrix = []
        for paper in self.load_papers():
            if paper.status != PaperStatus.INCLUDED:
                continue
            fulltext = load_fulltext(self.db, paper.paper_id)
            matrix.append({
                "paper_id": paper.paper_id,
                "title": paper.title,
                "year": paper.published.year if paper.published else None,
                "fulltext_status": fulltext.status if fulltext else None,
                "evidence": [
                    e.model_dump(mode="json", include={"evidence_id", "evidence_type", "claim", "quote", "location", "page"})
                    for e in evidence if e.paper_id == paper.paper_id
                ],
            })
        return matrix

    def export(self) -> None:
        project = self.load_project()
        _atomic_write(
            self.project_file,
            yaml.safe_dump(project.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        )
        _atomic_write(self.papers_file, _PAPERS.dump_json(self.load_papers(), indent=2).decode() + "\n")
        _atomic_write(self.search_log_file, _SEARCH_LOG.dump_json(self.load_search_log(), indent=2).decode() + "\n")
        _atomic_write(
            self.dir / "evidence-matrix.json",
            json.dumps(self.evidence_matrix(), indent=2, ensure_ascii=False) + "\n",
        )
        for name, content in (("gaps.json", self.gaps_export()), ("alignment.json", self.alignment_export())):
            _atomic_write(self.dir / name, json.dumps(content, indent=2, ensure_ascii=False) + "\n")
        if gate_1 := self.gate_export(Gate.GATE_1):
            _atomic_write(self.dir / "gate-1.json", json.dumps(gate_1, indent=2, ensure_ascii=False) + "\n")


# --- Import des projets du sprint 1 (fichiers JSON/YAML) -------------------------


def _same_identity(a: Paper, b: Paper) -> bool:
    return (a.doi, a.arxiv_id, a.openalex_id) == (b.doi, b.arxiv_id, b.openalex_id)


def import_project_files(db: Database, projects_dir: Path, project_id: str) -> int:
    """Importe un projet stocké en fichiers en conservant ses identifiants PAPER-xxx et SEARCH-xxx.

    Les fichiers d'origine sont copiés dans `migration-backup/` avant d'être régénérés.
    Toute collision d'identifiant avec la base interrompt l'import sans rien écrire.
    Renvoie le nombre de publications importées.
    """
    repo = ProjectRepository(db, projects_dir, project_id)
    if repo.exists():
        raise ImportConflict(f"Le projet {project_id} est déjà dans la base")
    if not repo.project_file.is_file():
        raise ProjectNotFound(f"Aucun fichier {repo.project_file}")

    project = Project.model_validate(yaml.safe_load(repo.project_file.read_text(encoding="utf-8")))
    if project.project_id != project_id:
        raise ImportConflict(f"project.yaml déclare {project.project_id!r} au lieu de {project_id!r}")
    papers = _PAPERS.validate_json(repo.papers_file.read_bytes()) if repo.papers_file.exists() else []
    log = _SEARCH_LOG.validate_json(repo.search_log_file.read_bytes()) if repo.search_log_file.exists() else []

    existing = {p.paper_id: p for p in load_all_papers(db)}
    by_identifier = {
        (field, value): p.paper_id
        for p in existing.values()
        for field in ("doi", "arxiv_id", "openalex_id")
        if (value := getattr(p, field))
    }
    for paper in papers:
        if paper.paper_id in existing and not _same_identity(paper, existing[paper.paper_id]):
            raise ImportConflict(f"{paper.paper_id} existe déjà dans la base pour une autre publication")
        for field in ("doi", "arxiv_id", "openalex_id"):
            owner = by_identifier.get((field, getattr(paper, field)))
            if owner and owner != paper.paper_id:
                raise ImportConflict(f"{paper.paper_id} : {field} déjà attribué à {owner} dans la base")
    known_searches = {r["search_id"] for r in db.conn.execute("SELECT search_id FROM searches")}
    if clash := sorted(known_searches & {s.search_id for s in log}):
        raise ImportConflict(f"Identifiants de recherche déjà présents dans la base : {', '.join(clash)}")

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (project_id, topic, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, project.topic, project.state, project.created_at.isoformat(), project.updated_at.isoformat()),
        )
        for change in project.history:
            _insert_state_change(conn, project_id, change)
        for execution in log:
            _insert_search(conn, execution)
        for paper in papers:
            if paper.paper_id not in existing:
                _upsert_paper(conn, paper)
            conn.execute(
                "INSERT INTO project_papers (project_id, paper_id, status) VALUES (?, ?, ?)",
                (project_id, paper.paper_id, paper.status),
            )
            for prov in paper.provenance:
                _insert_provenance(conn, paper.paper_id, prov)

    backup = repo.dir / "migration-backup"
    backup.mkdir(exist_ok=True)
    for path in (repo.project_file, repo.papers_file, repo.search_log_file):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    repo.export()
    return len(papers)

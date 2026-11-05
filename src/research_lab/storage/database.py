"""Base SQLite partagée entre les projets (knowledge/research.db).

Le schéma évolue par migrations numérotées : chaque migration s'applique une seule fois,
dans une transaction, et `PRAGMA user_version` mémorise la dernière appliquée.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_MIGRATIONS: list[str] = [
    # 1 — projets, corpus partagé, recherches et provenance (sprint 2a)
    """
    CREATE TABLE projects (
        project_id TEXT PRIMARY KEY,
        topic      TEXT NOT NULL,
        state      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE state_changes (
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        from_state TEXT,
        to_state   TEXT NOT NULL,
        at         TEXT NOT NULL,
        actor      TEXT NOT NULL
    );

    CREATE TABLE papers (
        paper_id    TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        authors     TEXT NOT NULL,  -- liste JSON
        abstract    TEXT,
        published   TEXT,
        venue       TEXT,
        work_type   TEXT,
        doi         TEXT UNIQUE,
        arxiv_id    TEXT UNIQUE,
        openalex_id TEXT UNIQUE,
        url         TEXT,
        CHECK (doi IS NOT NULL OR arxiv_id IS NOT NULL OR openalex_id IS NOT NULL)
    );

    CREATE TABLE searches (
        search_id  TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        started_at TEXT NOT NULL,
        status     TEXT NOT NULL,
        record     TEXT NOT NULL  -- SearchExecution complète, JSON
    );

    CREATE TABLE project_papers (
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        paper_id   TEXT NOT NULL REFERENCES papers(paper_id),
        status     TEXT NOT NULL,
        PRIMARY KEY (project_id, paper_id)
    );

    CREATE TABLE provenance (
        paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
        search_id    TEXT NOT NULL REFERENCES searches(search_id),
        source       TEXT NOT NULL,
        source_id    TEXT NOT NULL,
        query        TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        UNIQUE (paper_id, search_id, source, source_id)
    );

    -- Les identifiants ne changent jamais ; publications, recherches et historique ne sont jamais supprimés.
    CREATE TRIGGER papers_id_immutable BEFORE UPDATE OF paper_id ON papers
    BEGIN SELECT RAISE(ABORT, 'paper_id est immuable'); END;
    CREATE TRIGGER papers_no_delete BEFORE DELETE ON papers
    BEGIN SELECT RAISE(ABORT, 'une publication ne peut pas être supprimée'); END;
    CREATE TRIGGER searches_append_only BEFORE UPDATE ON searches
    BEGIN SELECT RAISE(ABORT, 'le journal des recherches est en ajout seul'); END;
    CREATE TRIGGER searches_no_delete BEFORE DELETE ON searches
    BEGIN SELECT RAISE(ABORT, 'le journal des recherches est en ajout seul'); END;
    CREATE TRIGGER state_changes_append_only BEFORE UPDATE ON state_changes
    BEGIN SELECT RAISE(ABORT, 'l''historique des états est en ajout seul'); END;
    CREATE TRIGGER state_changes_no_delete BEFORE DELETE ON state_changes
    BEGIN SELECT RAISE(ABORT, 'l''historique des états est en ajout seul'); END;
    """,
    # 2 — tri des publications, texte intégral et preuves (sprint 2b)
    """
    CREATE TABLE screening_decisions (
        project_id TEXT NOT NULL,
        paper_id   TEXT NOT NULL,
        decision   TEXT NOT NULL CHECK (decision IN ('included', 'excluded')),
        reason     TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        actor      TEXT NOT NULL,
        at         TEXT NOT NULL,
        FOREIGN KEY (project_id, paper_id) REFERENCES project_papers (project_id, paper_id)
    );

    CREATE TABLE fulltexts (
        paper_id    TEXT PRIMARY KEY REFERENCES papers(paper_id),
        status      TEXT NOT NULL CHECK (status IN ('available', 'unavailable', 'failed')),
        pdf_url     TEXT,
        pdf_sha256  TEXT,
        text_sha256 TEXT,
        page_count  INTEGER,
        extractor   TEXT,
        fetched_at  TEXT NOT NULL,
        error       TEXT,
        CHECK (status != 'available' OR (pdf_sha256 IS NOT NULL AND text_sha256 IS NOT NULL AND page_count > 0))
    );

    CREATE TABLE evidence (
        evidence_id      TEXT PRIMARY KEY,
        project_id       TEXT NOT NULL,
        paper_id         TEXT NOT NULL,
        claim            TEXT NOT NULL CHECK (length(trim(claim)) > 0),
        quote            TEXT NOT NULL,
        location         TEXT NOT NULL CHECK (location IN ('full_text', 'abstract')),
        page             INTEGER CHECK (page IS NULL OR page >= 1),
        evidence_type    TEXT NOT NULL,
        text_sha256      TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        actor            TEXT NOT NULL,
        withdrawn_at     TEXT,
        withdrawn_reason TEXT,
        CHECK ((location = 'full_text') = (page IS NOT NULL)),
        CHECK ((withdrawn_at IS NULL) = (withdrawn_reason IS NULL)),
        FOREIGN KEY (project_id, paper_id) REFERENCES project_papers (project_id, paper_id)
    );

    CREATE TRIGGER screening_append_only BEFORE UPDATE ON screening_decisions
    BEGIN SELECT RAISE(ABORT, 'l''historique du tri est en ajout seul'); END;
    CREATE TRIGGER screening_no_delete BEFORE DELETE ON screening_decisions
    BEGIN SELECT RAISE(ABORT, 'l''historique du tri est en ajout seul'); END;

    -- Un texte disponible ne change plus : des preuves y renvoient par son empreinte.
    CREATE TRIGGER fulltexts_available_frozen BEFORE UPDATE ON fulltexts WHEN OLD.status = 'available'
    BEGIN SELECT RAISE(ABORT, 'un texte intégral disponible ne peut pas être remplacé'); END;
    CREATE TRIGGER fulltexts_no_delete BEFORE DELETE ON fulltexts
    BEGIN SELECT RAISE(ABORT, 'un texte intégral ne peut pas être supprimé'); END;

    -- Une preuve ne se modifie pas : elle peut seulement être retirée, une fois, avec une raison.
    CREATE TRIGGER evidence_immutable BEFORE UPDATE ON evidence
    WHEN OLD.withdrawn_at IS NOT NULL
      OR NEW.evidence_id IS NOT OLD.evidence_id OR NEW.project_id IS NOT OLD.project_id
      OR NEW.paper_id IS NOT OLD.paper_id OR NEW.claim IS NOT OLD.claim OR NEW.quote IS NOT OLD.quote
      OR NEW.location IS NOT OLD.location OR NEW.page IS NOT OLD.page
      OR NEW.evidence_type IS NOT OLD.evidence_type OR NEW.text_sha256 IS NOT OLD.text_sha256
      OR NEW.created_at IS NOT OLD.created_at OR NEW.actor IS NOT OLD.actor
    BEGIN SELECT RAISE(ABORT, 'une preuve est immuable ; seul un retrait est possible'); END;
    CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence
    BEGIN SELECT RAISE(ABORT, 'une preuve ne peut pas être supprimée ; la retirer'); END;
    """,
    # 3 — gaps versionnés, recherches contradictoires, alignement sur les valeurs (sprint 2c)
    """
    CREATE TABLE gaps (
        gap_id     TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        created_at TEXT NOT NULL
    );

    -- Chaque révision d'un gap est une nouvelle version ; la version courante est la plus élevée.
    CREATE TABLE gap_versions (
        gap_id  TEXT NOT NULL REFERENCES gaps(gap_id),
        version INTEGER NOT NULL CHECK (version >= 1),
        status  TEXT NOT NULL,
        record  TEXT NOT NULL,  -- GapDraft complet, JSON
        reason  TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        actor   TEXT NOT NULL,
        at      TEXT NOT NULL,
        PRIMARY KEY (gap_id, version)
    );

    -- Preuves citées par chaque version : la clé étrangère garantit qu'elles existent.
    CREATE TABLE gap_evidence (
        gap_id      TEXT NOT NULL,
        version     INTEGER NOT NULL,
        evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
        role        TEXT NOT NULL CHECK (role IN ('supporting', 'contradicting')),
        PRIMARY KEY (gap_id, version, evidence_id),
        FOREIGN KEY (gap_id, version) REFERENCES gap_versions (gap_id, version)
    );

    ALTER TABLE searches ADD COLUMN gap_id TEXT REFERENCES gaps(gap_id);

    CREATE TABLE alignments (
        gap_id      TEXT NOT NULL,
        gap_version INTEGER NOT NULL,
        record      TEXT NOT NULL,  -- Alignment complet, JSON
        values_hash TEXT NOT NULL,
        actor       TEXT NOT NULL,
        at          TEXT NOT NULL,
        FOREIGN KEY (gap_id, gap_version) REFERENCES gap_versions (gap_id, version)
    );

    CREATE TRIGGER gaps_append_only BEFORE UPDATE ON gaps
    BEGIN SELECT RAISE(ABORT, 'un gap ne se modifie pas : ajouter une version'); END;
    CREATE TRIGGER gaps_no_delete BEFORE DELETE ON gaps
    BEGIN SELECT RAISE(ABORT, 'un gap ne peut pas être supprimé ; le retirer (statut withdrawn)'); END;
    CREATE TRIGGER gap_versions_append_only BEFORE UPDATE ON gap_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des gaps est en ajout seul'); END;
    CREATE TRIGGER gap_versions_no_delete BEFORE DELETE ON gap_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des gaps est en ajout seul'); END;
    CREATE TRIGGER gap_evidence_append_only BEFORE UPDATE ON gap_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des gaps est en ajout seul'); END;
    CREATE TRIGGER gap_evidence_no_delete BEFORE DELETE ON gap_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des gaps est en ajout seul'); END;
    CREATE TRIGGER alignments_append_only BEFORE UPDATE ON alignments
    BEGIN SELECT RAISE(ABORT, 'l''historique des évaluations est en ajout seul'); END;
    CREATE TRIGGER alignments_no_delete BEFORE DELETE ON alignments
    BEGIN SELECT RAISE(ABORT, 'l''historique des évaluations est en ajout seul'); END;
    """,
    # 4 — validations humaines : soumissions et décisions de gate (sprint 2d)
    """
    -- Chaque passage devant une gate est un tour ; la soumission fige les empreintes des livrables.
    CREATE TABLE gate_submissions (
        project_id   TEXT NOT NULL REFERENCES projects(project_id),
        gate         TEXT NOT NULL CHECK (gate IN ('gate_1', 'gate_2')),
        round        INTEGER NOT NULL CHECK (round >= 1),
        submitted_at TEXT NOT NULL,
        actor        TEXT NOT NULL,
        record       TEXT NOT NULL,  -- GateSubmission complète, JSON
        PRIMARY KEY (project_id, gate, round)
    );

    -- Une seule décision par tour, jamais modifiée.
    CREATE TABLE gate_decisions (
        project_id TEXT NOT NULL,
        gate       TEXT NOT NULL,
        round      INTEGER NOT NULL,
        decision   TEXT NOT NULL CHECK (decision IN ('approve', 'revise')),
        approver   TEXT NOT NULL,
        at         TEXT NOT NULL,
        comment    TEXT NOT NULL CHECK (length(trim(comment)) > 0),
        record     TEXT NOT NULL,  -- GateDecision complète, JSON
        PRIMARY KEY (project_id, gate, round),
        FOREIGN KEY (project_id, gate, round) REFERENCES gate_submissions (project_id, gate, round)
    );

    CREATE TRIGGER gate_submissions_append_only BEFORE UPDATE ON gate_submissions
    BEGIN SELECT RAISE(ABORT, 'une soumission de gate est immuable'); END;
    CREATE TRIGGER gate_submissions_no_delete BEFORE DELETE ON gate_submissions
    BEGIN SELECT RAISE(ABORT, 'une soumission de gate est immuable'); END;
    CREATE TRIGGER gate_decisions_append_only BEFORE UPDATE ON gate_decisions
    BEGIN SELECT RAISE(ABORT, 'une décision de gate est immuable'); END;
    CREATE TRIGGER gate_decisions_no_delete BEFORE DELETE ON gate_decisions
    BEGIN SELECT RAISE(ABORT, 'une décision de gate est immuable'); END;
    """,
]

SCHEMA_VERSION = len(_MIGRATIONS)


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Mode autocommit : les transactions sont ouvertes explicitement par `transaction()`.
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} est au schéma v{version}, plus récent que cet outil (v{SCHEMA_VERSION})")
        for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

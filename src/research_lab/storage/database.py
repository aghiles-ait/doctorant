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
    # 5 — questions de recherche et hypothèses, versionnées comme les gaps (sprint 3a)
    """
    CREATE TABLE research_questions (
        question_id TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(project_id),
        created_at  TEXT NOT NULL
    );

    CREATE TABLE question_versions (
        question_id TEXT NOT NULL REFERENCES research_questions(question_id),
        version     INTEGER NOT NULL CHECK (version >= 1),
        status      TEXT NOT NULL,
        record      TEXT NOT NULL,  -- QuestionDraft complet, JSON
        reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        actor       TEXT NOT NULL,
        at          TEXT NOT NULL,
        PRIMARY KEY (question_id, version)
    );

    -- Gaps et preuves cités par chaque version : les clés étrangères garantissent qu'ils existent.
    CREATE TABLE question_gaps (
        question_id TEXT NOT NULL,
        version     INTEGER NOT NULL,
        gap_id      TEXT NOT NULL REFERENCES gaps(gap_id),
        PRIMARY KEY (question_id, version, gap_id),
        FOREIGN KEY (question_id, version) REFERENCES question_versions (question_id, version)
    );

    CREATE TABLE question_evidence (
        question_id   TEXT NOT NULL,
        version       INTEGER NOT NULL,
        hypothesis_id TEXT NOT NULL,
        evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id),
        PRIMARY KEY (question_id, version, hypothesis_id, evidence_id),
        FOREIGN KEY (question_id, version) REFERENCES question_versions (question_id, version)
    );

    CREATE TRIGGER research_questions_append_only BEFORE UPDATE ON research_questions
    BEGIN SELECT RAISE(ABORT, 'une question ne se modifie pas : ajouter une version'); END;
    CREATE TRIGGER research_questions_no_delete BEFORE DELETE ON research_questions
    BEGIN SELECT RAISE(ABORT, 'une question ne peut pas être supprimée ; la retirer (statut withdrawn)'); END;
    CREATE TRIGGER question_versions_append_only BEFORE UPDATE ON question_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    CREATE TRIGGER question_versions_no_delete BEFORE DELETE ON question_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    CREATE TRIGGER question_gaps_append_only BEFORE UPDATE ON question_gaps
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    CREATE TRIGGER question_gaps_no_delete BEFORE DELETE ON question_gaps
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    CREATE TRIGGER question_evidence_append_only BEFORE UPDATE ON question_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    CREATE TRIGGER question_evidence_no_delete BEFORE DELETE ON question_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des questions est en ajout seul'); END;
    """,
    # 6 — solutions versionnées et comparaisons par question (sprint 3b)
    """
    CREATE TABLE solutions (
        solution_id TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(project_id),
        question_id TEXT NOT NULL REFERENCES research_questions(question_id),
        created_at  TEXT NOT NULL
    );

    CREATE TABLE solution_versions (
        solution_id TEXT NOT NULL REFERENCES solutions(solution_id),
        version     INTEGER NOT NULL CHECK (version >= 1),
        status      TEXT NOT NULL,
        record      TEXT NOT NULL,  -- SolutionDraft complet, JSON
        reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        actor       TEXT NOT NULL,
        at          TEXT NOT NULL,
        PRIMARY KEY (solution_id, version)
    );

    CREATE TABLE solution_evidence (
        solution_id TEXT NOT NULL,
        version     INTEGER NOT NULL,
        evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
        PRIMARY KEY (solution_id, version, evidence_id),
        FOREIGN KEY (solution_id, version) REFERENCES solution_versions (solution_id, version)
    );

    -- Comparaison des solutions d'une question ; chaque nouvelle comparaison est une version.
    CREATE TABLE solution_comparisons (
        question_id TEXT NOT NULL REFERENCES research_questions(question_id),
        version     INTEGER NOT NULL CHECK (version >= 1),
        record      TEXT NOT NULL,  -- Comparison complète, JSON
        actor       TEXT NOT NULL,
        at          TEXT NOT NULL,
        PRIMARY KEY (question_id, version)
    );

    CREATE TRIGGER solutions_append_only BEFORE UPDATE ON solutions
    BEGIN SELECT RAISE(ABORT, 'une solution ne se modifie pas : ajouter une version'); END;
    CREATE TRIGGER solutions_no_delete BEFORE DELETE ON solutions
    BEGIN SELECT RAISE(ABORT, 'une solution ne peut pas être supprimée ; la retirer (statut withdrawn)'); END;
    CREATE TRIGGER solution_versions_append_only BEFORE UPDATE ON solution_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des solutions est en ajout seul'); END;
    CREATE TRIGGER solution_versions_no_delete BEFORE DELETE ON solution_versions
    BEGIN SELECT RAISE(ABORT, 'l''historique des solutions est en ajout seul'); END;
    CREATE TRIGGER solution_evidence_append_only BEFORE UPDATE ON solution_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des solutions est en ajout seul'); END;
    CREATE TRIGGER solution_evidence_no_delete BEFORE DELETE ON solution_evidence
    BEGIN SELECT RAISE(ABORT, 'l''historique des solutions est en ajout seul'); END;
    CREATE TRIGGER solution_comparisons_append_only BEFORE UPDATE ON solution_comparisons
    BEGIN SELECT RAISE(ABORT, 'l''historique des comparaisons est en ajout seul'); END;
    CREATE TRIGGER solution_comparisons_no_delete BEFORE DELETE ON solution_comparisons
    BEGIN SELECT RAISE(ABORT, 'l''historique des comparaisons est en ajout seul'); END;
    """,
    # 7 — revue critique indépendante, objections et réponses (sprint 3c)
    """
    -- Une revue par tour (passage à SCIENTIFIC_REVIEW), jamais modifiée.
    CREATE TABLE scientific_reviews (
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        round      INTEGER NOT NULL CHECK (round >= 1),
        verdict    TEXT NOT NULL CHECK (verdict IN ('ACCEPTABLE', 'MAJOR_REVISION', 'INSUFFICIENT_EVIDENCE')),
        reviewer   TEXT NOT NULL,
        at         TEXT NOT NULL,
        record     TEXT NOT NULL,  -- ScientificReview complète, JSON
        PRIMARY KEY (project_id, round)
    );

    CREATE TABLE objections (
        objection_id TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL,
        round        INTEGER NOT NULL,
        severity     TEXT NOT NULL CHECK (severity IN ('critical', 'major', 'minor')),
        FOREIGN KEY (project_id, round) REFERENCES scientific_reviews (project_id, round)
    );

    -- Réponses du doctorant ; la plus récente fait foi, les précédentes sont conservées.
    CREATE TABLE objection_responses (
        objection_id TEXT NOT NULL REFERENCES objections(objection_id),
        action       TEXT NOT NULL CHECK (action IN ('revised', 'rebutted', 'accepted_limitation')),
        response     TEXT NOT NULL CHECK (length(trim(response)) > 0),
        actor        TEXT NOT NULL,
        at           TEXT NOT NULL
    );

    CREATE TRIGGER scientific_reviews_append_only BEFORE UPDATE ON scientific_reviews
    BEGIN SELECT RAISE(ABORT, 'une revue est immuable'); END;
    CREATE TRIGGER scientific_reviews_no_delete BEFORE DELETE ON scientific_reviews
    BEGIN SELECT RAISE(ABORT, 'une revue est immuable'); END;
    CREATE TRIGGER objections_append_only BEFORE UPDATE ON objections
    BEGIN SELECT RAISE(ABORT, 'une objection est immuable'); END;
    CREATE TRIGGER objections_no_delete BEFORE DELETE ON objections
    BEGIN SELECT RAISE(ABORT, 'une objection est immuable'); END;
    CREATE TRIGGER objection_responses_append_only BEFORE UPDATE ON objection_responses
    BEGIN SELECT RAISE(ABORT, 'l''historique des réponses est en ajout seul'); END;
    CREATE TRIGGER objection_responses_no_delete BEFORE DELETE ON objection_responses
    BEGIN SELECT RAISE(ABORT, 'l''historique des réponses est en ajout seul'); END;
    """,
    # 8 — transitions forcées (`project transition --force`), signalées dans l'historique
    """
    ALTER TABLE state_changes ADD COLUMN forced INTEGER NOT NULL DEFAULT 0;
    """,
    # 9 — pages du texte intégral affichées par `fulltext show`, par projet (couverture de lecture)
    """
    CREATE TABLE page_reads (
        project_id     TEXT NOT NULL REFERENCES projects(project_id),
        paper_id       TEXT NOT NULL REFERENCES papers(paper_id),
        page           INTEGER NOT NULL CHECK (page >= 1),
        text_sha256    TEXT NOT NULL,  -- texte affiché : une nouvelle extraction repart de zéro
        first_shown_at TEXT NOT NULL,
        PRIMARY KEY (project_id, paper_id, page, text_sha256)
    );
    """,
    # 10 — évaluation humaine des gaps et des hypothèses (sprint 4)
    """
    CREATE TABLE rating_sessions (
        session_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        rater      TEXT NOT NULL,
        at         TEXT NOT NULL,
        record     TEXT NOT NULL  -- RatingSession complète, JSON
    );
    CREATE TRIGGER rating_sessions_append_only BEFORE UPDATE ON rating_sessions
    BEGIN SELECT RAISE(ABORT, 'une évaluation humaine est immuable'); END;
    CREATE TRIGGER rating_sessions_no_delete BEFORE DELETE ON rating_sessions
    BEGIN SELECT RAISE(ABORT, 'une évaluation humaine est immuable'); END;
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

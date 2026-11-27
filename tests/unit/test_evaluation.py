"""Sprint 4 : évaluation de la qualité scientifique (indicateurs Q1 à Q5, notation humaine)."""

import pytest
from test_critique import MAJOR, _review, reviewing  # noqa: F401 — fixtures partagées
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401
from test_gate import human, ready, submitted  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401
from test_solutions import _comparison, _solution, _two_solutions, design  # noqa: F401

from research_lab.critique import submit_review
from research_lab.evaluation import (
    EvaluationError,
    current_ratings,
    evaluation_summary,
    quality_report,
    rating_targets,
    record_ratings,
)
from research_lab.schemas.evaluation import Rating
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectRepository
from research_lab.workflow import approvals
from research_lab.workflow.state import ResearchState as S

GAP_SCORES = {"reality": 4, "evidence": 3, "importance": 5}
HYPOTHESIS_SCORES = {"falsifiability": 4, "relevance": 4, "testability": 2}


def _indicators(report) -> dict[str, tuple[str, bool | None]]:
    return {i.name: (i.value, i.ok) for i in report.indicators}


def test_report_measures_q1_to_q5_and_review(reviewing, settings):
    submit_review(reviewing, settings, _review(verdict="MAJOR_REVISION", objections=[MAJOR]), "scientific-reviewer")
    indicators = _indicators(quality_report(reviewing, settings))
    assert indicators["publications incluses avec identifiant externe"][1] is True
    assert indicators["gaps avec une recherche contradictoire ayant ramené des résultats"] == ("1/1 (100 %)", True)
    assert indicators["hypothèses testées par au moins une solution"][1] is True
    assert indicators["dernier verdict"] == ("MAJOR_REVISION", False)
    assert indicators["objections (critiques / majeures / mineures)"][0] == "0 / 1 / 0"
    assert indicators["transitions forcées"] == ("0", True)


def test_untested_hypothesis_and_forced_transition_are_flagged(design, settings):
    design.transition(S.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy, force=True)
    indicators = _indicators(quality_report(design, settings))
    assert indicators["hypothèses testées par au moins une solution"] == ("0/2 (0 %)", False)
    assert indicators["transitions forcées"] == ("1", False)


def test_rating_targets_are_retained_gaps_and_hypotheses(design):
    assert [(t.target, t.kind) for t in rating_targets(design)] == [
        ("GAP-001", "gap"), ("RQ-001/H1", "hypothesis"), ("RQ-001/H2", "hypothesis"),
    ]  # GAP-002, écarté à la Gate 1, n'est pas noté


def _ratings() -> list[Rating]:
    return [
        Rating(target="GAP-001", target_version=2, scores=GAP_SCORES, comment="Manque réel"),
        Rating(target="RQ-001/H1", target_version=1, scores=HYPOTHESIS_SCORES),
    ]


def test_agent_cannot_rate(design, settings, monkeypatch):
    monkeypatch.setattr(approvals, "human_check_failure", lambda: "commande lancée depuis Claude Code")
    with pytest.raises(EvaluationError, match="Claude Code"):
        record_ratings(design, settings, _ratings(), "agent")
    assert design.load_rating_sessions() == []


def test_human_ratings_are_recorded_and_exported(design, settings, human):
    session = record_ratings(design, settings, _ratings(), "alice", "Premier passage")
    assert (session.session_id, session.state) == ("EVAL-001", S.SOLUTION_DESIGN)
    assert (design.dir / "human-evaluation.json").exists()
    later = Rating(target="GAP-001", target_version=2, scores=GAP_SCORES | {"reality": 2})
    record_ratings(design, settings, [later], "alice")
    current = current_ratings(design.load_rating_sessions())
    assert current["GAP-001"].scores["reality"] == 2 and "RQ-001/H1" in current


@pytest.mark.parametrize(("rating", "message"), [
    (Rating(target="GAP-002", target_version=1, scores=GAP_SCORES), "ni gap retenu"),
    (Rating(target="GAP-001", target_version=1, scores=GAP_SCORES), "version courante 2"),
    (Rating(target="GAP-001", target_version=2, scores={"reality": 4}), "critères attendus"),
    (Rating(target="RQ-001/H1", target_version=1, scores=HYPOTHESIS_SCORES | {"testability": 9}), "hors de l'échelle"),
])
def test_invalid_ratings_are_refused(design, settings, human, rating, message):
    with pytest.raises(EvaluationError, match=message):
        record_ratings(design, settings, [rating], "alice")


def test_summary_counts_distinct_rated_topics(design, settings, human):
    assert not evaluation_summary(design.db, settings).target_met
    record_ratings(design, settings, _ratings(), "alice")
    summary = evaluation_summary(Database(design.db.path), settings)
    assert list(summary.rated_projects) == [design.project_id]
    assert (summary.min_rated_topics, summary.target_met, summary.rating_count) == (3, False, 2)
    assert summary.averages["reality"] == 4.0


def test_ratings_are_immutable(design, settings, human):
    record_ratings(design, settings, _ratings(), "alice")
    with pytest.raises(Exception, match="immuable"):
        design.db.conn.execute("DELETE FROM rating_sessions")
    assert len(ProjectRepository(design.db, design.dir.parent, design.project_id).load_rating_sessions()) == 1

"""Sprint 4 : reprise d'un projet interrompu (spec §6, critère « reprise sans perte des validations »).

Chaque scénario rouvre la base comme le ferait une nouvelle session : rien ne vient de la mémoire du processus.
"""

import pytest
from test_critique import MAJOR, _review, reviewing  # noqa: F401 — fixtures partagées
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401
from test_gate import human, ready, submitted  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401
from test_solutions import _comparison, _solution, _two_solutions, design  # noqa: F401

from research_lab.critique import submit_review
from research_lab.resume import _STEPS, resume_report
from research_lab.schemas.gate import GateDecisionType
from research_lab.storage import repositories
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectRepository
from research_lab.workflow import approvals
from research_lab.workflow.approvals import decide_gate_1
from research_lab.workflow.state import ResearchState as S


def reopen(repo: ProjectRepository) -> ProjectRepository:
    """Nouvelle session : nouvelle connexion à la base, nouveau dépôt."""
    return ProjectRepository(Database(repo.db.path), repo.dir.parent, repo.project_id, repo.papers_dir)


def test_every_state_has_a_resume_step():
    assert set(_STEPS) == set(S)


def test_resume_reports_state_and_blockers_after_restart(analysis, settings):
    report = resume_report(reopen(analysis), settings)
    assert (report.state, report.waiting_for_human, report.stale_exports) == (S.GAP_ANALYSIS, False, [])
    assert "gap-analysis" in report.step
    assert any("aucun gap" in b for b in report.next_steps["`gate submit` (Gate 1)"])


def test_submitted_gate_survives_restart_and_can_be_decided(submitted, settings, human):
    resumed = reopen(submitted)
    report = resume_report(resumed, settings)
    assert (report.state, report.waiting_for_human, report.next_steps) == (S.AWAITING_GATE_1, True, {})
    decide_gate_1(resumed, GateDecisionType.APPROVE, "GAP-001 retenu", "alice", ["GAP-001"])
    assert reopen(submitted).approved_gaps() == {"GAP-001": 2}


def test_resume_after_gate_revision_shows_instructions_and_keeps_work(submitted, settings, human):
    decide_gate_1(submitted, GateDecisionType.REVISE, "Chercher la vérification formelle", "alice")
    resumed = reopen(submitted)
    report = resume_report(resumed, settings)
    assert report.state == S.LITERATURE_SEARCH
    assert report.human_instructions == "Gate 1 revise : Chercher la vérification formelle"
    assert [g.gap_id for g in resumed.load_gaps()] == ["GAP-001", "GAP-002"]
    assert len(resumed.load_evidence()) == 3


def test_resume_during_review_waits_for_reviewer_then_follows_verdict(reviewing, settings):
    report = resume_report(reopen(reviewing), settings)
    assert list(report.next_steps) == ["revue (agent scientific-reviewer)"]
    submit_review(reviewing, settings, _review(verdict="MAJOR_REVISION", objections=[MAJOR]), "scientific-reviewer")
    report = resume_report(reopen(reviewing), settings)
    assert report.next_steps[str(S.SOLUTION_DESIGN)] == []
    assert "MAJOR_REVISION" in report.next_steps[str(S.PROPOSAL_DRAFT)][0]


def test_crash_after_commit_leaves_stale_exports_that_resume_repairs(design, settings, monkeypatch):
    """Interruption entre l'écriture dans la base et la régénération des exports."""
    _two_solutions(design)
    with monkeypatch.context() as m:
        m.setattr(ProjectRepository, "export", lambda self: (_ for _ in ()).throw(KeyboardInterrupt))
        with pytest.raises(KeyboardInterrupt):
            design.transition(S.PROBLEM_FORMULATION, actor="agent", policy=settings.policy, force=True)
    resumed = reopen(design)
    assert resumed.load_project().state == S.PROBLEM_FORMULATION  # la base fait foi
    assert resume_report(resumed, settings).stale_exports == ["project.yaml"]
    resumed.export()
    assert resume_report(resumed, settings).stale_exports == []


def test_deleted_or_edited_exports_are_detected(design, settings):
    (design.dir / "gaps.json").unlink()
    (design.dir / "research-questions.json").write_text("[]\n")
    assert resume_report(design, settings).stale_exports == ["gaps.json", "research-questions.json"]


def test_interrupted_write_is_rolled_back(design, settings, monkeypatch):
    """Interruption au milieu d'une transaction : ni changement d'état, ni historique partiel."""
    before = design.load_project()
    monkeypatch.setattr(
        repositories, "_insert_state_change", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        design.transition(S.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy, force=True)
    assert reopen(design).load_project() == before


def test_interrupted_gate_decision_is_rolled_back(submitted, monkeypatch, human):
    monkeypatch.setattr(
        repositories, "_insert_state_change", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        decide_gate_1(submitted, GateDecisionType.APPROVE, "GAP-001 retenu", "alice", ["GAP-001"])
    resumed = reopen(submitted)
    assert resumed.load_project().state == S.AWAITING_GATE_1
    assert resumed.load_gate_decisions(approvals.Gate.GATE_1) == []


def test_forced_transition_is_reported(design, settings):
    design.transition(S.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy, force=True)
    assert resume_report(reopen(design), settings).last_change_forced

"""Étape 3d : Research Proposal contrôlé et bibliographie générée depuis la base."""

import pytest
from test_critique import MAJOR, _review, reviewing  # noqa: F401 — fixtures partagées
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401
from test_gate import human, ready, submitted  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401
from test_solutions import _comparison, _solution, _two_solutions, design  # noqa: F401

from research_lab.bibliography import bibtex_entry
from research_lab.critique import respond, submit_review
from research_lab.proposal import ProposalError, check_proposal_file, write_references
from research_lab.schemas.critique import ResponseDraft
from research_lab.validation.proposal import REQUIRED_SECTIONS
from research_lab.workflow.state import ResearchState


@pytest.fixture
def drafting(reviewing, settings):
    """Revue ACCEPTABLE (OBJ-001 majeure sur SOL-002, limite admise) ; état PROPOSAL_DRAFT."""
    submit_review(reviewing, settings, _review(), "scientific-reviewer")
    respond(reviewing, "OBJ-001", ResponseDraft(action="accepted_limitation", response="Reporté."), "agent")
    reviewing.transition(ResearchState.PROPOSAL_DRAFT, actor="agent", policy=settings.policy)
    return reviewing


def _write(repo, *, skip_sections=(), extra="", drop=()):
    """Proposal complet ; `drop` retire des identifiants du texte, `extra` en ajoute."""
    searches = " ".join(s.search_id for s in repo.load_search_log())
    content = {
        "Résumé": "Responsabilité vérifiable [PAPER-001, EV-001].",
        "Méthode": f"Recherches {searches}.",
        "État de l'art": "Position des auteurs [PAPER-002, EV-002].",
        "Gaps retenus": "GAP-001.",
        "Questions de recherche et hypothèses": "RQ-001 : RQ-001/H1 et RQ-001/H2.",
        "Solutions": "SOL-001 et SOL-002.",
        "Protocole d'évaluation": "Étude de cas.",
        "Revue critique": "OBJ-001 admise comme limite.",
        "Limites": "Corpus restreint.",
        "Références": "references.bib",
    }
    text = "# Research Proposal\n\n" + "".join(
        f"## {title}\n\n{body}\n\n" for title, body in content.items() if title not in skip_sections
    ) + extra
    for identifier in drop:
        text = text.replace(identifier, "")
    (repo.dir / "research-proposal.md").write_text(text)


def test_bibtex_entry_escapes_and_keys_by_paper_id(drafting):
    paper = drafting.get_paper("PAPER-001").model_copy(
        update={"title": "Trust & {verifiable}  AI_100%", "authors": ["Ada Lovelace", "Alan Turing"]}
    )
    entry = bibtex_entry(paper)
    assert entry.startswith("@") and "{PAPER-001,\n" in entry
    assert r"title = {{Trust \& \{verifiable\} AI\_100\%}}" in entry
    assert "author = {Ada Lovelace and Alan Turing}" in entry


def test_references_require_proposal_text(drafting):
    with pytest.raises(ProposalError, match="absent ou vide"):
        write_references(drafting)


def test_references_require_proposal_state(design):
    with pytest.raises(ProposalError, match="PROPOSAL_DRAFT"):
        write_references(design)


def test_complete_proposal_passes(drafting):
    _write(drafting)
    assert "references.bib" in check_proposal_file(drafting).errors[-1]
    assert write_references(drafting) == 2  # PAPER-001 cité, PAPER-002 cité par EV-002
    bib = (drafting.dir / "references.bib").read_text()
    assert "{PAPER-001," in bib and "{PAPER-002," in bib
    check = check_proposal_file(drafting)
    assert (check.status, check.errors, check.cited_papers) == ("OK", [], ["PAPER-001", "PAPER-002"])
    write_references(drafting)
    assert (drafting.dir / "references.bib").read_text() == bib  # déterministe


def test_missing_sections_are_reported(drafting):
    _write(drafting, skip_sections=("Limites", "Revue critique"))
    errors = check_proposal_file(drafting).errors
    assert "sections manquantes : Revue critique, Limites" in errors
    assert len(REQUIRED_SECTIONS) == 10


def test_every_validated_element_must_be_addressed(drafting):
    _write(drafting, drop=("RQ-001/H2", "OBJ-001", "SOL-002"))
    write_references(drafting)
    assert "non traités dans le Proposal : RQ-001/H2, SOL-002, OBJ-001" in check_proposal_file(drafting).errors


def test_unknown_or_unretained_identifiers_are_refused(drafting):
    _write(drafting, extra="Voir aussi GAP-002, SOL-404 et [PAPER-999].\n")
    write_references(drafting)
    errors = check_proposal_file(drafting).errors
    assert "PAPER-999 cité mais absent du corpus du projet" in errors
    assert "identifiants inconnus ou gaps non retenus : GAP-002, SOL-404" in errors


def test_searches_must_be_cited(drafting):
    _, *others = [s.search_id for s in drafting.load_search_log()]
    assert others
    _write(drafting, drop=tuple(s.search_id for s in drafting.load_search_log()))
    write_references(drafting)
    assert any("Méthode (Q5)" in e for e in check_proposal_file(drafting).errors)
    _write(drafting, drop=tuple(others))
    assert check_proposal_file(drafting).warnings == [f"recherches non citées : {', '.join(others)}"]


def test_bibliography_must_follow_the_text(drafting):
    _write(drafting)
    write_references(drafting)
    _write(drafting, drop=("[PAPER-002, EV-002]",))
    assert "pas à jour" in check_proposal_file(drafting).errors[-1]
    write_references(drafting)
    assert check_proposal_file(drafting).status == "OK"

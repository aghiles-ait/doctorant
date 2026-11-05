"""Scénario complet via la CLI, avec les APIs simulées à partir de réponses réelles enregistrées."""

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from research_lab.cli import app

ARXIV_URL = "https://export.arxiv.org/api/query"
OPENALEX_URL = "https://api.openalex.org/works"
PROJECT = "decentralized-ai-governance"

runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture
def project_ready(lab_root):
    assert invoke("project", "init", PROJECT, "--topic", "Decentralized AI governance").exit_code == 0
    assert invoke("project", "transition", PROJECT, "SCOPING").exit_code == 0
    (lab_root / "research" / "projects" / PROJECT / "scope.md").write_text("# Scope\nGouvernance décentralisée.\n")
    assert invoke("project", "transition", PROJECT, "LITERATURE_SEARCH").exit_code == 0
    return lab_root / "research" / "projects" / PROJECT


@pytest.fixture
def apis(fixture_text):
    with respx.mock:
        arxiv = respx.get(ARXIV_URL).mock(return_value=httpx.Response(200, text=fixture_text("arxiv_search.xml")))
        openalex = respx.get(OPENALEX_URL).mock(
            return_value=httpx.Response(200, text=fixture_text("openalex_search.json"))
        )
        yield arxiv, openalex


def _search(*extra: str):
    return invoke("watch", "search", PROJECT, "--query", "decentralized autonomous machines",
                  "--from", "2024-01-01", "--to", "2026-10-26", "--max-results", "3", "--json", *extra)


def test_search_builds_deduplicated_traceable_corpus(project_ready, apis):
    result = _search()
    assert result.exit_code == 0, result.output
    execution = json.loads(result.output)
    assert execution["status"] == "completed"
    assert [r["hits"] for r in execution["results"]] == [2, 3]
    # 2 arXiv + 3 OpenAlex, dont un article commun : 4 publications.
    assert execution["new_paper_ids"] == ["PAPER-001", "PAPER-002", "PAPER-003", "PAPER-004"]
    assert execution["config_hash"].startswith("sha256:")
    assert "submittedDate:[202401010000 TO 202610262359]" in execution["results"][0]["provider_query"]

    papers = json.loads((project_ready / "papers.json").read_text())
    merged = next(p for p in papers if p["arxiv_id"] == "2504.15676")
    assert {p["source"] for p in merged["provenance"]} == {"arxiv", "openalex"}
    assert merged["openalex_id"] == "W4414632071"
    for paper in papers:
        assert paper["doi"] or paper["arxiv_id"] or paper["openalex_id"]
        assert all(p["search_id"] == "SEARCH-001" and p["query"] for p in paper["provenance"])

    check = invoke("corpus", "check", PROJECT, "--json")
    assert json.loads(check.output)["errors"] == []


def test_rerun_is_idempotent(project_ready, apis):
    _search()
    papers_before = json.loads((project_ready / "papers.json").read_text())
    execution = json.loads(_search().output)
    assert execution["search_id"] == "SEARCH-002"
    assert execution["new_paper_ids"] == []
    assert sorted(execution["matched_paper_ids"]) == ["PAPER-001", "PAPER-002", "PAPER-003", "PAPER-004"]
    papers_after = json.loads((project_ready / "papers.json").read_text())
    assert [p["paper_id"] for p in papers_after] == [p["paper_id"] for p in papers_before]
    log = json.loads(invoke("search-log", PROJECT, "--json").output)
    assert [s["search_id"] for s in log] == ["SEARCH-001", "SEARCH-002"]


def test_failing_source_leaves_corpus_unchanged_but_is_logged(project_ready, apis):
    _, openalex = apis
    openalex.mock(return_value=httpx.Response(503))
    result = _search()
    assert result.exit_code == 2
    assert json.loads((project_ready / "papers.json").read_text()) == []
    [entry] = json.loads((project_ready / "search-log.json").read_text())
    assert entry["status"] == "failed"
    assert entry["results"][1]["status"] == "error"
    assert "503" in entry["results"][1]["error"]


def test_partial_search_is_refused_by_default_policy(project_ready, apis):
    result = _search("--allow-partial")
    assert result.exit_code == 1
    assert "interdit" in result.output


def test_search_requires_literature_search_state(lab_root, apis):
    invoke("project", "init", PROJECT, "--topic", "x")
    result = _search()
    assert result.exit_code == 1
    assert "LITERATURE_SEARCH" in result.output


def test_sprint1_project_must_be_imported_then_keeps_working(project_ready, apis, lab_root):
    _search()
    papers_before = json.loads((project_ready / "papers.json").read_text())
    # Simule un projet du sprint 1 : fichiers présents, base absente.
    (lab_root / "knowledge" / "research.db").unlink()

    blocked = invoke("corpus", "list", PROJECT)
    assert blocked.exit_code == 1
    assert "db import-files" in blocked.output

    imported = invoke("db", "import-files")
    assert imported.exit_code == 0, imported.output
    assert "4 publications importées" in imported.output
    assert json.loads((project_ready / "papers.json").read_text()) == papers_before

    execution = json.loads(_search().output)
    assert execution["search_id"] == "SEARCH-002"
    assert execution["new_paper_ids"] == []
    info = json.loads(invoke("db", "info", "--json").output)
    assert info["papers"] == 4 and info["projects"][0]["papers"] == 4


def test_literature_review_flow(project_ready, apis, lab_root):
    """Étape 2b de bout en bout : tri, texte intégral, preuve vérifiée, état de l'art, passage aux gaps."""
    from conftest import make_pdf

    _search()
    # Corpus de 4 publications, sous le minimum de la politique (20) : passage refusé.
    refused = invoke("project", "transition", PROJECT, "LITERATURE_REVIEW")
    assert refused.exit_code == 1 and "NEEDS_MORE_RESEARCH" in refused.output
    policy_file = lab_root / "config" / "research-policy.yaml"
    policy_file.write_text(policy_file.read_text().replace("min_corpus_size: 20", "min_corpus_size: 3"))
    assert invoke("project", "transition", PROJECT, "LITERATURE_REVIEW").exit_code == 0

    papers = {p["arxiv_id"] or p["openalex_id"]: p["paper_id"] for p in json.loads(invoke("corpus", "list", PROJECT, "--json").output)}
    dam = papers["2504.15676"]
    for paper_id in papers.values():
        flag = "--include" if paper_id == dam else "--exclude"
        result = invoke("corpus", "decide", PROJECT, paper_id, flag, "--reason", "critères de scope.md")
        assert result.exit_code == 0, result.output
    assert "0 publications restent à trier" in result.output

    page = "Decentralized Autonomous Machines extend autonomy into the physical world, enabling trustless systems."
    respx.get("https://export.arxiv.org/pdf/2504.15676").mock(
        return_value=httpx.Response(200, content=make_pdf(["Title page", page]))
    )
    fetched = invoke("fulltext", "fetch", PROJECT)
    assert fetched.exit_code == 0 and "1 available" in fetched.output
    assert "page 2/2" in invoke("fulltext", "show", PROJECT, dam, "--page", "2").output

    invented = invoke("evidence", "add", PROJECT, "--paper", dam, "--claim", "x", "--type", "position",
                      "--quote", "DAMs are provably secure against all attacks", "--page", "2")
    assert invented.exit_code == 1 and "Preuve refusée" in invented.output
    added = invoke("evidence", "add", PROJECT, "--paper", dam, "--claim", "Les DAM étendent l'autonomie au monde physique",
                   "--type", "position", "--quote", "extend autonomy into the physical world", "--page", "2")
    assert added.exit_code == 0 and "EV-001" in added.output

    review = project_ready / "literature-review.md"
    review.write_text(f"# État de l'art\nLes DAM étendent l'autonomie [{dam}, EV-001]. Voir aussi [EV-404].\n")
    assert invoke("review", "check", PROJECT).exit_code == 2
    assert invoke("project", "transition", PROJECT, "GAP_ANALYSIS").exit_code == 1
    review.write_text(f"# État de l'art\nLes DAM étendent l'autonomie [{dam}, EV-001].\n")
    assert invoke("review", "check", PROJECT).exit_code == 0
    assert invoke("project", "transition", PROJECT, "GAP_ANALYSIS").exit_code == 0

    matrix = json.loads((project_ready / "evidence-matrix.json").read_text())
    assert matrix == [{
        "paper_id": dam, "title": matrix[0]["title"], "year": 2025, "fulltext_status": "available",
        "evidence": [{"evidence_id": "EV-001", "evidence_type": "position", "claim": "Les DAM étendent l'autonomie au monde physique",
                      "quote": "extend autonomy into the physical world", "location": "full_text", "page": 2}],
    }]


def test_gap_analysis_flow(project_ready, apis, lab_root, tmp_path):
    """Étape 2c : gap, recherche contradictoire, évaluation au regard des valeurs, contrôle."""
    test_literature_review_flow(project_ready, apis, lab_root)  # projet à l'état GAP_ANALYSIS, preuve EV-001

    draft = tmp_path / "gap.json"
    gap = {"title": "Sécurité des DAM non évaluée", "description": "d", "category": "missing_evaluation",
           "rationale": "EV-001 affirme sans évaluer.", "supporting_evidence": ["EV-001"], "evidence_strength": "high"}
    draft.write_text(json.dumps(gap))
    refused = invoke("gap", "add", PROJECT, "--file", str(draft))
    assert refused.exit_code == 1 and "ne permettent que low" in refused.output
    draft.write_text(json.dumps(gap | {"evidence_strength": "low", "unknown": 1}))
    assert "Contenu invalide" in invoke("gap", "add", PROJECT, "--file", str(draft)).output
    draft.write_text(json.dumps(gap | {"evidence_strength": "low"}))
    added = invoke("gap", "add", PROJECT, "--file", str(draft))
    assert added.exit_code == 0 and "GAP-001 enregistré (candidate" in added.output

    assert invoke("watch", "search", PROJECT, "-q", "x").exit_code == 1
    search = _search("--for-gap", "GAP-001")
    assert search.exit_code == 0, search.output
    assert json.loads(search.output)["gap_id"] == "GAP-001"
    assert "[GAP-001]" in invoke("search-log", PROJECT).output

    assert invoke("gap", "check", PROJECT).exit_code == 2  # pas encore évalué
    values = ["privacy", "freedom", "sovereignty", "governance", "decentralization", "verifiability"]
    alignment = tmp_path / "alignment.json"
    alignment.write_text(json.dumps({"scores": {v: {"score": 3, "justification": "j"} for v in values}, "tradeoffs": []}))
    aligned = invoke("alignment", "set", PROJECT, "GAP-001", "--file", str(alignment))
    assert aligned.exit_code == 0 and "alignement 0.60, priorité 0.30" in aligned.output
    checked = invoke("gap", "check", PROJECT)
    assert checked.exit_code == 0 and "NEEDS_MORE_RESEARCH" in checked.output
    assert "1. GAP-001" in invoke("alignment", "show", PROJECT).output

    exported = json.loads((project_ready / "gaps.json").read_text())
    assert exported[0]["contradictory_searches"] == ["SEARCH-002"]
    assert json.loads((project_ready / "alignment.json").read_text())[0]["priority_score"] == 0.3
    assert len(json.loads(invoke("gap", "show", PROJECT, "GAP-001", "--history").output)) == 1


def test_gate_1_flow(project_ready, apis, lab_root, tmp_path, monkeypatch):
    """Étape 2d : l'agent soumet, la décision n'est acceptée que d'un humain dans un terminal."""
    test_gap_analysis_flow(project_ready, apis, lab_root, tmp_path)  # GAP-001 candidate, évalué

    assert "gate submit" in invoke("project", "transition", PROJECT, "AWAITING_GATE_1").output
    submitted = invoke("gate", "submit", PROJECT)
    assert submitted.exit_code == 0 and "tour 1, gap check NEEDS_MORE_RESEARCH" in submitted.output
    status = invoke("gate", "status", PROJECT)
    assert "1. GAP-001" in status.output and "Livrables : inchangés" in status.output

    refused = invoke("gate", "approve", PROJECT, "--gap", "GAP-001", "--comment", "ok")
    assert refused.exit_code == 1 and "Décision refusée" in refused.output  # pas de terminal (ni CLAUDECODE)

    from research_lab import cli
    from research_lab.workflow import approvals
    for module in (cli, approvals):
        monkeypatch.setattr(module, "human_check_failure", lambda: None)
    wrong = runner.invoke(app, ["gate", "approve", PROJECT, "--gap", "GAP-001", "--comment", "ok"], input="autre\n")
    assert wrong.exit_code == 1 and "rien n'a été enregistré" in wrong.output
    approved = runner.invoke(app, ["gate", "approve", PROJECT, "--gap", "GAP-001", "--comment", "Gap retenu"],
                             input=f"{PROJECT}\n")
    assert approved.exit_code == 0, approved.output
    assert "candidate : insuffisamment établi" in approved.output
    assert json.loads(invoke("project", "status", PROJECT, "--json").output)["state"] == "PROBLEM_FORMULATION"

    [round_1] = json.loads((project_ready / "gate-1.json").read_text())
    assert round_1["decision"]["selected_gaps"] == {"GAP-001": 1}
    assert invoke("gate", "verify", PROJECT).exit_code == 0
    (project_ready / "scope.md").write_text("modifié après la décision")
    verify = invoke("gate", "verify", PROJECT)
    assert verify.exit_code == 2 and "scope.md" in verify.output


def test_corpus_list_and_show(project_ready, apis):
    _search()
    listing = invoke("corpus", "list", PROJECT, "--source", "arxiv")
    assert "2 publications" in listing.output
    shown = json.loads(invoke("corpus", "show", PROJECT, "PAPER-001").output)
    assert shown["paper_id"] == "PAPER-001"
    assert invoke("corpus", "show", PROJECT, "PAPER-999").exit_code == 1

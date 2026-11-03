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


def test_corpus_list_and_show(project_ready, apis):
    _search()
    listing = invoke("corpus", "list", PROJECT, "--source", "arxiv")
    assert "2 publications" in listing.output
    shown = json.loads(invoke("corpus", "show", PROJECT, "PAPER-001").output)
    assert shown["paper_id"] == "PAPER-001"
    assert invoke("corpus", "show", PROJECT, "PAPER-999").exit_code == 1

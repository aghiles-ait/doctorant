"""Serveur web : API en lecture seule sur la base, pour l'interface React."""

import pytest
from fastapi.testclient import TestClient
from test_cli_flow import PROJECT, apis, invoke, project_ready  # noqa: F401 — fixtures partagées
from test_cli_flow import test_gate_2_flow as run_complete_flow

from research_lab.api import create_app


@pytest.fixture
def client(project_ready, apis, lab_root, tmp_path, monkeypatch):  # noqa: F811
    run_complete_flow(project_ready, apis, lab_root, tmp_path, monkeypatch)  # projet terminé
    assert invoke("project", "init", "second", "--topic", "Second sujet").exit_code == 0
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ui</title>")
    return TestClient(create_app(lab_root, dist))


def test_projects_and_workflow(client):
    projects = {p["id"]: p for p in client.get("/api/projects").json()}
    assert (projects[PROJECT]["state"], projects["second"]["state"]) == ("COMPLETED", "NEW")
    workflow = client.get("/api/workflow").json()
    assert set(workflow["deliverables"]) == set(workflow["states"])


def test_project_view_is_read_from_the_database(client):
    view = client.get(f"/api/projects/{PROJECT}").json()
    assert view["visits"]["SCIENTIFIC_REVIEW"] == 1 and view["reviews"][0]["verdict"] == "ACCEPTABLE"
    assert view["files"]["gaps.json"]["exists"]
    assert not client.get("/api/projects/second").json()["files"]["gaps.json"]["exists"]  # exporté vide
    [paper] = [x for x in view["papers"]["all"] if x["id"] == "PAPER-001"]
    assert paper["status"] == "included" and paper["url"].startswith("https://doi.org/")
    assert client.get(paper["pdf"]).headers["content-type"] == "application/pdf"
    assert view["search_log"][0]["id"] == "SEARCH-001" and "scope.md" in view["documents"]
    # Une écriture dans la base est visible à la requête suivante, sans redémarrer le serveur.
    assert invoke("project", "transition", "second", "SCOPING").exit_code == 0
    assert client.get("/api/projects/second").json()["state"] == "SCOPING"


def test_files_and_documents_are_whitelisted(client):
    assert client.get(f"/api/projects/{PROJECT}/files/gaps.json").json()[0]["gap_id"] == "GAP-001"
    assert client.get(f"/api/projects/{PROJECT}/documents/scope.md").text == "modifié après la décision"  # texte du fichier
    for url in (f"/api/projects/{PROJECT}/files/drafts", f"/api/projects/{PROJECT}/documents/gaps.json",
                "/api/projects/inconnu", "/api/papers/..%2Fresearch.db/pdf", "/api/papers/PAPER-999/pdf"):
        assert client.get(url).status_code == 404, url


def test_compiled_interface_is_served(client):
    assert "<title>ui</title>" in client.get("/").text

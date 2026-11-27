"""Routes d'écriture de l'interface web : mêmes opérations et mêmes contrôles que la CLI."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_cli_flow import PROJECT, apis, invoke, project_ready  # noqa: F401 — fixtures partagées
from test_cli_flow import test_gate_2_flow as run_complete_flow

from research_lab.api import create_app
from research_lab.config import load_settings
from research_lab.storage.database import Database
from research_lab.storage.repositories import highest_id, next_evidence_id, next_search_id

BASE = f"/api/projects/{PROJECT}"


@pytest.fixture
def client(project_ready, lab_root):  # noqa: F811
    return TestClient(create_app(lab_root))


def test_create_project(client):
    created = client.post("/api/projects", json={"project_id": "nouveau-sujet", "topic": "Un sujet"})
    assert created.status_code == 201 and created.json()["state"] == "NEW"
    assert client.post("/api/projects", json={"project_id": "nouveau-sujet", "topic": "x"}).status_code == 409
    assert client.post("/api/projects", json={"project_id": "Pas Valide", "topic": "x"}).status_code == 422
    history = client.get("/api/projects/nouveau-sujet").json()["history"]
    assert history[0]["actor"].endswith("(interface web)")


def test_search_is_journaled_like_the_cli(client, apis):  # noqa: F811
    body = {"query": "decentralized autonomous machines", "date_from": "2024-01-01", "date_to": "2026-10-26",
            "max_results": 3}
    execution = client.post(f"{BASE}/search", json=body).json()
    assert execution["status"] == "completed" and len(execution["new_paper_ids"]) == 4
    assert client.get(BASE).json()["search_log"][0]["id"] == execution["search_id"]
    refused = client.post(f"{BASE}/search", json={**body, "gap_id": "GAP-001"})
    assert refused.status_code == 409 and "GAP_ANALYSIS" in refused.json()["detail"]


def test_transitions_keep_preconditions_and_gates(client):
    refused = client.post(f"{BASE}/transition", json={"target": "LITERATURE_REVIEW"})
    assert refused.status_code == 409 and refused.json()["detail"].startswith("Transition refusée")
    forced = client.post(f"{BASE}/transition", json={"target": "SCOPING", "force": True})
    assert forced.json()["state"] == "SCOPING"
    history = client.get(BASE).json()["history"]  # rembobiné : plus de passage par LITERATURE_SEARCH
    assert [c["to_state"] for c in history] == ["NEW", "SCOPING"]
    for target in ("AWAITING_GATE_1", "COMPLETED"):  # jamais, même forcé
        assert client.post(f"{BASE}/transition", json={"target": target, "force": True}).status_code == 409


def test_no_route_decides_a_gate(client):
    paths = {route.path for route in client.app.routes}
    assert not any("gate" in p or "rate" in p for p in paths)


def test_writes_from_another_origin_are_refused(client):
    body = {"project_id": "csrf", "topic": "x"}
    assert client.post("/api/projects", json=body, headers={"origin": "https://example.com"}).status_code == 403
    assert client.post("/api/projects", json=body, headers={"origin": "http://localhost:5173"}).status_code == 201


def test_repair_costs_and_backup(client, lab_root):
    assert client.post(f"{BASE}/repair").json() == {"stale_exports": []}
    assert client.post("/api/costs/sync").status_code == 200
    saved = client.post("/api/backup").json()
    assert saved["path"].startswith(str(lab_root / "backups"))
    assert (lab_root / "backups").is_dir() and saved["schema_version"] >= 11
    assert client.post(f"{BASE}/fulltext").status_code == 409  # pas avant l'état de l'art


def test_delete_a_complete_project(project_ready, apis, lab_root, tmp_path, monkeypatch):  # noqa: F811
    run_complete_flow(project_ready, apis, lab_root, tmp_path, monkeypatch)  # toutes les tables sont remplies
    client = TestClient(create_app(lab_root))
    db = Database(load_settings(lab_root).db_path)
    before = {prefix: highest_id(db, prefix) for prefix in ("PAPER", "SEARCH", "EV", "GAP", "OBJ")}
    pdfs = list((lab_root / "knowledge" / "papers").glob("*.pdf"))
    assert pdfs and project_ready.is_dir()

    refused = client.post(f"{BASE}/delete", json={"confirm": "autre"})
    assert refused.status_code == 422 and client.get(BASE).status_code == 200
    counts = client.post(f"{BASE}/delete", json={"confirm": PROJECT}).json()
    assert counts["papers"] > 0 and counts["evidence"] > 0 and counts["papers_kept"] == 0

    assert client.get(BASE).status_code == 404 and not project_ready.exists()
    assert not any(p.exists() for p in pdfs)
    # Aucune trace du projet : seul le compteur d'identifiants subsiste.
    for table in ("papers", "searches", "evidence", "gaps", "state_changes", "gate_decisions", "project_deletions"):
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    # Les identifiants ne sont jamais réattribués.
    assert {prefix: highest_id(db, prefix) for prefix in before} == before
    assert next_search_id(db) == f"SEARCH-{before['SEARCH'] + 1:03d}"
    assert next_evidence_id(db) == f"EV-{before['EV'] + 1:03d}"

    # Le même identifiant peut resservir ; une nouvelle recherche reçoit de nouveaux numéros.
    assert client.post("/api/projects", json={"project_id": PROJECT, "topic": "Nouveau départ"}).status_code == 201
    client.post(f"{BASE}/transition", json={"target": "LITERATURE_SEARCH", "force": True})
    execution = client.post(f"{BASE}/search", json={"query": "decentralized autonomous machines"}).json()
    assert execution["search_id"] == f"SEARCH-{before['SEARCH'] + 1:03d}"
    assert min(int(p.split("-")[1]) for p in execution["new_paper_ids"]) == before["PAPER"] + 1


def test_protection_holds_outside_a_deletion(project_ready, apis, lab_root):  # noqa: F811
    invoke("watch", "search", PROJECT, "--query", "decentralized autonomous machines")
    db = Database(load_settings(lab_root).db_path)
    for table in ("searches", "papers", "state_changes"):
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(f"DELETE FROM {table}")


def test_cli_delete_is_human_only(project_ready):  # noqa: F811
    refused = invoke("project", "delete", PROJECT)  # pas de terminal interactif
    assert refused.exit_code == 1 and "Suppression refusée" in refused.output and project_ready.is_dir()


def test_upload_scope_unlocks_the_literature_search(client):
    created = client.post("/api/projects", json={"project_id": "depot", "topic": "Sujet"})
    assert created.status_code == 201
    url = "/api/projects/depot/documents/scope.md"
    scope = "# Périmètre\n\n## 1. Question\nQuoi ?\n\n## 2. Périmètre (inclus, exclus)\nDAO.\n"
    assert client.put(url, json={"text": scope}).status_code == 409  # état NEW
    client.post("/api/projects/depot/transition", json={"target": "SCOPING"})
    assert client.put(url, json={"text": "Pas de sections"}).status_code == 422
    assert client.put(url, json={"text": scope}).json() == {"sections": {"1": "Question", "2": "Périmètre"}}
    assert client.get(url).text == scope
    assert client.post("/api/projects/depot/transition", json={"target": "LITERATURE_SEARCH"}).json() == {
        "state": "LITERATURE_SEARCH"}


def test_forced_return_erases_the_later_states(project_ready, apis, lab_root, tmp_path, monkeypatch):  # noqa: F811
    run_complete_flow(project_ready, apis, lab_root, tmp_path, monkeypatch)
    client = TestClient(create_app(lab_root))
    db = Database(load_settings(lab_root).db_path)
    count = lambda table, where="project_id = ?": db.conn.execute(  # noqa: E731
        f"SELECT COUNT(*) FROM {table} WHERE {where}", (PROJECT,)).fetchone()[0]
    before = {t: count(t) for t in ("evidence", "screening_decisions", "searches", "project_papers")}
    assert count("gaps") and count("scientific_reviews") and count("searches", "project_id = ? AND gap_id IS NOT NULL")

    def back(target):
        assert client.post(f"{BASE}/transition", json={"target": target, "force": True}).json() == {"state": target}
        return client.get(BASE).json()

    # Retour à l'état de l'art : gaps, gates, questions, solutions, revues, Proposal et notes disparaissent.
    view = back("LITERATURE_REVIEW")
    for table in ("gaps", "gate_submissions", "research_questions", "solutions", "scientific_reviews", "rating_sessions"):
        assert count(table) == 0, table
    assert count("searches", "project_id = ? AND gap_id IS NOT NULL") == 0  # recherches contradictoires
    assert 0 < count("evidence") <= before["evidence"] and count("screening_decisions") > 0
    assert [c["to_state"] for c in view["history"]][-1] == "LITERATURE_REVIEW"
    assert "GAP_ANALYSIS" not in view["visits"] and not view["gaps"] and not view["gate_1"]
    assert (project_ready / "literature-review.md").exists() and not (project_ready / "research-proposal.md").exists()
    assert not (project_ready / "drafts").exists()

    # Retour à la recherche : le tri et les preuves disparaissent, le corpus reste à trier.
    back("LITERATURE_SEARCH")
    assert count("evidence") == count("screening_decisions") == 0 and count("searches") > 0
    assert set(view["papers"]["by_status"]) >= {"included"}
    assert set(client.get(BASE).json()["papers"]["by_status"]) == {"candidate"}
    assert not (project_ready / "literature-review.md").exists()

    # Retour au périmètre : plus de corpus ; les publications d'aucun autre projet sont supprimées.
    back("SCOPING")
    assert count("searches") == count("project_papers") == 0
    assert db.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    assert (project_ready / "scope.md").exists()
    back("NEW")
    assert not (project_ready / "scope.md").exists()
    assert [c["to_state"] for c in client.get(BASE).json()["history"]] == ["NEW"]


def test_cli_forced_return_is_human_only(project_ready, monkeypatch):  # noqa: F811
    from research_lab import cli
    from test_cli_flow import runner

    refused = invoke("project", "transition", PROJECT, "SCOPING", "--force")
    assert refused.exit_code == 1 and "Retour en arrière refusé" in refused.output
    assert invoke("project", "transition", PROJECT, "LITERATURE_REVIEW", "--force").exit_code == 0  # en avant : libre
    monkeypatch.setattr(cli, "human_check_failure", lambda: None)
    wrong = runner.invoke(cli.app, ["project", "transition", PROJECT, "SCOPING", "--force"], input="autre\n")
    assert wrong.exit_code == 1 and "rien n'a changé" in wrong.output
    done = runner.invoke(cli.app, ["project", "transition", PROJECT, "SCOPING", "--force"], input=f"{PROJECT}\n")
    assert done.exit_code == 0 and "état SCOPING" in done.output


def test_config_form_edits_values_and_keeps_comments(client, lab_root):
    config = client.get("/api/config").json()
    values = config["data"]["research-values.yaml"]
    assert values["values"]["privacy"]["weight"] == 1.0  # formulaire pré-rempli
    values["values"]["privacy"]["weight"] = 2.5
    values["values"]["privacy"]["description"] = "Nouvelle description."
    changed = client.put("/api/config/research-values.yaml", json={"data": values}).json()
    assert changed == {"values_changed": True, "config_changed": False}
    text = (lab_root / "config" / "research-values.yaml").read_text()
    assert "weight: 2.5" in text and "description: >\n      Nouvelle description." in text
    assert client.get("/api/config").json()["values"]["values"]["privacy"]["weight"] == 2.5

    policy = config["data"]["research-policy.yaml"]
    policy["literature_search"]["min_corpus_size"] = 30
    assert client.put("/api/config/research-policy.yaml", json={"data": policy}).json()["config_changed"]
    assert "# En dessous de ce seuil" in (lab_root / "config" / "research-policy.yaml").read_text()
    assert set(config["informative"]["research-policy.yaml"]) == {"human_gates", "scientific_quality"}
    policy["human_gates"]["gate_1"] = "optional"  # non lu par le code : refusé
    refused = client.put("/api/config/research-policy.yaml", json={"data": policy})
    assert refused.status_code == 422 and "informative" in refused.json()["detail"]

    before = (lab_root / "config" / "research-values.yaml").read_text()
    values["values"]["privacy"]["weight"] = -1  # refusé par le modèle (poids ≥ 0)
    refused = client.put("/api/config/research-values.yaml", json={"data": values})
    assert refused.status_code == 422 and "fichier inchangé" in refused.json()["detail"]
    for bad in ({"values": {"inconnue": {"weight": 1}}}, {"values": {"privacy": {"weight": "beaucoup"}}}):
        assert client.put("/api/config/research-values.yaml", json={"data": bad}).status_code == 422
    assert client.put("/api/config/autre.yaml", json={"data": {}}).status_code == 422
    assert (lab_root / "config" / "research-values.yaml").read_text() == before

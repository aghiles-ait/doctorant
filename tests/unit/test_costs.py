"""Sprint 4 : suivi des coûts, d'après des transcriptions au format de Claude Code."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_review import settings  # noqa: F401 — fixture partagée

from research_lab.costs import cost, cost_report, load_usage, sync
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectRepository
from research_lab.workflow.state import ResearchState as S

SESSION = "11111111-2222-3333-4444-555555555555"
START = datetime(2026, 11, 6, 13, 0, tzinfo=UTC)


def _assistant(message_id, minutes, *, command=None, model="claude-opus-5-5", agent=None, **usage):
    content = [{"type": "tool_use", "name": "Bash", "input": {"command": command}}] if command else []
    return {
        "type": "assistant", "sessionId": SESSION, "agentId": agent,
        "timestamp": (START + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        "message": {"id": message_id, "model": model, "content": content, "usage": {
            "input_tokens": 10, "output_tokens": 1000, "cache_read_input_tokens": 100_000,
            "cache_creation_input_tokens": 2000,
            "cache_creation": {"ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 0}, **usage,
        }},
    }


def _write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + '{"type": "assistant", "mess')  # ligne coupée


@pytest.fixture
def transcripts(settings):
    db = Database(settings.db_path)
    repo = ProjectRepository(db, settings.projects_dir, "alpha")
    repo.create("Gouvernance décentralisée", actor="alice")
    root = settings.transcripts_dir
    # Session principale : développement, sans projet, même si elle mentionne alpha.
    _write(root / f"{SESSION}.jsonl", [_assistant("msg_main", 1, command="research-lab project status alpha")])
    # Sous-agent doctorant : deux réponses, la première écrite en deux blocs (même identifiant).
    doctorant = root / SESSION / "subagents" / "agent-a1.jsonl"
    _write(doctorant, [
        _assistant("msg_d1", 2, agent="a1"),
        _assistant("msg_d1", 2, agent="a1", command=".venv/bin/research-lab question check alpha"),
        _assistant("msg_d2", 90, agent="a1", model="claude-unknown"),
    ])
    doctorant.with_suffix(".meta.json").write_text(json.dumps({"agentType": "doctorant"}))
    return repo


def test_sync_records_each_response_once_and_attributes_research_agents(transcripts, settings):
    db = transcripts.db
    assert sync(db, settings) == 3
    assert sync(db, settings) == 0  # idempotent
    usages = {u.message_id: u for u in load_usage(db)}
    assert usages["msg_main"].agent_type == "main" and usages["msg_main"].project_id is None
    assert (usages["msg_d1"].agent_type, usages["msg_d1"].project_id) == ("doctorant", "alpha")
    assert [u.message_id for u in load_usage(db, "alpha")] == ["msg_d1", "msg_d2"]


def test_cost_uses_configured_prices(transcripts, settings):
    sync(transcripts.db, settings)
    [main] = [u for u in load_usage(transcripts.db) if u.message_id == "msg_main"]
    # 10 × 4 + 1000 × 20 + 2000 × 5 + 100 000 × 0,20 (dollars par million de jetons)
    assert cost(main, settings.costs.prices) == pytest.approx((40 + 20_000 + 10_000 + 20_000) / 1e6)


def test_report_by_agent_state_and_model(transcripts, settings):
    transcripts.transition(S.SCOPING, actor="alice", policy=settings.policy)
    project = transcripts.load_project()
    # Création avant les réponses, passage à SCOPING entre les deux réponses du doctorant.
    project.history[0].at, project.history[-1].at = START - timedelta(hours=1), START + timedelta(minutes=30)
    sync(transcripts.db, settings)
    report = cost_report(load_usage(transcripts.db, "alpha"), settings.costs.prices, project)
    assert (report.total.responses, report.agent_runs) == (2, 1)
    assert set(report.by_state) == {"NEW", "SCOPING"}
    assert report.unpriced_models == ["claude-unknown"]
    assert report.by_model["claude-unknown"].cost == 0


def test_missing_transcripts_directory_is_not_an_error(settings):
    assert sync(Database(settings.db_path), settings) == 0


def test_usage_is_append_only(transcripts, settings):
    sync(transcripts.db, settings)
    with pytest.raises(Exception, match="ajout seul"):
        transcripts.db.conn.execute("DELETE FROM llm_usage")

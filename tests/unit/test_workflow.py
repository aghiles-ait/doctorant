import pytest

from research_lab.config import PolicyConfig
from research_lab.storage.database import Database
from research_lab.storage.repositories import ProjectRepository
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

POLICY = PolicyConfig(version="1.0", min_corpus_size=0)


@pytest.fixture
def repo(tmp_path) -> ProjectRepository:
    repo = ProjectRepository(Database(tmp_path / "research.db"), tmp_path / "projects", "test-project")
    repo.create("Decentralized AI governance", actor="alice")
    return repo


def test_new_project_files(repo):
    project = repo.load_project()
    assert project.state == ResearchState.NEW
    assert repo.load_papers() == []
    assert repo.load_search_log() == []
    assert repo.project_file.is_file() and repo.papers_file.is_file() and repo.search_log_file.is_file()


def test_cannot_create_twice(repo):
    with pytest.raises(FileExistsError):
        repo.create("again", actor="alice")


def test_literature_search_requires_scope(repo):
    repo.transition(ResearchState.SCOPING, actor="alice", policy=POLICY)
    with pytest.raises(TransitionError, match="scope.md"):
        repo.transition(ResearchState.LITERATURE_SEARCH, actor="alice", policy=POLICY)
    repo.scope_file.write_text("   \n")
    with pytest.raises(TransitionError, match="scope.md"):
        repo.transition(ResearchState.LITERATURE_SEARCH, actor="alice", policy=POLICY)

    repo.scope_file.write_text("# Scope\nGouvernance décentralisée des agents IA.\n")
    project = repo.transition(ResearchState.LITERATURE_SEARCH, actor="alice", policy=POLICY)
    assert project.state == ResearchState.LITERATURE_SEARCH
    assert [(h.from_state, h.to_state) for h in project.history] == [
        (None, ResearchState.NEW),
        (ResearchState.NEW, ResearchState.SCOPING),
        (ResearchState.SCOPING, ResearchState.LITERATURE_SEARCH),
    ]


@pytest.mark.parametrize("target", [ResearchState.LITERATURE_SEARCH, ResearchState.AWAITING_GATE_1, ResearchState.COMPLETED])
def test_skipping_states_is_refused(repo, target):
    with pytest.raises(TransitionError, match="non autorisée"):
        repo.transition(target, actor="alice", policy=POLICY)
    assert repo.load_project().state == ResearchState.NEW


def test_state_survives_reload(tmp_path, repo):
    repo.transition(ResearchState.SCOPING, actor="alice", policy=POLICY)
    repo.db.close()
    reopened = ProjectRepository(Database(tmp_path / "research.db"), tmp_path / "projects", "test-project")
    assert reopened.load_project().state == ResearchState.SCOPING

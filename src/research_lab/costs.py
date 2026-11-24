"""Suivi des coûts des agents (sprint 4).

Claude Code écrit une transcription par session et par sous-agent (JSON Lines), avec la consommation de jetons de
chaque réponse du modèle. `sync` les relit et enregistre chaque réponse une seule fois dans la base : les
transcriptions sont effacées après quelques semaines, la base les conserve. Une réponse est attribuée à un projet
seulement si elle vient d'un agent de recherche (doctorant, scientific-reviewer) dont les commandes
`research-lab` désignent ce projet ; le reste (développement du laboratoire) est compté sans projet.

Le coût est calculé avec les prix de config/costs.yaml : avec un abonnement, c'est un équivalent API.
"""

import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from research_lab.config import ModelPrice, Settings
from research_lab.schemas.project import Project
from research_lab.storage.database import Database


@dataclass(frozen=True)
class Usage:
    message_id: str
    session_id: str
    agent_id: str | None
    agent_type: str
    project_id: str | None
    model: str
    at: datetime
    input_tokens: int
    output_tokens: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read_tokens: int


def _transcripts(directory: Path) -> Iterator[tuple[Path, str | None]]:
    """Transcriptions des sessions principales et des sous-agents, avec le type d'agent des seconds."""
    for path in sorted(directory.glob("*.jsonl")):
        yield path, None
    for path in sorted(directory.glob("*/subagents/*.jsonl")):
        meta = path.with_suffix(".meta.json")
        agent_type = None
        if meta.exists():
            try:
                agent_type = json.loads(meta.read_text(encoding="utf-8")).get("agentType")
            except json.JSONDecodeError:
                pass
        yield path, agent_type


def _project_mentions(entry: dict, project_ids: set[str]) -> Counter:
    """Projets désignés par les commandes `research-lab` d'une réponse du modèle."""
    mentions: Counter = Counter()
    for block in entry.get("message", {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
            command = str(block.get("input", {}).get("command", ""))
            if "research-lab" in command:
                for word in set(re.findall(r"[a-z0-9][a-z0-9-]*", command)):
                    if word in project_ids:
                        mentions[word] += command.count(word)
    return mentions


def read_transcript(path: Path, agent_type: str | None, settings: Settings, project_ids: set[str]) -> list[Usage]:
    """Une entrée par réponse du modèle (la dernière occurrence fait foi : une réponse est écrite par blocs)."""
    entries: dict[str, dict] = {}
    mentions: Counter = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # ligne en cours d'écriture
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict) or not message.get("usage"):
            continue
        if message.get("model", "").startswith("<"):
            continue  # réponses synthétiques de Claude Code, sans appel au modèle
        entries[message.get("id") or entry.get("uuid")] = entry
        mentions += _project_mentions(entry, project_ids)

    research = set(settings.costs.research_agents)
    project = mentions.most_common(1)[0][0] if mentions else None
    usages = []
    for message_id, entry in entries.items():
        usage = entry["message"]["usage"]
        kind = agent_type or entry.get("attributionAgent") or "main"
        cache = usage.get("cache_creation") or {}
        written = usage.get("cache_creation_input_tokens", 0) or 0
        write_1h = cache.get("ephemeral_1h_input_tokens", 0) or 0
        usages.append(Usage(
            message_id=message_id, session_id=entry.get("sessionId", ""), agent_id=entry.get("agentId"),
            agent_type=kind, project_id=project if kind in research else None,
            model=entry["message"].get("model", "unknown"),
            at=datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")),
            input_tokens=usage.get("input_tokens", 0) or 0, output_tokens=usage.get("output_tokens", 0) or 0,
            cache_write_5m=cache.get("ephemeral_5m_input_tokens", written - write_1h) or 0, cache_write_1h=write_1h,
            cache_read_tokens=usage.get("cache_read_input_tokens", 0) or 0,
        ))
    return usages


def sync(db: Database, settings: Settings) -> int:
    """Enregistre les réponses pas encore connues ; renvoie leur nombre. Relancer ne change rien."""
    directory = settings.transcripts_dir
    if not directory.is_dir():
        return 0
    project_ids = {r["project_id"] for r in db.conn.execute("SELECT project_id FROM projects")}
    known = {r["message_id"] for r in db.conn.execute("SELECT message_id FROM llm_usage")}
    new = [
        u for path, agent_type in _transcripts(directory)
        for u in read_transcript(path, agent_type, settings, project_ids) if u.message_id not in known
    ]
    unique = list({u.message_id: u for u in new}.values())
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO llm_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(u.message_id, u.session_id, u.agent_id, u.agent_type, u.project_id, u.model, u.at.isoformat(),
              u.input_tokens, u.output_tokens, u.cache_write_5m, u.cache_write_1h, u.cache_read_tokens)
             for u in unique],
        )
    return len(unique)


def load_usage(db: Database, project_id: str | None = None) -> list[Usage]:
    where, params = ("WHERE project_id = ?", (project_id,)) if project_id else ("", ())
    rows = db.conn.execute(f"SELECT * FROM llm_usage {where} ORDER BY at", params)
    return [Usage(**{**dict(r), "at": datetime.fromisoformat(r["at"])}) for r in rows]


def cost(usage: Usage, prices: dict[str, ModelPrice]) -> float | None:
    """Coût en dollars, ou None si le modèle n'a pas de prix configuré."""
    price = prices.get(usage.model.split("[")[0])
    if price is None:
        return None
    return (
        usage.input_tokens * price.input + usage.output_tokens * price.output
        + usage.cache_write_5m * price.cache_write_5m + usage.cache_write_1h * price.cache_write_1h
        + usage.cache_read_tokens * price.cache_read
    ) / 1_000_000


@dataclass
class Line:
    responses: int = 0
    input_tokens: int = 0  # entrée non mise en cache + écriture en cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0

    def add(self, usage: Usage, amount: float | None) -> None:
        self.responses += 1
        self.input_tokens += usage.input_tokens + usage.cache_write_5m + usage.cache_write_1h
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cost += amount or 0.0


@dataclass
class CostReport:
    project_id: str | None
    total: Line = field(default_factory=Line)
    by_agent: dict[str, Line] = field(default_factory=dict)
    by_state: dict[str, Line] = field(default_factory=dict)
    by_model: dict[str, Line] = field(default_factory=dict)
    unpriced_models: list[str] = field(default_factory=list)
    agent_runs: int = 0


def _state_at(project: Project, at: datetime) -> str:
    """État du projet à un instant donné, d'après l'historique."""
    state = "NEW"
    for change in project.history:
        if change.at > at:
            break
        state = str(change.to_state)
    return state


def cost_report(usages: list[Usage], prices: dict[str, ModelPrice], project: Project | None = None) -> CostReport:
    report = CostReport(project_id=project.project_id if project else None)
    for usage in usages:
        amount = cost(usage, prices)
        if amount is None and usage.model not in report.unpriced_models:
            report.unpriced_models.append(usage.model)
        report.total.add(usage, amount)
        report.by_agent.setdefault(usage.agent_type, Line()).add(usage, amount)
        report.by_model.setdefault(usage.model, Line()).add(usage, amount)
        if project:
            report.by_state.setdefault(_state_at(project, usage.at), Line()).add(usage, amount)
    report.agent_runs = len({(u.session_id, u.agent_id) for u in usages})
    return report

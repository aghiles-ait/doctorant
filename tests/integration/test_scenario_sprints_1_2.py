"""Scénario de démonstration des sprints 1 et 2, de bout en bout, via la CLI.

    .venv/bin/pytest tests/integration/test_scenario_sprints_1_2.py -s

affiche chaque commande et sa sortie. Les réponses d'arXiv et d'OpenAlex sont de vraies réponses
enregistrées ; le contenu des PDF, en revanche, est simulé (deux pages courtes par article).
"""

import json
from pathlib import Path

import httpx
import respx
from conftest import make_pdf
from typer.testing import CliRunner

from research_lab import cli
from research_lab.cli import app
from research_lab.workflow import approvals

PROJECT = "decentralized-ai-governance"
VALUES = ["privacy", "freedom", "sovereignty", "governance", "decentralization", "verifiability"]

# Texte simulé des PDF des deux articles arXiv du corpus.
DAM_PAGES = [
    "Trustworthy Decentralized Autonomous Machines",
    "In our experiments, DAM agents completed most tasks without any trusted intermediary.\n"
    "Verifying the governance decisions of autonomous machines remains an open problem.",
]
GOVERNANCE_PAGES = [
    "Delegation and Participation in Decentralized Governance",
    "We find that partial abstention is a strong governance method from an epistemic standpoint.",
]

runner = CliRunner()


def step(title: str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def run(*args: str, expect: int = 0, stdin: str | None = None) -> str:
    result = runner.invoke(app, list(args), input=stdin)
    print(f"\n$ research-lab {' '.join(args)}\n{result.output.rstrip()}")
    assert result.exit_code == expect, result.output
    return result.output


def test_scenario_sprints_1_2(lab_root, fixture_text, tmp_path, monkeypatch):
    monkeypatch.chdir(lab_root)  # chemins relatifs, comme à la racine du dépôt
    project_dir = Path("research") / "projects" / PROJECT
    drafts = project_dir / "drafts"
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=fixture_text("arxiv_search.xml")))
        respx.get("https://api.openalex.org/works").mock(
            return_value=httpx.Response(200, text=fixture_text("openalex_search.json")))
        respx.get("https://export.arxiv.org/pdf/2504.15676").mock(
            return_value=httpx.Response(200, content=make_pdf(DAM_PAGES)))
        respx.get("https://export.arxiv.org/pdf/2505.04136").mock(
            return_value=httpx.Response(200, content=make_pdf(GOVERNANCE_PAGES)))

        # ------------------------------------------------------------------ sprint 1
        step("SPRINT 1 — Projet et périmètre : la recherche est refusée tant que scope.md est vide")
        run("project", "init", PROJECT, "--topic", "Decentralized AI governance")
        run("project", "transition", PROJECT, "SCOPING")
        run("project", "transition", PROJECT, "LITERATURE_SEARCH", expect=1)
        (project_dir / "scope.md").write_text(
            "# Périmètre\nQuestion : comment gouverner des agents IA décentralisés de façon vérifiable ?\n"
            "Inclus : gouvernance décentralisée, agents autonomes. Exclus : jeux de données, véhicules.\n")
        run("project", "transition", PROJECT, "LITERATURE_SEARCH")

        step("SPRINT 1 — Veille : arXiv + OpenAlex, déduplication, provenance, journal")
        run("watch", "search", PROJECT, "-q", "decentralized autonomous machines",
            "--from", "2024-01-01", "--to", "2026-10-26", "--max-results", "3")
        run("corpus", "list", PROJECT)
        run("search-log", PROJECT)
        run("corpus", "check", PROJECT)

        # ------------------------------------------------------------------ sprint 2a
        step("SPRINT 2a — Base SQLite partagée (source de vérité)")
        run("db", "info")

        # ------------------------------------------------------------------ sprint 2b
        step("SPRINT 2b — État de l'art : refusé sous 20 publications ; seuil abaissé à 4 pour la démonstration")
        run("project", "transition", PROJECT, "LITERATURE_REVIEW", expect=1)
        policy = lab_root / "config" / "research-policy.yaml"
        policy.write_text(policy.read_text().replace("min_corpus_size: 20", "min_corpus_size: 4"))
        run("project", "transition", PROJECT, "LITERATURE_REVIEW")

        step("SPRINT 2b — Tri selon scope.md")
        papers = json.loads(runner.invoke(app, ["corpus", "list", PROJECT, "--json"]).output)
        ids = {p["arxiv_id"] or p["openalex_id"]: p["paper_id"] for p in papers}
        dam, governance = ids["2504.15676"], ids["2505.04136"]
        for paper_id in ids.values():
            if paper_id in (dam, governance):
                run("corpus", "decide", PROJECT, paper_id, "--include", "--reason", "Gouvernance d'agents décentralisés")
            else:
                run("corpus", "decide", PROJECT, paper_id, "--exclude", "--reason", "Hors périmètre (scope.md)")

        step("SPRINT 2b — Texte intégral des publications incluses")
        run("fulltext", "fetch", PROJECT)
        run("fulltext", "show", PROJECT, dam, "--page", "2")

        step("SPRINT 2b — Preuves : un extrait inventé est refusé, un extrait exact est accepté")
        run("evidence", "add", PROJECT, "--paper", dam, "--page", "2", "--type", "empirical_result",
            "--claim", "Les DAM sont prouvées sûres", "--quote", "DAM agents are provably secure against all attacks",
            expect=1)
        run("evidence", "add", PROJECT, "--paper", dam, "--page", "2", "--type", "empirical_result",
            "--claim", "Les DAM accomplissent leurs tâches sans intermédiaire de confiance",
            "--quote", "DAM agents completed most tasks without any trusted intermediary")
        run("evidence", "add", PROJECT, "--paper", dam, "--page", "2", "--type", "limitation",
            "--claim", "La vérification des décisions de gouvernance des machines autonomes reste ouverte",
            "--quote", "Verifying the governance decisions of autonomous machines remains an open problem")
        run("evidence", "add", PROJECT, "--paper", governance, "--page", "2", "--type", "empirical_result",
            "--claim", "L'abstention partielle est une bonne méthode de gouvernance d'un point de vue épistémique",
            "--quote", "partial abstention is a strong governance method from an epistemic standpoint")

        step("SPRINT 2b — literature-review.md, contrôle des citations, passage à l'analyse des gaps")
        (project_dir / "literature-review.md").write_text(
            "# État de l'art\n## Méthode\nSEARCH-001, arXiv et OpenAlex, 4 publications, 2 incluses.\n"
            f"## Synthèse\nLes DAM fonctionnent sans intermédiaire de confiance [{dam}, EV-001], mais la "
            f"vérification de leurs décisions reste ouverte [{dam}, EV-002]. L'abstention partielle est une "
            f"méthode de gouvernance robuste [{governance}, EV-003].\n## Limites\nCorpus de démonstration.\n")
        run("review", "check", PROJECT)
        run("project", "transition", PROJECT, "GAP_ANALYSIS")

        # ------------------------------------------------------------------ sprint 2c
        step("SPRINT 2c — Gap : un nouveau gap est toujours candidate")
        drafts.mkdir()
        gap = {
            "title": "Gouvernance vérifiable des agents autonomes décentralisés",
            "description": "Les mécanismes de gouvernance décentralisée évalués ne permettent pas de vérifier "
                           "les décisions prises par des agents autonomes.",
            "category": "unresolved_research_question",
            "rationale": "EV-002 : les auteurs reconnaissent le problème comme ouvert ; EV-001 et EV-003 "
                         "évaluent l'autonomie et la qualité des décisions, jamais leur vérifiabilité.",
            "supporting_evidence": ["EV-001", "EV-002", "EV-003"],
            "evidence_strength": "high",
            "limitations": ["Corpus de 4 publications"],
            "objections": ["La vérifiabilité est peut-être traitée sous un autre nom (auditabilité)"],
        }
        (drafts / "gap.json").write_text(json.dumps(gap, ensure_ascii=False))
        run("gap", "add", PROJECT, "--file", str(drafts / "gap.json"), "--reason", "Croisement de EV-001 à EV-003")
        (drafts / "gap.json").write_text(json.dumps(gap | {"status": "supported"}, ensure_ascii=False))
        run("gap", "revise", PROJECT, "GAP-001", "--file", str(drafts / "gap.json"), "--reason", "r", expect=1)

        step("SPRINT 2c — Recherche contradictoire (Q3), puis révision du gap")
        run("watch", "search", PROJECT, "-q", "verifiable governance autonomous agents", expect=1)
        run("watch", "search", PROJECT, "--for-gap", "GAP-001", "-q", "verifiable governance autonomous agents",
            "--max-results", "3")
        (drafts / "gap.json").write_text(json.dumps(
            gap | {"status": "supported", "novelty_assessment": "not_found_in_searches"}, ensure_ascii=False))
        run("gap", "revise", PROJECT, "GAP-001", "--file", str(drafts / "gap.json"),
            "--reason", "SEARCH-002 ne trouve aucun travail qui comble le gap")
        run("gap", "list", PROJECT)

        step("SPRINT 2c — Évaluation au regard des valeurs, priorité calculée par le code")
        alignment = {
            "scores": {v: {"score": 4, "justification": f"Rendre la gouvernance vérifiable sert {v}"} for v in VALUES}
            | {"privacy": {"score": 2, "justification": "Vérifier les décisions peut exposer des données"}},
            "tradeoffs": ["verifiability contre privacy : vérifier une décision exige d'en publier les éléments"],
        }
        (drafts / "alignment-GAP-001.json").write_text(json.dumps(alignment, ensure_ascii=False))
        run("alignment", "set", PROJECT, "GAP-001", "--file", str(drafts / "alignment-GAP-001.json"))
        run("alignment", "show", PROJECT)
        run("gap", "check", PROJECT)

        # ------------------------------------------------------------------ sprint 2d
        step("SPRINT 2d — Gate 1 : l'agent soumet, le dossier est figé")
        run("project", "transition", PROJECT, "AWAITING_GATE_1", expect=1)
        run("gate", "submit", PROJECT)
        run("gate", "status", PROJECT)

        step("SPRINT 2d — Gate 1 : refusée sans humain ; puis un humain approuve (terminal simulé)")
        run("gate", "approve", PROJECT, "--gap", "GAP-001", "--comment", "ok", expect=1)
        for module in (cli, approvals):
            monkeypatch.setattr(module, "human_check_failure", lambda: None)
        run("gate", "approve", PROJECT, "--gap", "GAP-001", "--comment", "Problématique retenue",
            stdin=f"{PROJECT}\n")
        run("project", "status", PROJECT)
        run("gate", "verify", PROJECT)

        step("Fichiers du projet (exports régénérés depuis la base)")
        print("\n".join(sorted(p.name for p in project_dir.iterdir())))

    status = runner.invoke(app, ["project", "status", PROJECT, "--json"])
    assert json.loads(status.output)["state"] == "PROBLEM_FORMULATION"

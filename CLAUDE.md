# AI Research Doctorant

Laboratoire de recherche assisté par IA : transformer un sujet en Research Proposal
argumenté, traçable et reproductible. La spécification complète est dans `specs.md`.

**Avancement : sprint 1 (fondations et veille bibliographique).** Sprints 2 à 4 non implémentés.

## Principe d'architecture

Le LLM prend les décisions scientifiques argumentées ; le code Python
(`src/research_lab/`) prend en charge tout ce qui doit être vérifiable : appels aux APIs,
identifiants, déduplication, persistance, transitions du workflow. Les Skills appellent la
CLI `research-lab` et ne réimplémentent pas sa logique.

## Commandes

Python ≥ 3.12, environnement dans `.venv/` (voir README.md pour l'installation).

```bash
.venv/bin/pytest                    # tests hors réseau
.venv/bin/pytest -m network         # appels réels arXiv / OpenAlex
.venv/bin/research-lab --help       # CLI (project, watch, corpus, search-log)
```

## Organisation

- `.claude/agents/doctorant.md` : agent orchestrateur. `scientific-reviewer.md` : sprint 3.
- `.claude/skills/scientific-watch/` : seul skill implémenté ; les sept autres sont des fichiers vides.
- `config/` : sources académiques, politique de recherche, valeurs, scores.
- `src/research_lab/` : `providers/` (arXiv, OpenAlex), `schemas/` (Pydantic), `validation/`,
  `storage/`, `workflow/` (états et transitions), `corpus.py`, `watch.py`, `cli.py`.
- `research/projects/<id>/` : un dossier par projet (`project.yaml`, `scope.md`,
  `papers.json`, `search-log.json`).
- `tests/unit`, `tests/integration` ; `tests/fixtures` contient des réponses réelles des APIs.

## Règles

- Ne jamais inventer de publication, de citation ou de résultat. Une publication n'existe pour
  un projet que si elle a un identifiant `PAPER-xxx` dans son `papers.json`.
- Ne jamais modifier à la main `project.yaml`, `papers.json` ou `search-log.json` : passer par la CLI.
- Les identifiants `PAPER-xxx`, `SEARCH-xxx` (et plus tard `GAP-xxx`) ne changent jamais.
- Les transitions du workflow sont contrôlées par `workflow/transitions.py` ; les validations
  humaines (Gate 1, Gate 2) ne doivent jamais pouvoir être effectuées par un agent.
- Code : Python typé, modèles Pydantic pour toute donnée persistée, tests pour chaque
  règle déterministe. Ne pas implémenter de fonctionnalité d'un sprint ultérieur sans demande.

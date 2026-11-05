# AI Research Doctorant

Laboratoire de recherche assisté par IA : transformer un sujet en Research Proposal
argumenté, traçable et reproductible. La spécification complète est dans `specs.md`.

**Avancement : sprints 1 et 2 terminés** (base SQLite partagée, état de l'art avec preuves
vérifiées, gaps et alignement sur les valeurs, Gate 1). Sprints 3 et 4 non implémentés.

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
.venv/bin/research-lab --help       # CLI (project, watch, corpus, search-log, db)
```

## Organisation

- `.claude/agents/doctorant.md` : agent orchestrateur. `scientific-reviewer.md` : sprint 3.
- `.claude/skills/` : `scientific-watch`, `literature-review`, `gap-analysis` et `values-alignment`
  implémentés ; les quatre autres sont des fichiers vides.
- `config/` : sources académiques, politique de recherche, valeurs, scores.
- `src/research_lab/` : `providers/` (arXiv, OpenAlex), `schemas/` (Pydantic), `validation/`,
  `storage/` (`database.py` : schéma et migrations ; `repositories.py` : accès et exports),
  `workflow/` (états, transitions et leurs préconditions sur `ProjectFacts` ; `approvals.py` :
  soumission et décision des gates), `corpus.py`,
  `watch.py` (recherche), `fulltext.py` (PDF en accès libre), `review.py` (tri, preuves),
  `gaps.py` (gaps, alignement), `cli.py`.
- `validation/gaps.py` : règles déterministes des gaps (force des preuves, statut `supported`,
  nouveauté) et de l'évaluation au regard des valeurs, calcul des scores de priorité.
- Un gap est un manque scientifique établi par la littérature (spec §4.2) ; les valeurs de
  `research-values.yaml` servent seulement à évaluer et prioriser les gaps, jamais à en créer.
- `validation/evidence.py` : vérifie qu'un extrait cité figure dans le texte (comparaison sur
  lettres et chiffres seulement, pour tolérer les artefacts d'extraction PDF).
- `knowledge/papers/` : PDF et texte extrait page par page (`PAPER-xxx.pages.json`), partagés
  entre projets, non versionnés ; l'empreinte du texte est contrôlée à chaque lecture.
- `knowledge/research.db` : **source de vérité**, partagée entre projets. Les identifiants
  `PAPER-xxx` et `SEARCH-xxx` sont globaux. Toute évolution du schéma passe par une nouvelle
  migration ajoutée à la fin de `_MIGRATIONS` ; ne jamais modifier une migration existante.
- `research/projects/<id>/` : un dossier par projet. `scope.md` est écrit à la main ;
  `project.yaml`, `papers.json`, `search-log.json`, `evidence-matrix.json`, `gaps.json` et
  `alignment.json` sont **régénérés depuis la base** après chaque écriture. `drafts/` contient les
  brouillons JSON écrits par l'agent pour `gap add/revise` et `alignment set`.
- `tests/unit`, `tests/integration` ; `tests/fixtures` contient des réponses réelles des APIs.

## Règles

- Ne jamais inventer de publication, de citation ou de résultat. Une publication n'existe pour
  un projet que si elle a un identifiant `PAPER-xxx` dans son `papers.json`.
- Ne jamais modifier la base ni les fichiers exportés (`project.yaml`, `papers.json`,
  `search-log.json`) autrement que par la CLI.
- Les identifiants `PAPER-xxx`, `SEARCH-xxx`, `EV-xxx` et `GAP-xxx` ne changent jamais.
  Une preuve ne se modifie pas : elle se retire (`evidence withdraw`) et une nouvelle est créée.
  Un gap se révise par une nouvelle version (`gap revise`) ; les versions précédentes sont conservées.
- Les transitions du workflow sont contrôlées par `workflow/transitions.py` ; les validations
  humaines (Gate 1, Gate 2) ne doivent jamais pouvoir être effectuées par un agent : ne jamais
  lancer `gate approve` / `gate revise`, ni appeler `decide_gate_1`, ni contourner le contrôle
  `human_check_failure` (variable `CLAUDECODE`, terminal interactif). Les tests le simulent par monkeypatch.
- Code : Python typé, modèles Pydantic pour toute donnée persistée, tests pour chaque
  règle déterministe. Ne pas implémenter de fonctionnalité d'un sprint ultérieur sans demande.

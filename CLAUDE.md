# AI Research Doctorant

Laboratoire de recherche assisté par IA : transformer un sujet en Research Proposal
argumenté, traçable et reproductible. La spécification complète est dans `specs.md`.

**Avancement : sprints 1 à 4 terminés** : workflow complet, du sujet au Research Proposal validé
à la Gate 2 (base SQLite partagée, preuves vérifiées, gaps et valeurs, Gate 1, questions et
hypothèses, solutions comparées, revue critique indépendante, Proposal, Gate 2). Sprint 4 terminé : reprise (`project resume`), évaluation (`eval`), coûts (`costs`),
non-régression (`tests/regression`), sauvegarde (`db backup`), procédures (`docs/exploitation.md`).

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

- `.claude/agents/doctorant.md` : agent orchestrateur. `scientific-reviewer.md` : reviewer
  indépendant, en lecture seule ; seul auteur des revues (`critique submit`).
- `.claude/skills/` : `scientific-watch`, `literature-review`, `gap-analysis`, `values-alignment`,
  `problem-formulation`, `solution-architect`, `scientific-critic` et `research-writer` : tous implémentés.
- `config/` : sources académiques, politique de recherche, valeurs, scores.
- `src/research_lab/` : `providers/` (arXiv, OpenAlex), `schemas/` (Pydantic), `validation/`,
  `storage/` (`database.py` : schéma et migrations ; `repositories.py` : accès et exports),
  `workflow/` (états, transitions et leurs préconditions sur `ProjectFacts` ; `approvals.py` :
  soumission et décision des gates), `corpus.py`,
  `watch.py` (recherche), `fulltext.py` (PDF en accès libre), `review.py` (tri, preuves),
  `gaps.py` (gaps, alignement), `resume.py` (reprise : `project resume`), `scope.py` (sections numérotées de `scope.md`, raison de tri « §N — justification »), `evaluation.py` (indicateurs `eval report`, notation humaine `eval rate`), `costs.py` (coûts lus dans les transcriptions de Claude Code, `costs report` ; prix dans `config/costs.yaml`), `views.py` et `api.py` (API FastAPI en lecture seule pour l'interface web, `research-lab serve`), `questions.py` (questions et hypothèses), `solutions.py` (solutions et comparaisons), `critique.py` (revue critique, réponses), `proposal.py` et `bibliography.py` (Proposal,
  `references.bib`), `cli.py`. `templates/research-proposal.md` : sections contrôlées par `proposal check`.
- `validation/gaps.py` : règles déterministes des gaps (force des preuves, statut `supported`,
  nouveauté) et de l'évaluation au regard des valeurs, calcul des scores de priorité.
- Un gap est un manque scientifique établi par la littérature (spec §4.2) ; les valeurs de
  `research-values.yaml` servent seulement à évaluer et prioriser les gaps, jamais à en créer.
- `validation/evidence.py` : vérifie qu'un extrait cité figure dans le texte (comparaison sur
  lettres et chiffres seulement, pour tolérer les artefacts d'extraction PDF).
- `reading.py` : couverture de lecture. `fulltext show` affiche un plan, ou des pages (≤ `max_show_chars`
  par appel) qu'il enregistre dans `page_reads` (migration 9) ; le texte principal (jusqu'aux références)
  de chaque incluse doit être affiché en entier (`require_full_reading`), et `evidence add --page N`
  exige que la page l'ait été. Leçons de l'agent researcher d'iexec-openclaw (2026-11-23/24), comme les
  relances longues (`retry.delays_seconds`), les filtres de sources (`categories`, `filters`), les
  recherches plafonnées (`max_examinable_results`) et les recherches contradictoires vides qui ne comptent pas.
- `knowledge/papers/` : PDF et texte extrait page par page (`PAPER-xxx.pages.json`), partagés
  entre projets, non versionnés ; l'empreinte du texte est contrôlée à chaque lecture.
- `knowledge/research.db` : **source de vérité**, partagée entre projets. Les identifiants
  `PAPER-xxx` et `SEARCH-xxx` sont globaux. Toute évolution du schéma passe par une nouvelle
  migration ajoutée à la fin de `_MIGRATIONS` ; ne jamais modifier une migration existante.
- `research/projects/<id>/` : un dossier par projet. `scope.md`, `literature-review.md` et
  `research-proposal.md` sont rédigés par l'agent ; `references.bib` est généré par `proposal references` ;
  `project.yaml`, `papers.json`, `search-log.json`, `evidence-matrix.json`, `gaps.json`,
  `alignment.json`, `gate-1.json`, `gate-2.json`, `research-questions.json`, `solutions.json` et `scientific-review.json` sont **régénérés depuis la base**
  après chaque écriture. `drafts/` contient les brouillons JSON écrits par l'agent pour
  `gap add/revise`, `alignment set`, `question add/revise` et `solution add/revise/compare`.
- `web/` : interface React (Vite, TypeScript), compilée dans `web/dist` (non versionné) et servie par
  `research-lab serve` ; `npm run dev` pour la développer (API sur le port 8765). Elle ne fait que lire :
  aucune décision humaine ni écriture dans la base ne passe par l'interface.
- `tests/unit`, `tests/integration` ; `tests/fixtures` contient des réponses réelles des APIs.
  `tests/regression` : références `golden/` du scénario complet et instantanés `fixtures/snapshot-vN/`
  d'anciennes versions. Ne jamais modifier un instantané ; après un changement voulu des exports,
  `UPDATE_GOLDEN=1 .venv/bin/pytest tests/regression` et relire le diff ; après une migration, ajouter un
  instantané (`REGRESSION_SNAPSHOT=1`).

## Règles

- Ne jamais inventer de publication, de citation ou de résultat. Une publication n'existe pour
  un projet que si elle a un identifiant `PAPER-xxx` dans son `papers.json`.
- Ne jamais modifier la base ni les fichiers exportés (`project.yaml`, `papers.json`,
  `search-log.json`) autrement que par la CLI.
- Les identifiants `PAPER-xxx`, `SEARCH-xxx`, `EV-xxx`, `GAP-xxx`, `RQ-xxx`, `SOL-xxx` et `OBJ-xxx` ne changent jamais.
  Une preuve ne se modifie pas : elle se retire (`evidence withdraw`) et une nouvelle est créée.
  Un gap, une question ou une solution se révise par une nouvelle version (`… revise`) ;
  les versions précédentes sont conservées.
- Les transitions du workflow sont contrôlées par `workflow/transitions.py` (`--force` saute les
  préconditions, sauf vers ou depuis les gates, et reste tracé dans l'historique) ; les validations
  humaines (Gate 1, Gate 2) ne doivent jamais pouvoir être effectuées par un agent : ne jamais
  lancer `gate approve` / `gate revise`, ni appeler `decide_gate_1` / `decide_gate_2`, ni contourner
  le contrôle `human_check_failure` (variable `CLAUDECODE`, terminal interactif). Les tests le simulent
  par monkeypatch. La notation humaine (`eval rate`) suit la même règle : jamais par un agent.
  Les revues critiques sont écrites par l'agent `scientific-reviewer` seul.
- Code : Python typé, modèles Pydantic pour toute donnée persistée, tests pour chaque
  règle déterministe. Ne pas implémenter de fonctionnalité d'un sprint ultérieur sans demande.

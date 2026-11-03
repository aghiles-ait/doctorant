# AI Research Doctorant
## Spécification technique et plan d’implémentation avec Claude Code

**Version :** 1.0  
**Date :** 23 octobre 2026  
**Statut :** Spécification initiale — prête pour implémentation

---

# 1. Vision et objectifs

L’objectif est de construire un **laboratoire de recherche scientifique assisté par IA**, capable de transformer un sujet général en proposition de recherche argumentée, traçable et reproductible.

Le système ne doit pas simplement répondre à une question. Il doit conduire un processus scientifique complet, en capitalisant ses connaissances entre les sessions.

## 1.1 Capacités attendues

L’agent principal, `doctorant`, doit pouvoir :

1. Explorer la littérature scientifique sur des sujets généraux liés à l’intelligence artificielle.
2. Produire un état de l’art structuré et sourcé.
3. Identifier des lacunes scientifiques documentées.
4. Évaluer ces lacunes au regard de valeurs configurables : confidentialité, liberté, souveraineté, gouvernance, décentralisation et vérifiabilité.
5. Formuler des problématiques et des hypothèses falsifiables.
6. Proposer des solutions conceptuelles de haut niveau.
7. Soumettre ses conclusions à un reviewer scientifique indépendant.
8. Générer un **Research Proposal scientifique complet**.

## 1.2 Décisions d’architecture

| Dimension | Décision retenue |
|---|---|
| Périmètre | IA générale : LLM, agents, gouvernance, sécurité, systèmes distribués, etc. |
| Orchestrateur | `doctorant.md` dans Claude Code |
| Autonomie | Hybride, avec deux validations humaines |
| Compétences | Huit Skills spécialisés |
| Revue critique | Sous-agent indépendant `scientific-reviewer.md` |
| Mémoire | Fichiers versionnés et SQLite |
| Sources | arXiv, OpenAlex, Semantic Scholar, Crossref |
| Livrable | Research Proposal scientifique en Markdown |
| Exécution | Locale via Claude Code, avec APIs académiques externes |

## 1.3 Les deux validations humaines

### Gate 1 — Validation de la problématique

Cette validation intervient après :

- La définition du périmètre.
- La recherche bibliographique.
- L’état de l’art.
- L’analyse des gaps.
- Leur priorisation.

L’humain peut choisir une ou plusieurs problématiques, demander des preuves supplémentaires ou réorienter la recherche.

### Gate 2 — Validation du Research Proposal

Cette validation intervient après :

- La formulation des hypothèses.
- La conception des solutions candidates.
- La définition du protocole d’évaluation.
- La revue critique indépendante.
- La rédaction du Research Proposal.

L’humain peut accepter le rapport, demander des corrections ou relancer une investigation ciblée.

**Règle fondamentale :** aucun passage de Gate 1 ou Gate 2 ne peut être effectué automatiquement. Les validations doivent être enregistrées et vérifiées par le workflow, et pas seulement demandées dans un prompt.

---

# 2. Architecture logicielle

L’architecture est organisée en quatre couches.

## 2.1 Orchestration — Claude Code

Responsabilités :

- Coordonner le processus scientifique.
- Sélectionner et appeler les Skills.
- Gérer les états du projet.
- Déclencher les validations humaines.
- Organiser les itérations.
- Consolider les résultats.

Composants :

- `doctorant.md`
- `scientific-reviewer.md`
- Moteur de workflow
- Mécanisme d’approbation

## 2.2 Scientific Skills

Huit compétences spécialisées :

1. `scientific-watch`
2. `literature-review`
3. `gap-analysis`
4. `values-alignment`
5. `problem-formulation`
6. `solution-architect`
7. `scientific-critic`
8. `research-writer`

Chaque Skill est responsable d’une étape scientifique précise et possède un contrat explicite.

## 2.3 Deterministic Tools

Modules Python responsables des opérations vérifiables :

- Connecteurs aux APIs académiques.
- Validation des identifiants bibliographiques.
- Déduplication.
- Extraction et normalisation des métadonnées.
- Validation des schémas.
- Calcul des scores.
- Gestion de la persistance.
- Contrôle des transitions du workflow.

**Principe :** le LLM prend les décisions scientifiques argumentées ; les scripts prennent en charge les opérations déterministes.

## 2.4 Research Knowledge Layer

Couche de connaissances persistantes :

- Publications.
- Métadonnées bibliographiques.
- Matrices de preuves.
- Gaps.
- Hypothèses.
- Questions de recherche.
- Solutions proposées.
- Historique des décisions.
- Versions des artefacts.

Technologies initiales :

- SQLite.
- Markdown.
- JSON.
- Git.

## 2.5 Research Artifacts

Livrables générés :

- Research Scope.
- Literature Review.
- Evidence Matrix.
- Gap Analysis.
- Research Questions.
- Solution Overview.
- Scientific Review.
- Research Proposal.
- Bibliographie BibTeX.
- Journal d’audit.

---

# 3. Structure du dépôt

```text
ai-research-doctorant/
├── CLAUDE.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── .claude/
│   ├── agents/
│   │   ├── doctorant.md
│   │   └── scientific-reviewer.md
│   ├── skills/
│   │   ├── scientific-watch/SKILL.md
│   │   ├── literature-review/SKILL.md
│   │   ├── gap-analysis/SKILL.md
│   │   ├── values-alignment/SKILL.md
│   │   ├── problem-formulation/SKILL.md
│   │   ├── solution-architect/SKILL.md
│   │   ├── scientific-critic/SKILL.md
│   │   └── research-writer/SKILL.md
│   └── settings.json
│
├── config/
│   ├── research-values.yaml
│   ├── research-policy.yaml
│   ├── academic-sources.yaml
│   └── scoring.yaml
│
├── src/research_lab/
│   ├── cli.py
│   ├── workflow/
│   │   ├── state.py
│   │   ├── transitions.py
│   │   └── approvals.py
│   ├── providers/
│   │   ├── arxiv.py
│   │   ├── openalex.py
│   │   ├── semantic_scholar.py
│   │   └── crossref.py
│   ├── storage/
│   │   ├── database.py
│   │   └── repositories.py
│   ├── schemas/
│   └── validation/
│       ├── references.py
│       ├── evidence.py
│       └── outputs.py
│
├── knowledge/
│   ├── papers/
│   └── research.db
│
├── research/
│   └── projects/
│       └── <project-id>/
│           ├── project.yaml
│           ├── scope.md
│           ├── literature-review.md
│           ├── evidence-matrix.json
│           ├── gaps.json
│           ├── gate-1.json
│           ├── research-questions.md
│           ├── solution-overview.md
│           ├── scientific-review.md
│           ├── gate-2.json
│           ├── research-proposal.md
│           └── references.bib
│
├── templates/
│   ├── research-proposal.md
│   └── gap-record.json
│
└── tests/
    ├── unit/
    ├── integration/
    └── evaluation/
```

Les fichiers `SKILL.md` utilisent le mécanisme natif de Claude Code. Les modules Python exposent des commandes que les Skills peuvent appeler, sans dupliquer leur logique.

---

# 4. Contrats des huit Skills

Chaque Skill doit respecter un contrat standardisé.

**Input :** références aux artefacts nécessaires, configuration et contexte.

**Process :** étapes reproductibles et règles scientifiques.

**Output :** artefacts structurés validables.

**Quality gates :** critères permettant d’accepter ou de rejeter le résultat.

**Failure behavior :** comportement en cas de données insuffisantes ou d’erreur.

Les schémas Pydantic sont recommandés pour valider les sorties structurées.

## 4.1 Matrice des contrats

| Skill | Entrées | Sorties | Condition de réussite |
|---|---|---|---|
| `scientific-watch` | Sujet, mots-clés, période, sources | `papers.json`, `search-log.json` | Provenance vérifiable, doublons éliminés |
| `literature-review` | Corpus sélectionné, questions initiales | `literature-review.md`, `evidence-matrix.json` | Affirmations reliées aux sources |
| `gap-analysis` | État de l’art, matrice de preuves | `gaps.json` | Chaque gap documenté et contestable |
| `values-alignment` | Gaps, `research-values.yaml` | `alignment.json` | Compromis et justifications explicites |
| `problem-formulation` | Gaps approuvés, contraintes | `research-questions.json` | Hypothèses falsifiables |
| `solution-architect` | Questions, hypothèses, état de l’art | `solutions.json` | Plusieurs alternatives comparées |
| `scientific-critic` | Résultats, références, propositions | `scientific-review.json` | Objections et vérifications indépendantes |
| `research-writer` | Tous les artefacts validés | `research-proposal.md`, `references.bib` | Rapport cohérent, citations vérifiées |

## 4.2 Exemple de contrat : `gap-analysis`

```yaml
name: gap-analysis
version: "1.0"

input:
  required:
    - literature_review_path
    - evidence_matrix_path
    - research_scope_path

output:
  path: gaps.json
  schema: GapAnalysisResult

process:
  - Extract unresolved research questions
  - Identify conflicting experimental results
  - Identify missing evaluations
  - Compare competing approaches
  - Search for potential counterexamples
  - Classify evidence strength
  - Produce gap candidates

quality_rules:
  - Every gap must cite supporting evidence
  - Separate observations from hypotheses
  - Report contradictory evidence
  - Never infer novelty from absence in a small corpus
  - Mark insufficiently supported gaps as candidates

failure:
  insufficient_evidence: NEEDS_MORE_RESEARCH
  invalid_citations: BLOCKED
```

## 4.3 Modèle de données d’un gap

```json
{
  "gap_id": "GAP-001",
  "title": "Verifiable decentralized agent governance",
  "description": "Research gap candidate",
  "category": "unresolved_research_question",
  "status": "candidate",
  "supporting_papers": ["PAPER-001", "PAPER-002"],
  "contradicting_papers": [],
  "evidence_strength": "medium",
  "novelty_assessment": "unverified",
  "open_questions": [
    "Can governance policies be verified without a trusted coordinator?"
  ],
  "limitations": [
    "The literature search may be incomplete"
  ]
}
```

L’identifiant `GAP-001` ne doit pas changer lorsqu’une nouvelle publication apparaît.

Le système ajoute des preuves, réévalue le statut et conserve l’historique des modifications.

---

# 5. Configuration des valeurs scientifiques

La recherche doit rester ouverte à l’ensemble de l’IA.

Les valeurs interviennent principalement lors de l’évaluation et de la priorisation des opportunités, et non comme un filtre éliminant prématurément des publications.

## 5.1 Fichier `research-values.yaml`

```yaml
version: "1.0"

values:
  privacy:
    description: >
      Minimize unauthorized disclosure of sensitive data,
      model inputs, outputs and intermediate computations.
    weight: 1.0

  freedom:
    description: >
      Preserve user autonomy, portability and freedom
      to choose or replace AI systems.
    weight: 1.0

  sovereignty:
    description: >
      Preserve meaningful control over data,
      infrastructure and AI execution.
    weight: 1.0

  governance:
    description: >
      Support transparent, accountable and
      contestable governance mechanisms.
    weight: 1.0

  decentralization:
    description: >
      Reduce unnecessary trusted intermediaries
      and single points of control.
    weight: 1.0

  verifiability:
    description: >
      Enable independent verification of
      important system properties.
    weight: 1.0

evaluation:
  scale: [0, 1, 2, 3, 4, 5]
  require_justification: true
  report_tradeoffs: true
  allow_not_applicable: true
```

Les poids sont initialement égaux.

Ils pourront être adaptés après quelques projets, à partir de décisions humaines explicites.

---

# 6. Moteur de workflow et validations

Le workflow doit être persistant.

Si Claude Code est interrompu, l’exécution doit reprendre à partir du dernier état validé, sans relancer systématiquement toute la recherche.

## 6.1 États du workflow

```text
NEW
  ↓
SCOPING
  ↓
LITERATURE_SEARCH
  ↓
LITERATURE_REVIEW
  ↓
GAP_ANALYSIS
  ↓
AWAITING_GATE_1
  ├── Approve → PROBLEM_FORMULATION
  └── Revise  → LITERATURE_SEARCH
                    ↓
              SOLUTION_DESIGN
                    ↓
              SCIENTIFIC_REVIEW
                ├── Critical issues → SOLUTION_DESIGN
                └── Acceptable      → PROPOSAL_DRAFT
                                           ↓
                                     AWAITING_GATE_2
                                       ├── Approve → COMPLETED
                                       └── Revise  → SOLUTION_DESIGN
```

Les transitions doivent être contrôlées par Python.

Claude peut proposer une transition, mais le programme vérifie les préconditions.

## 6.2 Exemple de logique Python

```python
from enum import StrEnum

class ResearchState(StrEnum):
    NEW = "NEW"
    SCOPING = "SCOPING"
    LITERATURE_SEARCH = "LITERATURE_SEARCH"
    LITERATURE_REVIEW = "LITERATURE_REVIEW"
    GAP_ANALYSIS = "GAP_ANALYSIS"
    AWAITING_GATE_1 = "AWAITING_GATE_1"
    PROBLEM_FORMULATION = "PROBLEM_FORMULATION"
    SOLUTION_DESIGN = "SOLUTION_DESIGN"
    SCIENTIFIC_REVIEW = "SCIENTIFIC_REVIEW"
    PROPOSAL_DRAFT = "PROPOSAL_DRAFT"
    AWAITING_GATE_2 = "AWAITING_GATE_2"
    COMPLETED = "COMPLETED"

def approve_gate(project, gate, approver, decision):
    assert gate in ("gate_1", "gate_2")
    assert decision in ("approve", "revise", "reject")
    assert approver != "ai-agent"

    expected = (
        ResearchState.AWAITING_GATE_1
        if gate == "gate_1"
        else ResearchState.AWAITING_GATE_2
    )

    if project.state != expected:
        raise ValueError("Project is not awaiting this gate")

    # Persist approval, reviewer, timestamp and
    # immutable artifact hashes in one transaction.
    return record_approval(project, gate, approver, decision)
```

Dans l’implémentation réelle, `record_approval` devra être transactionnel, enregistrer l’identité du validateur et vérifier les empreintes des artefacts.

Une réponse générée par l’agent ne doit jamais pouvoir se substituer à une approbation humaine.

---

# 7. Schéma de données minimal

Six entités principales sont prévues.

| Entité | Champs essentiels |
|---|---|
| `Paper` | ID, titre, auteurs, DOI, arXiv ID, date, statut, URL |
| `Evidence` | ID, paper ID, claim, passage, localisation, type de preuve |
| `Gap` | ID, description, statut, evidence IDs, objections |
| `ResearchQuestion` | ID, gap IDs, question, hypothèses, métriques |
| `Solution` | ID, question ID, architecture, compromis, risques |
| `ResearchRun` | ID, sujet, état, configuration, horodatages, validations |

Deux tables supplémentaires sont recommandées :

- `SearchExecution`, pour tracer les recherches bibliographiques.
- `ArtifactVersion`, pour conserver l’historique des livrables.

Les relations sont essentielles : une affirmation du rapport doit pouvoir être remontée jusqu’à un élément de preuve et à une publication identifiable.

---

# 8. Politique de qualité scientifique

Cinq contrôles sont obligatoires.

## Q1 — Validité bibliographique

Vérifier que les références existent et que leurs métadonnées correspondent.

Un DOI valide ne prouve pas que l’article soutient l’affirmation citée.

## Q2 — Traçabilité des affirmations

Toute affirmation scientifique substantielle doit être associée à une preuve localisable, avec page, section ou extrait lorsque disponible.

## Q3 — Recherche contradictoire

Pour chaque gap prioritaire, effectuer une recherche dédiée aux travaux qui pourraient déjà le résoudre.

## Q4 — Falsifiabilité

Les hypothèses doivent conduire à des observations ou expériences susceptibles de les réfuter.

## Q5 — Transparence des limites

Le rapport doit indiquer :

- Les bases consultées.
- Les requêtes utilisées.
- Les dates des recherches.
- Les critères de sélection.
- Les limites du corpus.

Le reviewer indépendant doit pouvoir conclure `MAJOR_REVISION` ou `INSUFFICIENT_EVIDENCE`.

Il ne doit pas être obligé d’approuver une proposition.

---

# 9. Plan d’implémentation avec Claude Code

L’implémentation est organisée en quatre sprints.

Chaque sprint doit produire un résultat fonctionnel et testable.

## Sprint 1 — Fondations et veille bibliographique

**Estimation : 2 à 3 jours de développement.**

Travaux :

1. Initialiser le dépôt.
2. Configurer Claude Code.
3. Créer `doctorant.md`.
4. Intégrer les sources académiques.
5. Implémenter `scientific-watch`.
6. Créer les premiers schémas de données.
7. Ajouter les tests initiaux.

**Livrable :** rechercher un sujet et constituer un corpus traçable de publications, avec métadonnées et historique des requêtes.

## Sprint 2 — Raisonnement scientifique

**Estimation : 3 à 5 jours.**

Travaux :

1. Développer `literature-review`.
2. Développer `gap-analysis`.
3. Développer `values-alignment`.
4. Ajouter la matrice de preuves.
5. Implémenter la mémoire SQLite.
6. Implémenter Gate 1.

**Livrable :** état de l’art structuré, gaps argumentés et sélection humaine des problématiques.

## Sprint 3 — Conception et publication

**Estimation : 3 à 4 jours.**

Travaux :

1. Développer `problem-formulation`.
2. Développer `solution-architect`.
3. Développer `scientific-critic`.
4. Développer `research-writer`.
5. Intégrer le reviewer indépendant.
6. Implémenter Gate 2.

**Livrable :** premier Research Proposal complet, revu et soumis à validation humaine.

## Sprint 4 — Robustesse et évaluation

**Estimation : 3 à 5 jours.**

Travaux :

1. Ajouter les tests automatisés.
2. Tester les scénarios de reprise.
3. Mettre en place des évaluations de qualité scientifique.
4. Ajouter le suivi des coûts.
5. Ajouter les tests de non-régression.
6. Documenter les procédures d’exploitation.

**Livrable :** MVP reproductible, testable et documenté.

## Estimation globale

**11 à 17 jours de développement**, hors temps de revue scientifique humaine.

Cette estimation suppose un développeur familiarisé avec Python et Claude Code, ainsi que des intégrations API relativement simples.

---

# 10. Pilotage de Claude Code

Il est déconseillé de demander à Claude Code de construire l’ensemble du projet en une seule requête.

L’approche recommandée consiste à travailler par sessions courtes, avec des critères d’acceptation explicites.

## 10.1 Prompt initial pour Claude Code

```text
Tu es un architecte logiciel senior spécialisé en systèmes
agentiques, Claude Code, Python et workflows de recherche
scientifique.

Je souhaite construire un projet nommé `ai-research-doctorant`.

OBJECTIF

Créer un agent scientifique autonome appelé `doctorant`,
capable de :

1. Explorer la littérature scientifique sur des sujets
   généraux liés à l'IA.
2. Produire un état de l'art structuré et sourcé.
3. Identifier des gaps scientifiques documentés.
4. Évaluer ces gaps au regard de valeurs configurables :
   confidentialité, liberté, souveraineté, gouvernance,
   décentralisation et vérifiabilité.
5. Formuler des problématiques et hypothèses falsifiables.
6. Proposer des solutions conceptuelles haut niveau.
7. Faire critiquer ses conclusions par un reviewer indépendant.
8. Générer un Research Proposal scientifique complet.

ARCHITECTURE IMPOSÉE

- Claude Code comme environnement d'orchestration.
- `.claude/agents/doctorant.md` comme agent principal.
- `.claude/agents/scientific-reviewer.md` comme reviewer.
- Huit Skills natifs dans `.claude/skills/`.
- Python 3.12+ avec typage et Pydantic.
- SQLite pour les métadonnées et l'état persistant.
- Markdown, JSON et BibTeX pour les artefacts.
- APIs académiques pour les publications.
- Deux validations humaines obligatoires et persistantes.

CONTRAINTES SCIENTIFIQUES

- Ne jamais inventer de publications ou citations.
- Distinguer faits, interprétations et hypothèses.
- Vérifier les références bibliographiques.
- Associer les affirmations à des preuves.
- Rechercher les travaux contradictoires.
- Ne jamais présenter un gap comme inédit sans recherche
  de nouveauté documentée.
- Préserver la traçabilité et la reproductibilité.

MISSION IMMÉDIATE : SPRINT 1 UNIQUEMENT

1. Proposer la structure détaillée du dépôt.
2. Créer `CLAUDE.md` et `doctorant.md`.
3. Créer les fichiers de configuration initiaux.
4. Implémenter les connecteurs arXiv et OpenAlex.
5. Implémenter le Skill `scientific-watch`.
6. Définir les modèles Pydantic pour les publications
   et les résultats de recherche.
7. Ajouter des tests unitaires et d'intégration.
8. Documenter les commandes de lancement.

MÉTHODE DE TRAVAIL

Avant d'écrire le code, présente le plan d'implémentation
du Sprint 1 et les critères d'acceptation.

Après validation du plan, implémente progressivement.

N'implémente pas les Sprints 2 à 4.

Utilise les conventions natives de la version installée
de Claude Code.

À la fin, exécute les tests disponibles, indique leurs
résultats réels et documente les fonctionnalités non
encore implémentées.
```

---

# 11. Critères d’acceptation du MVP

Les objectifs suivants doivent être définis avant le développement.

| Critère | Cible MVP |
|---|---|
| Références bibliographiques inventées | 0 dans les corpus de test |
| Métadonnées des publications | Identifiant et provenance pour 100 % des entrées retenues |
| Traçabilité | Chaque gap possède des références explicites |
| Workflow | Impossible de contourner les deux validations |
| Résilience | Reprise après interruption sans perte des validations |
| Reproductibilité | Requêtes, dates, configurations et versions conservées |
| Évaluation scientifique | Revue humaine sur au moins trois sujets distincts |

La qualité des gaps et des hypothèses devra être évaluée par un humain.

Il serait trompeur de prétendre mesurer entièrement la nouveauté scientifique avec un score automatisé.

---

# 12. Évolutions après le MVP

## 12.1 Veille scientifique continue

Relancer périodiquement les recherches, comparer les nouveaux articles au corpus existant et signaler les gaps dont le statut pourrait changer.

## 12.2 Graphe de connaissances scientifiques

Relier :

- Publications.
- Méthodes.
- Résultats.
- Contradictions.
- Gaps.
- Hypothèses.

Cette structure faciliterait la découverte de liens interdisciplinaires.

## 12.3 Validation expérimentale

Ajouter ultérieurement un agent capable de proposer :

- Des benchmarks.
- Des protocoles expérimentaux.
- Des preuves de concept isolées.
- Des analyses de résultats.

Toute exécution expérimentale significative resterait soumise à autorisation humaine.

---

# 13. Recommandation finale

Pour ce projet, la priorité doit être donnée à **la rigueur scientifique avant la complexité agentique**.

Le véritable avantage compétitif ne viendra pas du nombre d’agents ou de Skills, mais de la capacité du système à :

1. Capitaliser les connaissances scientifiques au fil du temps.
2. Distinguer une lacune scientifique réelle d’une simple préférence architecturale.
3. Justifier chaque problématique par des preuves vérifiables.
4. Réviser ses conclusions lorsque de nouveaux travaux apparaissent.
5. Produire des propositions de recherche que des chercheurs humains peuvent examiner sérieusement.

**La première étape concrète est le Sprint 1 : obtenir un `doctorant` capable de découvrir, qualifier, enregistrer et retrouver des publications scientifiques de manière fiable.**

Tout le raisonnement ultérieur dépendra de la qualité de cette fondation.
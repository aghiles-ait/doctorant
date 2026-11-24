---
name: solution-architect
description: Conception des solutions. Pour chaque question de recherche RQ-xxx, propose plusieurs solutions conceptuelles SOL-xxx (architecture, hypothèses testées, protocole d'évaluation, compromis, risques, preuves EV-xxx), puis les compare critère par critère. À utiliser quand un projet est à l'état SOLUTION_DESIGN.
allowed-tools: Read, Write(research/projects/*/drafts/*), Edit(research/projects/*/drafts/*), Bash(.venv/bin/research-lab *)
---

# solution-architect — contrat v1.0

Une solution est une **réponse conceptuelle de haut niveau** à une question de recherche : une
architecture qui permettrait de tester ses hypothèses, pas une implémentation. Chaque question
reçoit **plusieurs alternatives**, comparées explicitement (spec §4.1). Recommander une solution
est permis, choisir ne l'est pas : le choix revient à l'humain à la Gate 2.

Tout passe par `.venv/bin/research-lab`. Les seuls fichiers que tu écris sont des brouillons JSON
dans `research/projects/<id>/drafts/`. `solutions.json` est régénéré depuis la base : ne jamais le modifier.

## Input

- Projet à l'état `SOLUTION_DESIGN` (`project status <id>`).
- Questions et hypothèses : `question list <id>`, `question show <id> RQ-xxx`.
- État de l'art et preuves : `literature-review.md`, `evidence list <id> --json` (méthodes, approches
  concurrentes, limites reconnues) ; `alignment.json` (compromis entre valeurs des gaps retenus).
- Après une revue critique ou une Gate 2 : les objections et commentaires à traiter.

## Process

1. **Pour chaque question active**, identifier au moins deux approches réellement différentes
   (`solution_design.min_solution_alternatives` dans `config/research-policy.yaml`), en partant des
   approches concurrentes de l'état de l'art. Deux variantes d'un même paramètre ne sont pas deux
   alternatives.

2. **Écrire chaque solution** `research/projects/<id>/drafts/solution-<nom>.json` :
   ```json
   {
     "title": "…",
     "question_id": "RQ-001",
     "summary": "…",
     "architecture": "Composants, flux, acteurs de confiance…",
     "addressed_hypotheses": ["H1", "H2"],
     "evaluation_plan": "Protocole : dispositif, données, métriques des hypothèses, ce qui réfuterait…",
     "tradeoffs": ["… contre …"],
     "risks": ["…"],
     "evidence": ["EV-012", "EV-031"],
     "limitations": ["…"]
   }
   ```
   puis `.venv/bin/research-lab solution add <id> --file research/projects/<id>/drafts/solution-<nom>.json`.
   - `addressed_hypotheses` : hypothèses de la question que la solution permet de tester ;
   - `evaluation_plan` : reprend les métriques et le critère de réfutation des hypothèses ;
   - `evidence` : les travaux sur lesquels la solution s'appuie (méthodes, résultats, limites).
     Ce qui n'est appuyé par aucune preuve est présenté comme une conjecture, dans `summary` ou `limitations`.

3. **Comparer** les solutions de chaque question, `drafts/comparison-RQ-xxx.json` :
   ```json
   {
     "question_id": "RQ-001",
     "criteria": ["vérifiabilité", "coût de calcul", "dépendance à un tiers de confiance"],
     "assessments": {
       "SOL-001": {"vérifiabilité": "…", "coût de calcul": "…", "dépendance à un tiers de confiance": "…"},
       "SOL-002": {"vérifiabilité": "…", "coût de calcul": "…", "dépendance à un tiers de confiance": "…"}
     },
     "recommendation": "SOL-001",
     "justification": "…"
   }
   ```
   puis `.venv/bin/research-lab solution compare <id> --file …`.
   Au moins deux critères ; toutes les solutions actives de la question, sur tous les critères.
   Les critères viennent de la question (métriques des hypothèses) et des valeurs (`research-values.yaml`).
   `recommendation: null` si aucune solution ne domine : le dire dans `justification`.

4. **Réviser** : `solution revise <id> SOL-xxx --file … --reason "…"`. Toute révision, ajout ou
   retrait (`"status": "withdrawn"`) rend la comparaison périmée : la refaire.

5. **Contrôler et clore** : `.venv/bin/research-lab solution check <id>` jusqu'à `OK`, traiter ou
   expliquer les avertissements (hypothèse testée par aucune solution), puis
   `.venv/bin/research-lab project transition <id> SCIENTIFIC_REVIEW`.

## Output

- Solutions `SOL-xxx` et comparaisons versionnées dans la base ; `research/projects/<id>/solutions.json`
  (généré) : par question, ses solutions, les publications citées et la comparaison.

Compte rendu : par question, les alternatives, la comparaison (critères, recommandation et sa
justification), les principaux risques et compromis, les hypothèses mal couvertes.

## Quality gates

- Chaque question active a au moins deux solutions actives, toutes comparées sur au moins deux critères.
- Chaque solution cite des hypothèses de sa question et des preuves actives ; compromis et risques explicites.
- `solution check` renvoie `OK`.

## Failure behavior

| Situation | Comportement |
|---|---|
| Solution refusée (question, hypothèse ou preuve inconnue) | Corriger selon le message. |
| Une seule approche crédible dans l'état de l'art | Le dire ; proposer quand même une alternative contrastée (approche de référence, approche minimale) et en exposer les faiblesses, sans la présenter comme équivalente. |
| Aucune solution ne permet de tester une hypothèse | Le signaler (avertissement de `solution check`) ; ne pas l'inscrire dans `addressed_hypotheses` pour faire disparaître l'avertissement. |
| Solution reposant sur des travaux hors corpus | Ne pas les citer comme preuves ; la présenter comme conjecture et le noter dans `limitations`. |

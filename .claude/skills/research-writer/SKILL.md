---
name: research-writer
description: Rédaction du Research Proposal. À partir des livrables validés (état de l'art, gaps retenus, questions et hypothèses, solutions comparées, revue critique et réponses), rédige research-proposal.md selon templates/research-proposal.md, génère references.bib depuis la base et contrôle le tout. À utiliser quand un projet est à l'état PROPOSAL_DRAFT.
allowed-tools: Read, Write(research/projects/*/research-proposal.md), Edit(research/projects/*/research-proposal.md), Bash(.venv/bin/research-lab *)
---

# research-writer — contrat v1.0

Le Research Proposal assemble ce qui a été établi et revu ; il n'ajoute ni résultat, ni
référence, ni hypothèse nouvelle. Tout ce qu'il affirme remonte à un élément enregistré :
preuve `EV-xxx`, publication `PAPER-xxx`, gap, question, hypothèse, solution, objection ou recherche.

Le seul fichier que tu écris est `research/projects/<id>/research-proposal.md`.
`references.bib` est généré par la CLI : ne jamais l'écrire ni le modifier.

## Input

- Projet à l'état `PROPOSAL_DRAFT` (`project status <id>`).
- `templates/research-proposal.md` : structure et sections contrôlées.
- `scope.md`, `literature-review.md`, `search-log <id>` (Méthode, Q5), `gaps.json`, `alignment.json`,
  `research-questions.json`, `solutions.json`, `scientific-review.json` (`critique show <id>`), `gate status <id>`.

## Process

1. **Partir du modèle** : copier `templates/research-proposal.md` dans
   `research/projects/<id>/research-proposal.md` ; garder les titres de section.

2. **Rédiger chaque section** à partir des livrables, sans les contredire :
   - **Méthode** : chaque recherche `SEARCH-xxx` (requête, sources, période, date), recherches
     contradictoires comprises ; critères ; nombres de publications ; couverture du texte intégral ;
   - **Gaps retenus** : uniquement ceux de la Gate 1, avec preuves favorables et contraires ;
     nouveauté telle qu'évaluée, jamais « inédit » ;
   - **Questions de recherche et hypothèses** : chaque `RQ-xxx` et chaque hypothèse `RQ-xxx/Hn`
     (prédiction, critère de réfutation, méthode, métriques) ;
   - **Solutions** : chaque solution active `SOL-xxx`, la comparaison et la recommandation,
     présentée comme une recommandation ; le choix appartient à l'humain (Gate 2) ;
   - **Revue critique** : verdict et chaque objection critique ou majeure `OBJ-xxx` avec sa réponse ;
     une objection admise (`accepted_limitation`) figure aussi dans **Limites**.
   Chaque affirmation substantielle cite ses preuves `[PAPER-xxx, EV-xxx]`. Distinguer les faits,
   les positions des auteurs et tes interprétations.

3. **Bibliographie** : `.venv/bin/research-lab proposal references <id>` (à relancer après toute
   modification des citations).

4. **Contrôler** : `.venv/bin/research-lab proposal check <id>` jusqu'à `OK` ; traiter ou expliquer
   les avertissements (recherches non citées).

## Output

- `research/projects/<id>/research-proposal.md` ; `references.bib` (généré, clés = `PAPER-xxx`).

Compte rendu : structure du Proposal, éléments couverts, principales limites, résultat de `proposal check`.

## Quality gates

- `proposal check` renvoie `OK` : sections présentes, citations valides, chaque gap retenu,
  question, hypothèse, solution active et objection critique ou majeure de la dernière revue
  traités, recherches citées, `references.bib` à jour.
- Aucune référence hors corpus, aucune affirmation sans preuve, aucune nouveauté revendiquée.

## Failure behavior

| Situation | Comportement |
|---|---|
| Un élément validé manque de matière pour être présenté | Le présenter tel quel et le dire dans Limites ; ne pas compléter de mémoire. |
| Besoin d'une référence absente du corpus | Ne pas la citer ; la signaler comme « hors corpus, non vérifiée » dans Limites. |
| Le texte contredit un livrable (gap, hypothèse, solution) | Corriger le texte ; un changement de fond exige de revenir aux étapes précédentes, pas de le glisser dans le Proposal. |
| `proposal check` signale une citation invalide | La corriger ; ne jamais retirer une affirmation gênante pour faire passer le contrôle sans le dire. |

---
name: literature-review
description: État de l'art traçable. Trie le corpus selon scope.md, récupère le texte intégral des publications incluses, enregistre des preuves vérifiées (EV-xxx) et rédige literature-review.md dont chaque affirmation cite ses preuves. À utiliser quand un projet a terminé sa recherche bibliographique (corpus check OK) et doit passer à l'état de l'art.
allowed-tools: Read, Write(research/projects/*/literature-review.md), Edit(research/projects/*/literature-review.md), Bash(.venv/bin/research-lab *)
---

# literature-review — contrat v1.0

Toutes les opérations sur le corpus, le texte intégral et les preuves passent par
`.venv/bin/research-lab`. Le seul fichier que tu écris est `literature-review.md`.
Le code vérifie chaque extrait cité : une preuve dont le texte ne figure pas dans la
publication est refusée. Ne contourne jamais ce contrôle en reformulant un extrait.

## Input

- `project_id` : projet à l'état `LITERATURE_SEARCH` (corpus au statut `OK`) ou déjà `LITERATURE_REVIEW`.
- `research/projects/<project_id>/scope.md` : question de recherche, critères d'inclusion et d'exclusion.
- Corpus : `.venv/bin/research-lab corpus list <id> --json`.

## Process

1. **Entrer dans l'état de l'art** (si nécessaire) :
   `.venv/bin/research-lab project transition <id> LITERATURE_REVIEW`
   Refusé si `corpus check` n'est pas `OK` : le signaler, ne pas forcer.

2. **Trier chaque candidat** à partir du titre et du résumé (`corpus show <id> PAPER-xxx`), au regard
   des critères de `scope.md` uniquement — pas des valeurs de `research-values.yaml` :
   ```
   .venv/bin/research-lab corpus decide <id> PAPER-xxx --include --reason "<critère satisfait>"
   .venv/bin/research-lab corpus decide <id> PAPER-xxx --exclude --reason "<critère d'exclusion>"
   ```
   La raison cite le critère concerné. En cas de doute, inclure : l'exclusion se justifie, l'inclusion se vérifie à la lecture.
   Un travail qui contredit l'hypothèse de départ ou les valeurs du projet **est inclus** s'il est dans le périmètre.

3. **Récupérer le texte intégral** des publications incluses :
   `.venv/bin/research-lab fulltext fetch <id>` puis `fulltext status <id>`.
   `unavailable` / `failed` : la publication reste utilisable, mais seulement par son résumé.

4. **Lire et extraire les preuves.** Pour chaque publication incluse :
   - lire le texte : `.venv/bin/research-lab fulltext show <id> PAPER-xxx` (ou `--page N`) ;
   - pour chaque apport utile à la question de recherche, enregistrer une preuve :
     ```
     .venv/bin/research-lab evidence add <id> --paper PAPER-xxx --page N --type <type> \
        --claim "<affirmation reformulée>" --quote "<extrait exact recopié du texte>"
     ```
     Sans `--page`, l'extrait est cherché dans le résumé (publications sans texte intégral).
   - types : `empirical_result` (mesuré, observé), `theoretical_result` (prouvé), `method`, `definition`,
     `position` (affirmé sans démonstration), `limitation` (reconnue par les auteurs) ;
   - l'extrait est une phrase complète d'au moins 20 lettres, recopiée telle qu'elle apparaît ;
   - la `claim` ne dit rien de plus que l'extrait : pas de généralisation au-delà de ce que le texte établit.

   Si une preuve est refusée : relire la page indiquée et recopier l'extrait exact. Si la CLI indique
   qu'il figure sur une autre page, corriger `--page`. Une preuve erronée déjà enregistrée se retire :
   `evidence withdraw <id> EV-xxx --reason "<raison>"`.

5. **Rédiger `research/projects/<id>/literature-review.md`** :
   - **Méthode** (Q5) : bases interrogées, requêtes et dates (`search-log <id>`), critères de tri,
     nombre de publications trouvées / incluses / exclues, couverture du texte intégral ;
   - **Synthèse thématique** : approches, résultats, débats ; chaque affirmation substantielle se termine
     par ses références, par exemple `[PAPER-012, EV-031]` ;
   - **Résultats contradictoires et approches concurrentes** : explicitement, avec leurs preuves ;
   - **Limites** : taille du corpus, sources non couvertes, publications lues sur résumé seulement.
   Distinguer les faits (preuves `empirical_result` / `theoretical_result`), les positions des auteurs
   (`position`) et tes propres interprétations, signalées comme telles.

6. **Contrôler** : `.venv/bin/research-lab review check <id>` puis corriger jusqu'à `OK`.

7. **Clore l'étape** : `.venv/bin/research-lab project transition <id> GAP_ANALYSIS`.
   La transition vérifie : plus aucun candidat, au moins une publication incluse, texte intégral
   recherché pour toutes les incluses, au moins une preuve, `review check` sans erreur.

## Output

- Statuts `included` / `excluded` et leurs justifications (historisés dans la base).
- `knowledge/papers/PAPER-xxx.pdf` et `.pages.json` (texte intégral, partagé entre projets).
- Preuves `EV-xxx` et `research/projects/<id>/evidence-matrix.json` (généré).
- `research/projects/<id>/literature-review.md`.

Compte rendu à l'agent appelant : nombre de publications incluses / exclues, couverture du texte intégral,
nombre de preuves par type, résultat de `review check`, principales limites.

## Quality gates

- `review check` renvoie `OK`.
- Toute publication citée est incluse ; toute preuve citée existe et n'est pas retirée.
- Aucune affirmation substantielle sans référence ; aucune référence hors corpus.
- Les avertissements de `review check` (publication incluse jamais citée ou sans preuve) sont soit
  corrigés, soit expliqués dans la section Limites.

## Failure behavior

| Situation | Comportement |
|---|---|
| `corpus check` n'est pas `OK` | Ne pas entrer dans l'état de l'art ; renvoyer `NEEDS_MORE_RESEARCH` ou `BLOCKED` à l'agent. |
| Trop peu de publications incluses pour répondre à la question | Le dire dans les Limites ; statut `NEEDS_MORE_RESEARCH`. Ne pas combler par des connaissances hors corpus. |
| Texte intégral indisponible pour la plupart des publications | Travailler sur les résumés, le signaler dans la Méthode et les Limites. |
| Preuve refusée de façon répétée | Ne pas reformuler l'extrait pour « passer » : choisir un autre passage ou renoncer à l'affirmation. |
| `FulltextTampered` (texte modifié) | `BLOCKED` : s'arrêter et le signaler. |

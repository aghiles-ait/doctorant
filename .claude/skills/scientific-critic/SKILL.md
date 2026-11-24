---
name: scientific-critic
description: Revue critique indépendante. Examine le raisonnement d'un projet (gaps retenus, questions, hypothèses falsifiables, solutions, preuves EV-xxx), relit un échantillon de preuves dans le texte des publications, formule des objections OBJ-xxx classées par gravité et rend un verdict (ACCEPTABLE, MAJOR_REVISION, INSUFFICIENT_EVIDENCE). Réservé à l'agent scientific-reviewer, à l'état SCIENTIFIC_REVIEW.
allowed-tools: Read, Bash(.venv/bin/research-lab *)
---

# scientific-critic — contrat v1.0

La revue porte sur le **raisonnement complet** avant la rédaction du Research Proposal : des gaps
retenus à la Gate 1 jusqu'aux solutions, et sur les preuves qui le soutiennent (« résultats,
références, propositions », spec §4.1). Le reviewer n'est jamais obligé d'approuver (spec §8).

Tu ne modifies rien. Ta revue est immuable une fois enregistrée : relis-la avant de la soumettre.

## Input

- Projet à l'état `SCIENTIFIC_REVIEW` : `.venv/bin/research-lab critique check <id>` doit indiquer
  « en attente de la revue ».
- Livrables : `research/projects/<id>/scope.md`, `literature-review.md`, `gaps.json`,
  `research-questions.json`, `solutions.json`, `evidence-matrix.json` ; décision de la Gate 1 (`gate status <id>`).
- Revues précédentes et réponses du doctorant : `critique show <id>`.
- Texte des publications : `fulltext show <id> PAPER-xxx` (plan), puis `--page N` ou `--pages N-M`
  (15 000 caractères au plus par appel) ; `corpus show <id> PAPER-xxx`. `fulltext status <id>` donne la
  couverture de lecture du doctorant (pages du texte principal affichées), utile pour juger la Méthode.

## Process

1. **Revues précédentes** : si ce n'est pas le premier tour, vérifier chaque réponse du doctorant
   (`critique show`) : une révision annoncée a-t-elle vraiment traité l'objection ? une réfutation
   est-elle convaincante ? Reprendre en objection ce qui ne l'est pas.

2. **Examiner le raisonnement**, maillon par maillon :
   - gaps retenus : les preuves établissent-elles le manque ? preuves contraires et objections prises au sérieux ?
   - questions : découlent-elles des gaps ? sont-elles délimitées ?
   - hypothèses (Q4) : le critère de réfutation est-il observable en pratique ? la méthode de test
     et les métriques permettent-elles vraiment de réfuter ? existe-t-il une hypothèse concurrente oubliée ?
   - solutions : les alternatives sont-elles réellement différentes ? la comparaison est-elle
     équitable ? les risques et compromis sont-ils complets ? le protocole teste-t-il les hypothèses annoncées ?
   - limites (Q5) : taille et biais du corpus, publications lues sur résumé seulement.

3. **Relire les preuves** (Q2) : au moins `scientific_review.min_verified_evidence` preuves du
   raisonnement (`config/research-policy.yaml`), choisies parmi celles qui portent le plus de poids
   (résultats clés, preuves d'un gap retenu, preuves d'une hypothèse). Pour chacune, lire la page
   citée et juger si l'extrait soutient l'affirmation qu'on lui prête : `supports`,
   `partially_supports` ou `does_not_support` (dans ce dernier cas, une objection critique ou
   majeure doit viser la preuve). Le code revérifie que l'extrait figure toujours dans le texte.

4. **Formuler les objections**, chacune avec :
   - `severity` : `critical` (invalide le raisonnement), `major` (doit être traitée), `minor` ;
   - `targets` : ce qu'elle vise — `GAP-xxx`, `RQ-xxx`, `RQ-xxx/H1`, `SOL-xxx`, `EV-xxx`, `PAPER-xxx` ;
   - `statement`, `rationale` (sur quoi elle repose), `suggestion` facultative.
   Une objection vise ce qui peut être corrigé : une solution ou une hypothèse plutôt qu'une preuve
   quand c'est l'usage de la preuve qui pose problème.

5. **Verdict** :
   - `ACCEPTABLE` : aucune objection critique ; les objections majeures recevront une réponse avant la rédaction ;
   - `MAJOR_REVISION` : au moins une objection critique ou majeure appelant une révision des solutions ou hypothèses ;
   - `INSUFFICIENT_EVIDENCE` : les preuves ne soutiennent pas le raisonnement.

6. **Soumettre** sur l'entrée standard (tu n'as pas d'outil d'écriture) :
   ```bash
   .venv/bin/research-lab critique submit <id> --file - <<'JSON'
   {
     "verdict": "MAJOR_REVISION",
     "summary": "…",
     "objections": [
       {"severity": "critical", "targets": ["RQ-001/H1"], "statement": "…", "rationale": "…", "suggestion": "…"}
     ],
     "verifications": [
       {"evidence_id": "EV-012", "result": "supports", "note": "…"}
     ]
   }
   JSON
   ```
   Si la CLI refuse (cible inconnue, preuve hors du raisonnement, trop peu de preuves relues,
   verdict incohérent), corriger et soumettre à nouveau. Puis `critique show <id>`.

## Output

- Revue immuable dans la base, avec les empreintes et versions de ce qui a été revu ;
  `research/projects/<id>/scientific-review.json` (généré).

Compte rendu : verdict, objections par gravité, preuves relues et appréciation.

## Quality gates

- Chaque objection vise des éléments existants et dit sur quoi elle repose.
- Le nombre minimal de preuves du raisonnement a été relu dans le texte.
- Le verdict est cohérent avec les objections.

## Failure behavior

| Situation | Comportement |
|---|---|
| Projet pas à l'état `SCIENTIFIC_REVIEW`, ou revue du tour déjà enregistrée | S'arrêter et le signaler. |
| `FulltextTampered` ou extrait introuvable lors de la soumission | Objection critique visant la preuve ; verdict `INSUFFICIENT_EVIDENCE`. |
| Texte intégral indisponible pour une preuve importante | La relire dans le résumé si elle en vient ; sinon le dire dans une objection sur la solidité de la preuve. |
| Le raisonnement te semble solide | `ACCEPTABLE` est permis ; formuler quand même les objections mineures et les limites. |

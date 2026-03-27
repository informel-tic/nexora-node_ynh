# Check-list de finalisation — Nexora

But: formaliser la baseline de sortie et rendre vérifiable la clôture palier 1 et palier 2.

## Statut d'implémentation (mise à jour)

- Phase 0 : baseline formalisée et audit initial exécuté.
- Palier 1 :
	- Proxy REST `node.actions` renforcé avec routes dédiées tenant-scopées.
	- Snapshot PRA enrichi avec `tenant_id` pour renforcer les filtres gouvernance.
	- Tokens scopés durcis: en-tête tenant obligatoire + claim HMAC requis quand un mapping de scopes est configuré.
	- Résilience dev/test améliorée si OpenSSL absent (fallback explicite, borné au contexte test/flag).
	- Contrats comportementaux ajoutés pour les routes dédiées `node.actions` et le durcissement token scope.
	- Réduction des exceptions silencieuses résiduelles via journalisation explicite en fallback runtime.
- Validation locale ciblée : `32 passed` sur suites behavior/auth/debt.
- Validation globale locale : `360 passed, 5 skipped, 30 subtests passed` sur `tests/`.
- Gate de charge multi-tenant validé localement (`1500/1500` requêtes, `p95=109.147ms`, `0` échec).
- Packaging wheel/sdist validé localement via `python -m build`.
- Matrice e2e opérateur shell non exécutable sur l'environnement actuel (WSL non installé).
- Build offline bundle et matrice e2e shell bloqués sur l'environnement actuel (WSL sans distribution).
- Reste à fermer pour Palier 1 : validation e2e/bootstrap shell sur environnement Linux (WSL opérationnel) puis validation packaging shell complète.

1) Baseline minimale (Phase 0)
- Définir et approuver la matrice "Palier 1 / Palier 2 / v2.1+".
- Lister les dettes critiques et leur propriétaire (TD-001..TD-005, S3..S5, A1..A2).
- Définir preuves exigées pour considérer un item "done" (tests automatisés, runbook rejoué, artifact release, securité, profondeur d'anticipation des problématiques).

2) Critères Palier 1 (release opérateur)
- TD-001 (tenant filtering) fermé ou atténué avec tests.
- TD-002 (exceptions silencieuses) corrigé + test de non-régression.
- Replay detection & rate-limit durables (ou plan de migration documenté).
- Token rotation opérationnelle (runbook + test).
- Parité REST/MCP/Console pour surfaces prioritaires (governance.risks, node.actions proxy).
- Workflows bootstrap (fresh/adopt/augment) vérifiés end-to-end.
- Pipeline release & packaging vérifié (wheel, offline bundle, package YunoHost).
- Documentation opérateur mise à jour et runbooks rejoués.

3) Critères Palier 2 (SaaS production)
- Persistance SQL/RLS déployée et validée (J0..J3).
- Isolation des données par `tenant_id` prouvée par tests et audits.
- Subscriber boundaries durcies et guide abonné finalisé.
- Tests longue durée multi-tenant passés et SLO/SLA définis.
- Observabilité, métriques et journaux prêts pour support en production.

4) Vérifications automatisées (commandes de preuve)
- `PYTHONPATH=src python -m pytest --collect-only -q`
- `PYTHONPATH=src python -m pytest tests/test_ci_guardrails.py tests/test_docs_completeness.py tests/test_docs_inventory_contract.py tests/test_repo_split_contract.py tests/test_docs_obsolescence_contract.py -q`
- `PYTHONPATH=src python -m pytest tests/test_debt_guardrails.py tests/test_persistence_backend.py tests/test_multitenant_extended.py tests/test_ws9_multitenancy.py tests/test_p8_behavioral.py tests/test_load_test_multitenant.py -q`
- `PYTHONPATH=src python -m pytest tests/ -v --tb=short`
- `PYTHONPATH=src python scripts/load_test_multitenant.py --tenants 12 --requests 1500 --workers 24 --duration-seconds 45 --max-failures 0 --max-p95-ms 750`
- `./scripts/e2e_operator_matrix.sh`

5) Gouvernance documentaire
- Mettre à jour `docs/CHANGELOG.md` pour chaque correction.
- Verrouiller `docs/docs_inventory.yaml` et exiger suppression d'obsolescence avant merge.
- Publier un tableau de pilotage (Palier 1 / Palier 2 / v2.1+) et lier PRs/tickets.

6) Prochaines actions immédiates
- Lancer l'audit pour localiser `except: pass` et lister occurrences.
- Ouvrir PRs pour TD-002 et TD-001 (priorité).
- Planifier la migration SQL shadow (J0) en tant que branche experimente.

---

Fichier créé automatiquement pour matérialiser la baseline de finalisation.

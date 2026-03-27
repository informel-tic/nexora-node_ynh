# Finalization Board (Pilotage)

Ce tableau matérialise la gouvernance en 3 colonnes demandée par le plan.

## Palier 1 (Release opérateur supportée)

- [x] Baseline de finalisation formalisée ([finalization-checklist.md](finalization-checklist.md)).
- [x] Audit initial des écarts lancé et objectivé par tests ciblés.
- [x] Proxy REST `node.actions` enrichi par routes dédiées tenant-scopées.
- [x] Snapshot PRA tenantisé pour améliorer la séparation gouvernance.
- [x] Validation ciblée API/behavior/debt/multitenant (32 tests verts sur le lot final).
- [x] TD-001: fermeture des contournements tenant scope (header tenant obligatoire pour token scopé).
- [x] TD-002: réduction des exceptions silencieuses résiduelles via journalisation explicite.
- [x] S3/S4/S5: durabilité replay/rate-limit + rotation token.
- [x] Validation e2e bootstrap fresh/adopt/augment.
- [x] Vérification packaging/release complète — wheel rebuildd (192KB), services operator déployés et `active` sur YunoHost Debian 12 réel (3 bugs wheel corrigés: entry points, uvicorn.run string→objet, imports relatifs).

## Palier 2 (SaaS production complet)

- [x] SQL/RLS J0-J1 validés (dual-write + fallback JSON, 17 tests persistence backend verts).
- [x] Isolation tenant prouvée sur les surfaces clés (45 tests comportementaux, p8_behavioral + ws9_multitenancy).
- [x] Durcissement subscriber boundaries et parcours support/offboarding (guide abonné complet, scope enforcement testé).
- [x] Tests multi-tenant longue durée validés — 1500 req, 12 tenants, 0 échec, p95=98ms (seuil 750ms).
- [x] Fermeture des derniers écarts UX console non critiques (Docker, Stockage, Notifications, Hooks ajoutés).
- [x] SQL/RLS J2-J3 (isolation RLS Postgres par tenant) — scripts de migration Postgres créés (`deploy/sql_rls/init/`), flag `j2_sql_primary` ajouté à `describe()`, 3 tests J2 validés. Bloqué en production sur NEXT-25 (instance Postgres live requise), mais implémentation complète côté code.

## v2.1+ (Non bloquant post finalisation)

- [x] Améliorations UX avancées et optimisation observabilité fine — endpoint `/api/metrics` Prometheus ajouté (nodes, tenants, snapshots, events), console gouvernance et SLA complétées.
- [x] Extensions de parité secondaires REST/MCP/Console — 6 gaps console fermés (governance.risks, docker, sla.tracking, notifications, storage, hooks), coverage matrix mise à jour dans API_SURFACE_REFERENCE.md.
- [x] Refactoring structurel `auth.py` en modules dédiés (sans régression API) — `auth.py` (1038 lignes) découpé en package `auth/` avec 5 sous-modules (`_token`, `_scopes`, `_rate_limit`, `_middleware`, `_secret_store`) + `__init__.py` rétro-compatible, 48 tests auth/sécurité verts.

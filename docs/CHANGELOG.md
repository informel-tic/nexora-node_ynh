# Changelog

All notable changes to the Nexora platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added (sprint 2026-03-27 — finalisation complète v2.1)
- **auth.py modularisation (NEXT-22)** — `src/nexora_core/auth.py` (1038 lignes) découpé en package `auth/` avec 5 sous-modules dédiés : `_token` (gestion tokens, rotation, session), `_scopes` (tenant/rôle, validators), `_rate_limit` (rate-limiting avec persistance fichier), `_middleware` (TokenAuth, SecurityHeaders, CSRF), `_secret_store` (SecretStore, VALID_SCOPES). `__init__.py` rétro-compatible — les 20+ sites d'import existants fonctionnent sans modification. Les globaux mutables (`_api_token`, `_AUTH_FAILURES`) accessibles via `auth._token._api_token` et `auth._rate_limit._AUTH_FAILURES`.
- **SQL/RLS J2-J3** — Scripts de migration Postgres créés sous `deploy/sql_rls/init/` : `001_base_schema.sql` (tables canoniques), `002_rls_policies.sql` (policies `tenant_isolation` + `platform_admin_read` sur `tenant_artifacts`), `003_rls_operator_bypass.sql` (rôles `nexora_app`/`nexora_owner`/`nexora_service`, fonctions `nexora_set_tenant`, vue `v_control_plane_state` J2). Runbook dans `deploy/sql_rls/README.md`.
- **J2 flag** — `SqliteStateRepository.describe()` expose désormais `j2_sql_primary: bool` (True quand `dual_write=False` — SQL primaire). 3 nouveaux tests J2 dans `tests/test_persistence_backend.py` (20 tests total, tous verts).
- **Console parité** — 2 nouvelles vues console : `loadGovernanceRisks` (registre des risques avec score card), `loadSlaTracking` (paliers SLA avec uptime %, RTO/RPO). `app.js` et `index.html` mis à jour (sections `governance` et `sla-tracking`).
- **Endpoint `/api/metrics`** — endpoint Prometheus-compatible (text/plain, format 0.0.4) exposant : `nexora_nodes_total`, `nexora_nodes_by_status{status=…}`, `nexora_tenants_active_count`, `nexora_inventory_snapshots_total`, `nexora_security_events_total`.
- **API Surface Reference** — 6 gaps console fermés (governance.risks, docker.management, sla.tracking, notifications.routing, storage.analysis, hooks.management). Coverage matrix mise à jour (Y/Y/Y pour les 6). Section "Gap List" remplacée par "Remaining Gaps (v2.1+ backlog)" — 4 items résiduels.

### Added (sprint 2026-03-26 — poursuite finalisation)
- **Console UX** — 4 vues manquantes ajoutées: Docker (`loadDocker`), Stockage (`loadStorage`), Notifications (`loadNotifications`), Hooks (`loadHooks`); liens de navigation correspondants dans `index.html`; routeur `sectionRenderers` mis à jour dans `app.js`. Ferme l'écart UX Palier 2 "derniers écarts console non critiques".
- **Tech Debt Register** — TD-001, TD-002, TD-004, TD-005 clôturés (statut → Done) sur la base des tests comportementaux passants et du garde-fou CI anti-swallow; date de mise à jour corrigée à 2026-03-26.

### Fixed (sprint 2026-03-26 — déploiement opérateur)
- **[DEPLOY BUG 1]** `pyproject.toml` — entry points corrigés : `apps.control_plane.backend:main` → `control_plane.backend:main` et `apps.node_agent.agent:main` → `node_agent.agent:main`. Le wheel installait les packages sous `control_plane/` et `node_agent/` (sans préfixe `apps.`), rendant les console_scripts non fonctionnels.
- **[DEPLOY BUG 2]** `apps/control_plane/api.py` et `apps/node_agent/api.py` — `uvicorn.run("apps.xxx.api:app", ...)` (string) remplacé par `uvicorn.run(app, ...)` (objet direct). La résolution module-string échoue après installation wheel car `apps.control_plane` n'est pas importable dans l'environnement installé.
- **[DEPLOY BUG 3]** `apps/control_plane/backend.py` et `apps/node_agent/agent.py` — imports absolus (`from apps.control_plane.api import ...`) remplacés par imports relatifs (`from .api import ...`) pour fonctionner à la fois en source et depuis le wheel.
- Tests contractuels `test_runtime_boundaries.py` mis à jour pour accepter la forme d'import relative (ou absolue).

### Validated (sprint 2026-03-26)
- Bootstrap orchestration Python (12/12 tests) — logique lifecycle/enrollment/capabilities validée sans WSL.
- Wheel `nexora_platform-2.0.0-py3-none-any.whl` rebuildd (192KB) — packaging reproductible confirmé.
- **Déploiement opérateur réel validé** sur serveur YunoHost Debian 12 (`srvtestyuno1.local`) :
  - `nexora-control-plane` → `active (running)` sur `127.0.0.1:38120`, health OK (`{"status":"ok","version":"2.0.0"}`)
  - `nexora-node-agent` → `active (running)` sur `127.0.0.1:38121`, health OK
  - Services activés comme units systemd, démarrage automatique au reboot
- Multi-tenant load test: 1500/1500 requêtes, 12 tenants, 0 échecs, p95=98ms (seuil 750ms) — SLA Palier 2 validé.
- Persistence backend SQL (17/17 tests) — dual-write J0, fallback JSON J1, cohérence multi-tenant confirmés.


- **[S1] CRITICAL BUG FIX**: `validate_scoped_secret` in `src/nexora_core/auth.py` — post-match validation logic was outside the `for record in records:` loop, causing only the last record to be validated. All checks (revoked, scope, tenant, expiry, permissions) are now correctly executed inside the loop, eliminating a potential auth bypass.
- **[S2] BUG FIX**: `purge_tenant_secrets` in `src/nexora_core/auth.py` used an undeclared `logger` variable, causing a guaranteed `NameError` crash on tenant purge. Fixed by adding `import logging` and `logger = logging.getLogger(__name__)`.
- **[S3/S4/S5] HARDENING COMPLETED**: `src/nexora_core/auth.py` now persists replay-consumed token digests and auth failure counters across restarts, and implements API token rotation (`rotate_api_token`) with optional auto-rotation through `NEXORA_API_TOKEN_AUTO_ROTATE_DAYS`.
- **[TD-001] TENANT SCOPE ENFORCEMENT**: scoped tokens now require `X-Nexora-Tenant-Id` on authenticated requests when a token-scope mapping is configured, closing the no-header bypass path; behavioral regression added in `tests/test_p8_behavioral.py`.
- **[S6] Content-Security-Policy header** added to `SecurityHeadersMiddleware`. All API responses now include a strict CSP limiting script/style/connect/frame sources to `'self'` with `frame-ancestors 'none'`.
- **[S7] hmac.new()** call in `build_tenant_scope_claim` updated to use named keyword arguments (`key=`, `msg=`, `digestmod=`) following current Python 3 best practices.

### Added (sprint 2026-03-26)
- `docs/SUBSCRIBER_GUIDE.md` — comprehensive subscriber onboarding guide (enrollment, API surfaces, quotas, security, GDPR offboarding, support).
- CI jobs `lint` (ruff + mypy) and `security-scan` (bandit + pip-audit) added to `.github/workflows/ci.yml`; `vision-final-ready` now depends on both. CI guardrails test updated accordingly.

### Changed (sprint 2026-03-26)
- `docs/SECURITY.md` — rewritten from 26-line skeleton to comprehensive 12-section reference covering auth, SecretStore, rate-limiting, all middlewares, tenant RBAC, TLS/identity, at-rest secrets, audit trail, 4 policy profiles, known security debt table, and responsibility matrix.
- `docs/ARCHITECTURE.md` — rewritten from 25-line minimal to full architecture reference with ASCII diagrams (3-layer view, enrollment sequence, network flow), component table, all 91 `nexora_core` modules by domain, API route register map, persistence backend table, and architectural rules.
- `docs/IMPLEMENTATION_MASTER_PLAN.md` — added audit coherence warning banner; NEXT-18 to NEXT-25 backlog items added to track security debt from 2026-03-26 sprint.
- `apps/control_plane/api.py` — `security_updates`, `fail2ban_status`, `open_ports`, `permissions_audit`, `recent_logins` stub endpoints now include `_stub: true` and `_stub_note` fields explicitly declaring they require YunoHost CLI integration (audit item A3, tracking ticket NEXT-13).
- `src/nexora_core/node_actions.py` and `src/nexora_core/notifications.py` — fallback `except Exception` branches now emit explicit warning logs instead of silently continuing, reducing TD-002 runtime opacity.
- `docs/docs_inventory.yaml` — `SUBSCRIBER_GUIDE.md` added, count updated to 45, `updated_at` set to 2026-03-26.
- Dated audit files (`AUDIT_APPROFONDI_2026-03-24.md`, `CODEBASE_AUDIT_2026-03-24.md`, `DIRECTION_AUDIT_2026-03-24.md`, `EFFICIENCY_AUDIT_2026-03-25.md`, `PLATFORM_AUDITS_2026-03-23.md`) — archive notice added at top redirecting to consolidated `SECURITY.md`/`ARCHITECTURE.md`/`IMPLEMENTATION_MASTER_PLAN.md`.

- [2026-03-25] Bootstrap coherence policy now targets YunoHost nodes on Debian major tracks 11/12/13: prechecks are Debian-only, YunoHost compatibility is always assessed before mutation, and each bootstrap emits `/opt/nexora/var/node-coherence-report.json` with package/version inventory, scope/profile blockers and adaptation hints.
- [2026-03-25] Audit d’efficience Nexora/SaaS (phase 10) consolidé: diagnostic 360°, plan priorisé P0/P1/P2, KPI opérateurs, risques résiduels et alignement explicite avec la trajectoire multi-tenant souveraine.
- [2026-03-25] Exécution P0/P1: instrumentation SLO bootstrap (`/var/log/nexora/bootstrap-slo.jsonl` + `scripts/bootstrap_slo_summary.py`), matrice opérateur nocturne adopt/augment/fresh (`.github/workflows/nightly-operator-e2e.yml`, `scripts/e2e_operator_matrix.sh`) et observabilité coût CI (`scripts/ci_cost_report.py` + artefacts runtime).
- [2026-03-25] Robustesse d’exploitation VM YunoHost renforcée sur tracks Debian/YunoHost 11/12/13: détection YunoHost multi-sources (`tools version`/`--version`/`dpkg-query`), audit de cohérence node, et fallback online contrôlé si bundle offline incomplet (`NEXORA_ALLOW_ONLINE_WHEEL_FALLBACK`).
- [2026-03-24] Added `docs/COMMERCIAL_OPERATING_MODEL.md` describing the end-to-end functional model (operator SaaS vs subscriber agent-only), commercialization model, and marketing/GTM framing.
- [2026-03-24] Added `scripts/export_split_repos.sh` to generate two publication-ready snapshots (`operator-private` and `subscriber-public`) supporting a two-repository strategy (private operator SaaS repo vs public subscriber node-agent repo).
- [2026-03-24] `scripts/build_vm_offline_kit.sh` now defaults to `KIT_SCOPE=subscriber` and strips control-plane/console/package artifacts for client kits, with explicit `KIT_SCOPE=operator` opt-in for internal runtimes.
- [2026-03-24] Added `docs/ROOT_ACCESS_LIMITS.md` and bootstrap guardrails clarifying that root-owned client hosts cannot be made copy-proof; subscriber scope now hard-refuses control-plane bootstrap profiles and requires `node-agent-only` to preserve SaaS/operator separation.
- [2026-03-24] Added deployment-scope guardrails for SaaS separation: control-plane now supports `NEXORA_DEPLOYMENT_SCOPE=subscriber` to deny non-minimal control-plane surfaces (console + non-enrollment APIs), and service templates explicitly pin `NEXORA_DEPLOYMENT_SCOPE=operator`; behavioral and packaging tests were extended accordingly.
- [2026-03-24] Package/operator hardening: YunoHost install/upgrade/restore now enforce an explicit operator-role lock file (`/etc/nexora/api-token-roles.json`), control-plane services set `NEXORA_OPERATOR_ONLY_ENFORCE=1` and `NEXORA_API_TOKEN_ROLE_FILE`, and packaging tests now assert these guardrails.
- [2026-03-24] Added `scripts/build_vm_offline_kit.sh` to generate a single FTP/SFTP-uploadable offline VM artifact (repo snapshot + wheel bundle + SHA256), and documented `SKIP_NETWORK_PRECHECKS=yes` for isolated YunoHost 12 test VMs.
- [2026-03-24] Deployment guidance now includes an explicit YunoHost 12 **non-exposed VM** offline workflow (bundle build, FTP/SFTP upload, `NEXORA_WHEEL_BUNDLE_DIR` usage, and bootstrap network-precheck caveat), plus an updated operator checklist for SaaS validation on isolated test environments.
- [2026-03-24] Phase 10 operator-surface closure: enforced and audited operator-only matrix for sensitive internal routes (persistence, interface parity, docker/failover/storage/notifications/sla/hooks/automation), with subscriber-deny behavioral coverage and synchronized status tracking (`P10-T04` / `CP-08`).
- [2026-03-24] Phase 10 closure sprint (single pass): SQL backend now performs dual-write with JSON coherence reporting, `/api/persistence` surfaces coherence metadata, CI `vision-final-ready` now runs long-run multitenant load thresholds, and operator-only enforcement was added on critical internal routes (`/api/persistence`, `/api/interface-parity/fleet-lifecycle`) with behavioral coverage.
- [2026-03-24] Phase 10 execution kickoff: added optional SQL persistence backend (`NEXORA_PERSISTENCE_BACKEND=sql`), tenant-aware SQL artifact indexing, CI gate `vision-final-ready`, and multitenant load smoke script (`scripts/load_test_multitenant.py`); synchronized roadmap/master plan/checkpoints/CI quality docs to track final-scale closure.
- [2026-03-24] Documentation architecture refactor: added `docs/DOCUMENTATION_ARCHITECTURE.md`, upgraded `docs/adr/README.md` into a lifecycle-aware ADR index, aligned `.agents` references/workflow to the new doc hierarchy, and synchronized `docs/docs_inventory.yaml` + `docs/CHECKPOINTS.md` for Phase 9 closure tracking.
- [2026-03-24] Phase 9 completion pass: tenant scope extended to remaining security routes (including fail2ban mutations), runtime quota enforcement now covers `max_apps_per_node` and `max_storage_gb` in enrollment/import flows, audit/runtime artifacts carry tenant tagging on creation, isolation tests expanded, and SQL+RLS persistence migration plan published in `docs/CONTROL_PLANE_PERSISTENCE.md`.
- [2026-03-24] Phase 9 continuation (`P9-T06`): added canonical tenant quota endpoint `/api/tenants/usage-quota` exposing per-tenant `usage` vs `limits` with `exceeded` flags and entitlements; includes tenant-scoped API behavioral tests and master-plan progress update.
- [2026-03-24] Node-action resilience + CI status hardening: `inventory/refresh` now tolerates summary objects without `tenant_id` while persisting snapshots; regression coverage added in `tests/test_node_action_backends.py`; CI workflow now keeps `test-collection` and `tests` in a terminal non-skipped state on docs-only changes via step-level fast path, with guardrails/docs updated (`tests/test_ci_guardrails.py`, `docs/CI_QUALITY_GATES.md`).
- [2026-03-24] Documentation alignment pass: `docs/CHECKPOINTS.md` and `docs/IMPLEMENTATION_MASTER_PLAN.md` now explicitly distinguish delivered Phase 9 items (core governance tenant-scope + scoped-token claim binding) from remaining open tasks, to avoid ambiguity in GitHub diff reviews.
- [2026-03-24] SaaS hardening continuation (Phase 9): when token→tenant scope mapping is enabled, tenant-scoped requests now require a matching HMAC claim header `X-Nexora-Tenant-Claim` bound to the authenticated token; regression tests cover missing/valid claim cases.
- [2026-03-24] SaaS hardening continuation (Phase 9): tenant-scoped `security/posture` now reads permissions from tenant-filtered governance inventory (not global inventory), and governance isolation tests now cover `/api/governance/risks`, `/api/security/posture`, `/api/pra`, plus token-scope denial on governance routes.
- [2026-03-24] SaaS hardening continuation (Phase 9): governance routes `/api/scores`, `/api/governance/report`, `/api/governance/risks`, `/api/security/posture`, and `/api/pra` now accept tenant scope and return tenant-aware payloads when `X-Nexora-Tenant-Id` is provided; regression coverage extended in `tests/test_p8_behavioral.py`.
- [2026-03-24] Documentation refonte aligned to sovereign SaaS direction: roadmap/checkpoints/master-plan now expose an active post-audit Phase 9 backlog (`P9-T01`..`P9-T07`) for tenant isolation closure, auth claim binding, runtime quota enforcement, quota observability, and SQL/RLS migration planning; project and SaaS strategy docs now explicitly state subscriber non-goals for self-hosted control-plane usage.
- [2026-03-24] SaaS hardening continuation (WS9-P0): added optional token-to-tenant scope binding in `TokenAuthMiddleware` via `NEXORA_API_TOKEN_SCOPE_FILE` (rejects tenant header outside authorized scope), tenant tagging of new inventory snapshots (`adoption-import`, `heartbeat`, `inventory/refresh`), and tenant-filtered `/api/governance/snapshot-diff`; added regression coverage in `tests/test_p8_behavioral.py`.
- [2026-03-24] CI docs-only fast path added: new `changes` job with `dorny/paths-filter` in `.github/workflows/ci.yml`, conditional execution for `test-collection`/`tests` when code paths are modified, and updated guardrail coverage in `tests/test_ci_guardrails.py`; documentation synchronized in `docs/CI_QUALITY_GATES.md`.
- [2026-03-24] Added an obsolescence-removal workflow gate: new script `scripts/docs_obsolescence_audit.py`, CI step `python scripts/docs_obsolescence_audit.py --enforce-removal`, and contract test `tests/test_docs_obsolescence_contract.py`; updated `.agents` workflow/instructions and `docs/CI_QUALITY_GATES.md` accordingly.
- [2026-03-24] Added `docs/DIRECTION_AUDIT_2026-03-24.md` to verify sovereign SaaS recentering against `docs/IMPLEMENTATION_MASTER_PLAN.md` and to publish the prioritized finalization backlog (P0/P1/P2) for tenant isolation, quota enforcement, and scale readiness.
- [2026-03-24] WS9 tenant-isolation hardening for control-plane fleet routes: `/api/fleet/topology` now applies tenant-header scoping, and mutation routes (`/api/fleet/nodes/{node_id}/action`, lifecycle actions) now deny cross-tenant node access with explicit `403`; added behavioral tests in `tests/test_p8_behavioral.py`.
- [2026-03-24] Sovereign SaaS recentering pass extended across project governance assets: updated `docs/PROJECT.md`, `docs/ROADMAP.md`, `docs/CHECKPOINTS.md`, `docs/AUDIT_APPROFONDI_2026-03-24.md`, `docs/COMPLIANCE_GOVERNANCE.md`, `.agents/instructions/AI_DRIVEN_DEV.md`, `.agents/workflows/nexora-prod-ready.md`, and YunoHost package descriptions (`ynh-package/doc/DESCRIPTION.md`, `ynh-package/doc/DESCRIPTION_fr.md`) to enforce operator-only internal hosting and subscriber SaaS access.
- [2026-03-24] Added `docs/AUDIT_APPROFONDI_2026-03-24.md` for a deep, master-plan-aligned repository audit (test baseline, risk ranking, and execution priorities for scale/SaaS hardening), and registered it in `docs/docs_inventory.yaml`.
- [2026-03-24] Bug bounty sweep completed: fixed confirmation-token replay (`validate_bound_confirmation` now one-time), tightened CSRF for mutating requests (Origin/Referer required), and reduced offline wheel install attack surface by pinning to `nexora_platform-*.whl`; added regressions in `tests/test_modes_extended.py` and `tests/test_p8_behavioral.py` plus `docs/BUG_BOUNTY_2026-03-24.md`.
- [2026-03-24] P8 hardening block completed: offline wheel bundle workflow (`scripts/build_offline_bundle.sh` + `NEXORA_WHEEL_BUNDLE_DIR` install path), behavioral API/idempotence tests (`tests/test_p8_behavioral.py`), and auditable uninstall purge mode with JSON report (`ynh-package/scripts/remove`, `/var/log/nexora-uninstall-report.json`, `docs/UNINSTALL.md`).
- [2026-03-24] Master plan continuation: Phase 0 task `P0-T04` is now completed with `docs/SURFACE_NAMING_CONVENTIONS.md`, formalizing canonical naming across capability IDs, REST paths, MCP tools, console routes/components, and JSON payload fields.
- [2026-03-24] Governance update: `.agents` policies now require planning by large implementation blocks (not micro-steps by default), introduce mandatory bug hunting with regression tests, and `docs/IMPLEMENTATION_MASTER_PLAN.md` now explicitly requires reading `.agents/instructions/AI_DRIVEN_DEV.md` and `.agents/workflows/nexora-prod-ready.md` at task start.
- [2026-03-24] Adoption hardening wave: `build_adoption_report` now detects nested path conflicts, nginx health blockers, and domain certificate readiness warnings; `deploy/bootstrap-adopt.sh` now enforces blocking-collision gates from `/opt/nexora/var/adoption-report.json`; added `tests/test_adoption_report.py` (happy/error/edge coverage).
- [2026-03-24] MCP adapter debt TD-003 repaid: `src/yunohost_mcp/server.py` now enforces policy filtering through FastMCP public APIs (`list_tools`, `remove_tool`) instead of private registry attributes, with a guardrail test added in `tests/test_debt_guardrails.py`.
- [2026-03-24] Bootstrap/package lifecycle convergence advanced: YunoHost package `install/upgrade/restore` scripts now call `python3 -m nexora_core.bootstrap assess-package-lifecycle`, so compatibility policy is evaluated by the same canonical Python service used by bootstrap.
- [2026-03-24] Technical debt repayment wave launched: tenant-scoped dashboard filtering implemented in `orchestrator.py`, silent exception swallowing reduced in core/MCP runtime paths, and new CI debt guardrail test (`tests/test_debt_guardrails.py`) wired into `.github/workflows/ci.yml`.
- [2026-03-24] Added `docs/TECH_DEBT_REGISTER.md` and extended `docs/docs_inventory.yaml` to track debt remediation governance explicitly.
- [2026-03-24] Agent governance docs aligned to Deep execution standard: `.agents/instructions/AI_DRIVEN_DEV.md` now defines RFC2119 obligations, Lite/Standard/Deep classification, Doc Inventory, measurable quality gates, and mandatory delivery template.
- [2026-03-24] Production workflow aligned to Deep standard: `.agents/workflows/nexora-prod-ready.md` now enforces impact matrix, test pack minimum (happy/error/edge), CI decision reporting, and pass/fail final gates.
- [2026-03-24] Full docs consistency pass (`docs/` + `docs/adr`) with roadmap status alignment (WS4/WS7/WS8/WS9), MCP tool-count refresh (225 registered / 194 exposed), and updated audit traceability.
- [2026-03-24] Documentation pass #2: normalized historical wording in `DOC_CODE_AUDIT.md` (snapshot markers + current test baseline) to avoid ambiguity between past audit snapshots and current branch state.
- [2026-03-24] Documentation pass #3: added `docs/docs_inventory.yaml` (33-doc dependency map) and CI contract `tests/test_docs_inventory_contract.py`, now enforced in `.github/workflows/ci.yml`.
- [2026-03-24] CI quality gates hardened: PR-trigger contract checks, workflow concurrency/caching, and dedicated CI guardrail tests.
- [2026-03-24] Added `docs/CI_QUALITY_GATES.md` and aligned runbooks/README with mandatory pre-PR validation steps.
- [2026-03-24] Platform audits for Security, Rollback, Upgrade and UX/UI.
- [2026-03-24] Executive audit roadmap focusing on WS5 Interface Convergence, WS6 Modular Console, WS4 mTLS Security, WS8 Observability, WS7 Packaging, and WS9 SaaS Vision.
- [2026-03-23] AI Workflow: Verified EPIC-3-1 Enrollment & Lifecycle execution and unit tests passed on Windows environment.
- [2026-03-23] AI Workflow: Verified EPIC-3-2 Transport & Network Security execution and tests passed.
- [2026-03-23] AI Workflow: Verified EPIC-3-3 Node-Agent action endpoints and capabilities.
- [2026-03-23] AI Workflow: Verified EPIC-3-7 Modes, Policy, and Confirmations tests.
- [2026-03-23] AI Workflow: Verified EPIC-3-8 Packaging YunoHost manifest constraints and pathing.
- [2026-03-23] AI Workflow: Verified EPIC-3-15 Security Hardening input validation checks.
- [2026-03-23] AI Workflow: Verified EPIC-3-16 Base CI and massive local mock test suite.
- [2026-03-23] AI Workflow: Verified EPIC-3-4 Fleet Inventory & Heartbeat mechanics.
- [2026-03-23] AI Workflow: Verified EPIC-3-5 Inter-node synchronization execution and job queues.
- [2026-03-23] AI Workflow: Verified EPIC-3-6 Orchestrator engine constraints and blueprints models.
- [2026-03-23] AI Workflow: Verified EPIC-3-9 Observability, local SLA event history, and metrics.
- [2026-03-23] AI Workflow: Verified EPIC-3-10 Disaster recovery, PRA helpers, and offsite backups.
- [2026-03-23] AI Workflow: Verified EPIC-3-11 Docker engine policies and reverse proxy supervision.
- [2026-03-23] AI Workflow: Verified EPIC-3-12 High Availability and Failover cluster mechanisms.
- [2026-03-23] AI Workflow: Verified EPIC-3-13 Multi-Tenant isolation policies and configuration overrides.
- [2026-03-23] AI Workflow: Verified EPIC-3-14 REST API definitions and v1 router schemas.

### Added
- EPIC-3-4 / EPIC-3-5: heartbeat versionné, snapshots d'inventaire et moteur de sync avec rollback.
- EPIC-3-9 / EPIC-3-10: métriques persistantes, calculs SLA/event history et helpers PRA/restore.
- EPIC-3-11 à EPIC-3-14 / EPIC-3-17: extensions Docker/HA/multi-tenant, namespace API v1 et nouveaux runbooks/références d'architecture.

### Added
- EPIC-3-2: TLS helpers, local CRL, HTTPS-first fleet transport and security audit trail.
- EPIC-3-3: node-agent action surface, capability catalog, metrics endpoint and dry-run/result contracts.
- WS2 finalization: atomic state saves, rotating backups, journal recovery, corruption recovery and control-plane persistence runbook.
- WS3 finalization: canonical node-action engine, privileged execution plans, PRA/maintenance/docker backends and normalized action audit contract.
- WS2 follow-up: persisted inventory cache through the state repository and added a legacy JSON migration path.
- WS3 follow-up: verified and documented the real `branding/apply` backend.
- EPIC-3-7: official MCP authorization matrix plus confirmation tokens bound to action/target/params.
- EPIC-3-8 / EPIC-3-16: YunoHost pre-install checks, CI workflow and release script.

### Changed
- `auth.py` now supports scoped per-node secrets and actor role validation helpers.
- `orchestrator.py` and node summaries now expose capability metadata derived from the action catalog.

### Added
- EPIC-3-1 enrollment core: one-time token issuance, challenge-response attestation, registration finalization, and lifecycle actions for drain/cordon/revoke/retire/rotation/re-enrollment.
- OpenSSL-backed fleet CA and per-node certificate issuance for Nexora node identities.
- Targeted unit test coverage for enrollment and node lifecycle flows.

### Changed
- `compatibility.py` now has a built-in YAML fallback parser so compatibility checks and CLI output still work in constrained environments without PyYAML.
- `yunohost_mcp.cli` now lazy-loads `uvicorn`, allowing the `compatibility` subcommand to run without server dependencies.

### Added
- AI-driven development workflow (`.agents/workflows/nexora-prod-ready.md`)
- AI agent instructions (`.agents/instructions/AI_DRIVEN_DEV.md`)
- Implementation plan (`docs/IMPLEMENTATION_MASTER_PLAN.md`, renommé depuis `docs/implementation_plan.md`)
- Task tracker (`docs/CHECKPOINTS.md`, remplace le suivi historique `docs/tasks.md`)

---

## [2.0.0] - 2026-03-23

### Added
- Unified `nexora_core` Python library (30 modules)
- Control-plane FastAPI (`apps/control_plane/backend.py`)
- Node-agent FastAPI (`apps/node_agent/agent.py`)
- 214 MCP tools across 26 modules
- Compatibility matrix (`compatibility.yaml`) with pinning policy
- Bootstrap script `deploy/bootstrap-node.sh` with Debian 12 + YunoHost validation
- Three bootstrap profiles: `control-plane`, `node-agent-only`, `control-plane+node-agent`
- Two enrollment modes: `push`, `pull`
- Node lifecycle state machine with 10 states and validated transitions
- Mode system: observer / operator / architect / admin
- Confirmation tokens for destructive operations
- Escalation tokens with TTL
- YunoHost package (`ynh-package/`) with 6 lifecycle scripts
- Scoring engine: security, PRA, health, compliance (0-100 with grades)
- Fleet inventory, drift detection, topology generation
- Sync plans (branding, permissions, PRA, inventory)
- Blueprint system for sector-specific deployments
- Docker integration with templates and compose generation
- Failover / HA configuration generators
- Multi-tenant isolation by domain/group
- Notification templates and alert routing
- SLA tiers and uptime tracking
- Automation job templates and checklists
- Portal design system with sector themes

### Finalized
- [2026-03-23] All AI Workflow Blocs 1-17 successfully executed and verified via unit tests.
- Workflow completed successfully with Zero-Stop execution policy.
- [2026-03-24] Clarification: Zero-Stop is kept as historical snapshot wording for 2026-03-23 only; active governance now follows the Deep standard in `.agents/instructions/AI_DRIVEN_DEV.md` and `.agents/workflows/nexora-prod-ready.md`.

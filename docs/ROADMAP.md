# Produit et Trajectoire Nexora (Roadmap)

_Dernière mise à jour : 2026-03-26._

---

## 1. Vision et Modèle Produit

Nexora transforme YunoHost en une plateforme d'orchestration professionnelle sans modifier son cœur. Il s'agit d'un **SaaS souverain** opéré par Nexora pour ses abonnés.

### 1.1 Les 5 blocs officiels
1. **Nexora Node** : Runtime local (inventaire, attestation, actions locales).
2. **Nexora Control Plane** : API d'orchestration centrale (enrollment, flotte, cycle de vie).
3. **Nexora Console** : Interface opérateur UI dédiée.
4. **Nexora MCP** : Gateway d'automatisation IA (Adaptateur Modulaire).
5. **Nexora Value Modules** : Blueprints, PRA, Docker, Quotas, etc.

### 1.2 Doctrine et Modèles d'Opération
- **Distribution** : Le package YunoHost n'est qu'un artefact de distribution.
- **Opérateur (Interne)** : Self-hosting complet de la plateforme réservé à l'usage interne Nexora.
- **Abonné (Externe)** : Accès au service via le portail SaaS pour gérer ses propres nœuds.
- **Overlay Professionnel** : Capacités avancées (multi-nœuds, IA, PRA) au-dessus du YunoHost natif.

---

## 2. État d'avancement (Roadmap)

Nexora is evolving toward a clear platform split:
- **Nexora Node** on managed YunoHost servers
- **Nexora Control Plane** as the orchestration authority
- **Nexora MCP** as AI-facing interface adapter
- **Nexora Console** as operator UI
- **YunoHost package** as a distribution/support artifact

Strategic baseline: operator-managed sovereign SaaS with recursive internal dogfooding; subscriber-facing self-hosting is out of scope.

## Active checkpoints

### Platform boundary
- keep docs and code aligned on Node / Control Plane / MCP / Console ownership
- keep package scope explicit and narrower than total product scope

### Control-plane authority (WS1 + WS2 done)
- ~~move end-to-end enrollment/lifecycle orchestration behind service APIs~~ done — `bootstrap.py`, `enrollment.py`, `node_lifecycle.py`
- ~~reduce shell ownership of business lifecycle state changes~~ done — bootstrap shell scripts now delegate to Python services
- ~~prepare durable persistence beyond single-node JSON assumptions~~ done — `persistence.py` with atomic saves, journal recovery, rotating backups

### Node runtime hardening (WS3 done)
- ~~replace placeholder action surfaces with real execution backends~~ done — 9 backends in `node_actions.py`
- ~~complete remote trust and transport hardening~~ done — WS4 delivered (mTLS, trust policy, identity lifecycle)
- ~~improve production-grade observability and recovery behavior~~ done — WS8 delivered (metrics, SLA, runbooks, audit export)

### Next phases to consolidate (Audited 2026-03-24, refreshed)

1. **Interface convergence (WS5 / Phase 4) - STABILIZED**
   - strict parity between REST and MCP (fleet/lifecycle domains) is operational
   - Operator Console is connected to stable contracts
   - canonical capability catalog remains the source for residual gaps tracking

2. **Modular Operator Console (WS6 / Phase 5) - STABILIZED**
   - reusable UI primitives are in place (modals, alerts, tables)
   - domain views are implemented (Fleet, Adoption, Governance, PRA, Security)
   - accessibility improvements are in place (ARIA, focus management)
   - residual inline-style cleanup continues as hardening work

3. **Security and Trust (WS4 / Phase 4) - DONE**
   - ~~implement mTLS trust model between control plane and node-agent~~
   - ~~finalize identity rotation and revocation mechanisms~~
   - ~~isolate node secrets and complete end-to-end security audits~~

4. **Observability and Resilience (WS8 / Phase 6) - DONE**
   - ~~finalize critical runbooks (lost node, broken enrollment, full restore)~~
   - ~~normalize structured logging across all components~~
   - ~~harden upgrade and rollback automation tests~~

5. **Industrialization and Packaging (WS7 / Phase 6) - DONE**
   - ~~clarify support boundaries between YunoHost package and Nexora platform~~
   - ~~establish single source of versioning for releases~~

6. **Commercial Vision & SaaS (WS9 / Phase 7) - DELIVERED (Functional Baseline)**
   - ~~document operator-internal platform vs subscriber SaaS positioning~~
   - tenant isolation extended across fleet + governance + security surfaces
   - scoped-token tenant claim binding is active (`X-Nexora-Tenant-Claim`)
   - runtime quota enforcement includes nodes/apps/storage and usage/quota operator endpoint

## Active execution queue (Phase 10)

The current top-priority sequence is:

1. execute SQL/RLS persistence migration milestones (J0/J1 first),
2. keep automated coherence checks on roadmap/master-plan/checkpoints status drift green,
3. keep recurring multi-tenant load long-run tests and thresholds green,
4. keep operator-only surface separation for sensitive internal routes green (matrix + tests),
5. keep CI gate `vision-final-ready` green on every PR.

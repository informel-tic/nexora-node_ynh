# Plan directeur d’implémentation Nexora

_Dernière mise à jour : 2026-03-26._

> **⚠️ Avertissement de cohérence (audit 2026-03-26)** : Un audit de sécurité approfondi a révélé que plusieurs livraisons déclarées « [x] » dans les phases WS4/WS9 présentent des dettes techniques critiques non résolues. Les items NEXT-13 à NEXT-17 restent **ouverts**. Des items NEXT-18 à NEXT-25 ont été ajoutés pour tracer les dettes identifiées. Voir `docs/SECURITY.md` et `docs/ARCHITECTURE.md` pour les détails. **Ne pas traiter les statuts `[x]` comme garantie de complétude opérationnelle.**

## 1. Objet du document

Ce document transforme la vision produit et les checkpoints existants en **plan d’exécution complet** jusqu’à la vision finale de Nexora :

- **Nexora Node** sur chaque nœud YunoHost géré ;
- **Nexora Control Plane** comme autorité d’orchestration ;
- **Nexora Console** comme interface opérateur ;
- **Nexora MCP** comme adaptateur IA ;
- **package YunoHost** comme artefact de distribution/support ;
- exploitation récursive en **self-hosting opérateur (interne)** pour délivrer une **offre SaaS abonnée**.

Il sert de source opérationnelle pour :

1. prioriser les travaux ;
2. découper les epics en tâches concrètes ;
3. clarifier les dépendances ;
4. définir les critères de passage entre les phases.

---

## 2. Vision finale cible

### Vision produit

À terme, Nexora doit être une **plateforme d’orchestration professionnelle pour infrastructures YunoHost** avec :

- un **control plane central** pilotant enrollment, lifecycle, gouvernance, compatibilité, synchronisation et audit ;
- un **node runtime** exécutable localement ou à distance, capable d’inventaire, d’attestation et d’actions réelles ;
- une **console opérateur modulaire** pour dashboarding, adoption, flotte, sécurité, PRA et exploitation quotidienne ;
- une **surface MCP** alignée avec les mêmes capacités métier que l’API REST ;
- un **socle de distribution** propre pour les déploiements YunoHost supportés ;
- un mode **self-hosted multi-nœuds réservé à l’Opérateur** pour opérer le SaaS ;
- une trajectoire **SaaS multi-tenant** avec isolation client stricte.

### Définition de “vision finale”

La vision finale sera considérée atteinte lorsque les conditions suivantes seront réunies :

- le **control plane** est la seule autorité métier de coordination de flotte ;
- le **node runtime** exécute de vraies actions idempotentes et traçables ;
- **REST, Console et MCP** consomment les mêmes capacités métier sans divergence ;
- la persistance est **durable**, sauvegardable, restaurable et opérable en production ;
- la sécurité est **durcie de bout en bout** ;
- l’expérience opérateur est **documentée, testée et maintenable** ;
- le packaging, la release et l’exploitation sont **industrialisés** ;
- la plateforme peut supporter l’**opération interne récursive** et un **SaaS multi-tenant massif**.

---

## 3. État actuel synthétique

## Acquis déjà présents

- séparation explicite **Node / Control Plane / MCP / Console / package** ;
- matrice de compatibilité et version partagée ;
- base d’enrollment/lifecycle/fleet ;
- API control plane visible ;
- node runtime exposant identity, inventory, compatibility, actions ;
- packaging YunoHost fonctionnel ;
- premiers audits sécurité, UX, rollback, upgrade ;
- docs d’architecture, d’ADR, de sécurité, de runbooks et de packaging.

## Lacunes structurantes restantes

Les principaux écarts encore ouverts sont :

1. **bootstrap ↔ services Python**
   - le shell conserve encore une part trop forte des transitions métier ;
2. **persistence durable**
   - l’état JSON local doit évoluer vers une persistance de production ;
3. **node actions réelles**
   - plusieurs endpoints sont encore contractuels / placeholder ;
4. **convergence des interfaces**
   - REST, MCP et Console doivent partager strictement les mêmes capacités ;
5. **console modulaire**
   - l’UI reste encore partiellement monolithique/inline-driven ;
6. **sécurité réseau complète**
   - modèle de confiance et transport à finaliser ;
7. **exploitation production**
   - observabilité, backup/recovery, runbooks, release, upgrade paths à finaliser ;
8. **commercial/SaaS**
   - isolation client et packaging d’offre encore à industrialiser.

---

## 4. Principes de priorisation

L’ordre d’implémentation doit respecter les règles suivantes :

1. **Les frontières produit priment sur la vitesse**.
2. **Le control plane devient canonique avant de multiplier les fonctionnalités**.
3. **On remplace les placeholders par de vrais backends avant d’élargir la surface UI**.
4. **La persistance et la sécurité précèdent la montée en charge commerciale**.
5. **Le self-hosting est strictement réservé à l’Opérateur ; l’offre client est SaaS par abonnement**.

---

## 5. Chantiers structurants

## WS-1 — Core & orchestration canonique

**But :** faire du control plane l’autorité de coordination unique.

### Résultats attendus

- lifecycle, enrollment, compatibilité et politiques exposés par des services stables ;
- bootstrap et interfaces externes branchés sur ces services ;
- aucun doublon métier durable dans MCP, shell ou Console.

### Tâches

- [x] **WS1-T01** — cartographier toutes les transitions métier encore pilotées par shell/scripts.
- [x] **WS1-T02** — déplacer les transitions lifecycle critiques dans des services Python réutilisables.
- [x] **WS1-T03** — faire consommer ces services par le bootstrap fresh/adopt/augment.
- [x] **WS1-T04** — centraliser les règles de compatibilité/enrollment dans une API de service stable.
- [x] **WS1-T05** — formaliser les contrats d’erreur, rollback et retry pour enrollment/lifecycle.
- [x] **WS1-T06** — supprimer les dernières duplications métier côté MCP.
- [x] **WS1-T07** — ajouter des tests d’intégration control plane ↔ bootstrap ↔ node-agent.

## WS-2 — Persistance, durabilité, récupération

**But :** sortir du mode “JSON local” comme hypothèse de production.

### Résultats attendus

- persistance durable abstraite ;
- migrations/versioning du schéma ;
- sauvegarde/restauration et corruption recovery documentés.

### Tâches

- [x] **WS2-T01** — définir le backend de persistance cible du control plane.
- [x] **WS2-T02** — introduire une abstraction de repository/store pour l’état flotte.
- [x] **WS2-T03** — porter enrollment, lifecycle, audit et inventory cache sur cette abstraction.
- [x] **WS2-T04** — créer un chemin de migration depuis l’état JSON existant.
- [x] **WS2-T05** — définir politique de backup/restore du control plane.
- [x] **WS2-T06** — documenter PRA du control plane et tester les restaurations.
- [x] **WS2-T07** — ajouter tests de concurrence, corruption, rollback et reprise après crash.

## WS-3 — Node runtime production-grade

**But :** faire du node-agent un runtime d’exécution réel, pas seulement contractuel.

### Résultats attendus

- backend réel pour actions branding, permissions, hooks, automation, inventory, PRA, maintenance, docker, healthcheck ;
- idempotence, traçabilité, dry-run et rollback partiel ;
- protections de capacité et d’autorisation par action.

### Tâches

- [x] **WS3-T01** — définir le moteur d’exécution local des actions node-agent.
- [x] **WS3-T02** — implémenter backend réel `inventory/refresh`.
- [x] **WS3-T03** — implémenter backend réel `permissions/sync`.
- [x] **WS3-T04** — implémenter backend réel `branding/apply`.
- [x] **WS3-T05** — définir un chemin d’exécution privilégié pour `hooks/install` hors du service node-agent sandboxé.
- [x] **WS3-T06** — définir un chemin d’exécution privilégié pour `automation/install` hors du service node-agent sandboxé.
- [x] **WS3-T07** — implémenter backend réel `pra/snapshot`.
- [x] **WS3-T08** — implémenter backend réel `maintenance/enable` / `disable`.
- [x] **WS3-T09** — implémenter backend réel `docker/compose/apply`.
- [x] **WS3-T10** — implémenter backend réel `healthcheck/run`.
- [x] **WS3-T11** — normaliser le format de résultat, trace, audit, rollback_hint et dry-run.
- [x] **WS3-T12** — ajouter tests sur vraie exécution locale/mock système selon action.

## WS-4 — Sécurité, identité et transport

**But :** finaliser la confiance de bout en bout.

### Résultats attendus

- identité nœud robuste ;
- transport TLS/mTLS cohérent ;
- gestion des secrets et rotation opérables ;
- surface d’attaque minimale.

### Tâches

- [x] **WS4-T01** — finaliser le modèle de trust entre control plane et node-agent.
- [x] **WS4-T02** — industrialiser émission/rotation/révocation des identités nœuds.
- [x] **WS4-T03** — compléter la couche mTLS pour les opérations distantes.
- [x] **WS4-T04** — isoler les secrets par nœud/service/opérateur.
- [x] **WS4-T05** — journaliser tous les événements sécurité critiques.
- [x] **WS4-T06** — renforcer CSRF/auth/session côté Console.
- [x] **WS4-T07** — ajouter tests de skew d’horloge, replay, token reuse, revocation.
- [x] **WS4-T08** — produire un audit de durcissement final par surface.

## WS-5 — Convergence REST / MCP / Console

**But :** garantir une seule plateforme métier exposée via trois interfaces.

### Résultats attendus

- surfaces REST, MCP et Console alignées ;
- aucun contournement direct de logique métier depuis une interface ;
- documentation par surface et par capacité.

### Tâches

- [x] **WS5-T01** — inventorier toutes les capacités métier exposées aujourd’hui.
- [x] **WS5-T02** — définir un catalogue canonique de capacités.
- [x] **WS5-T03** — mapper chaque capacité aux interfaces REST / MCP / Console.
- [x] **WS5-T04** — supprimer les écarts de nommage et de payload.
- [x] **WS5-T05** — faire consommer MCP des services stables pour tous les domaines prioritaires.
- [x] **WS5-T06** — générer une documentation API groupée par surfaces.
- [x] **WS5-T07** — ajouter tests de parité REST ↔ MCP sur jeux de capacités critiques.

## WS-6 — Console opérateur modulaire

**But :** transformer la console en vraie UI d’exploitation.

### Résultats attendus

- navigation claire par domaines ;
- composants réutilisables ;
- accessibilité, sécurité de session et maintenabilité améliorées ;
- vues dédiées adoption, flotte, gouvernance, PRA, sécurité, actions.

### Tâches

- [x] **WS6-T01** — définir l’architecture front modulaire cible.
- [x] **WS6-T02** — extraire les primitives UI réutilisables (modal, table, badge, stat card, alert).
- [x] **WS6-T03** — normaliser navigation, loaders, erreurs et appels API.
- [x] **WS6-T04** — sortir les styles inline restants vers le design system.
- [x] **WS6-T05** — créer vue flotte complète (liste, état, compat, lifecycle).
- [x] **WS6-T06** — créer vue enrollment/adoption/augment.
- [x] **WS6-T07** — créer vue sécurité/gouvernance.
- [x] **WS6-T08** — créer vue PRA / backup / restore.
- [x] **WS6-T09** — créer vue observabilité / alertes / SLA.
- [x] **WS6-T10** — ajouter accessibilité explicite (focus, clavier, contrastes, labels).
- [x] **WS6-T11** — documenter la console comme interface opérateur officielle.

## WS-7 — Packaging, bootstrap, upgrade et release

**But :** industrialiser le cycle de vie du produit supporté.

### Résultats attendus

- packaging aligné avec le produit ;
- chemins fresh/adopt/augment fiables ;
- release versionnée depuis une source unique ;
- upgrades et rollback opérables.

### Tâches

- [x] **WS7-T01** — faire consommer packaging et release scripts la même source de version.
- [x] **WS7-T02** — réduire la logique métier shell au strict bootstrap/distribution.
- [x] **WS7-T03** — brancher bootstrap sur les APIs de service Python pour lifecycle/enrollment.
- [x] **WS7-T04** — compléter les préchecks adoption existants (ports, nginx, certifs, conflits avancés).
- [x] **WS7-T05** — tester les upgrades de version supportée.
- [x] **WS7-T06** — tester les rollback/restore de bout en bout.
- [x] **WS7-T07** — formaliser support boundaries package vs platform.
- [x] **WS7-T08** — industrialiser la release (build, tag, changelog, artefacts).

## WS-8 — Observabilité, gouvernance et exploitation

**But :** rendre Nexora opérable en conditions réelles.

### Résultats attendus

- logs, métriques, événements et alertes cohérents ;
- scoring et gouvernance exploitables ;
- runbooks exhaustifs par scénario.

### Tâches

- [x] **WS8-T01** — normaliser les logs structurés (Control Plane, Node Agent, MCP).
- [x] **WS8-T02** — centraliser les métriques clés par surface.
- [x] **WS8-T03** — implémenter les dashboards opérationnels.
- [x] **WS8-T04** — enrichir `RUNBOOKS.md` (enrollment loss, node failure, restore).
- [x] **WS8-T05** — intégrer alertes et notifications SLA.
- [x] **WS8-T06** — assurer la piste d'audit exportable et intègre.
- [x] **WS8-T07** — permettre une supervision multi-nœuds réelle (état de flotte).

## WS-9 — Multi-tenant, scale et SaaS

**But :** préparer l’extension commerciale finale.

### Résultats attendus

- isolation de tenants solide ;
- plan de scaling du control plane ;
- fonctionnalités de facturation/quotas/organisation au cœur du mode SaaS ;
- gouvernance de données et opérabilité multi-clients.

### Tâches

- [x] **WS9-T01** — définir les modèles d’organisation / tenant / fleet ownership.
- [x] **WS9-T02** — isoler données, secrets, audit et politiques par tenant.
- [x] **WS9-T03** — préparer stratégie de scaling horizontal du control plane.
- [x] **WS9-T04** — définir limites/quotas/entitlements par offre.
- [x] **WS9-T05** — documenter le modèle de support opérateur interne vs offre SaaS abonnée.
- [x] **WS9-T06** — créer plan de conformité et gouvernance données pour SaaS.
- [x] **WS9-T07** — formaliser onboarding client, séparation environnements et offboarding.

## WS-10 — Produit, documentation et go-to-market

**But :** faire converger code, docs et positionnement commercial.

### Résultats attendus

- documentation opérateur-grade ;
- positionnement produit clair ;
- backlog et roadmap continus ;
- readiness commerciale crédible.

### Tâches

- [x] **WS10-T01** — compléter la page de positionnement commercial SaaS abonné (self-hosting interne uniquement).
- [x] **WS10-T02** — maintenir un catalogue documentaire par surface (Node, Control Plane, MCP, Console, package).
- [x] **WS10-T03** — faire évoluer `CHECKPOINTS.md` en miroir de l’avancement réel.
- [x] **WS10-T04** — relier audit code↔docs à chaque passe majeure.
- [x] **WS10-T05** — préparer playbooks de démo, POC, onboarding et support.

---

## 6. Phasage recommandé

## Phase 0 — Consolidation des frontières (court terme)

**Objectif :** terminer la clarification architecture + wiring + documentation.

### Livrables

- packages et adaptateurs rangés dans leurs bons domaines ;
- checkpoints/doc map mis à jour ;
- liste canonique des capacités métier ;
- base de tests de frontières.

### Tâches prioritaires

- [x] P0-T01 — finaliser l’alignement docs ↔ code pour Control Plane / Node / MCP / Console.
- [x] P0-T02 — inventorier les capacités métier existantes.
- [x] P0-T03 — cartographier la logique métier encore présente dans shell/MCP/UI.
- [x] P0-T04 — fixer les conventions de nommage des surfaces.

## Phase 1 — Control plane canonique

**Objectif :** faire passer enrollment/lifecycle/compatibilité derrière des services stables.

### Tâches prioritaires

- [x] P1-T01 — service API canonique enrollment.
- [x] P1-T02 — service API canonique lifecycle.
- [x] P1-T03 — intégration bootstrap ↔ services Python.
- [x] P1-T04 — contrats d’erreur, d’audit et de rollback.
- [x] P1-T05 — tests d’intégration multi-étapes.

## Phase 2 — Node runtime réel

**Objectif :** remplacer les réponses placeholders par de vraies exécutions.

### Tâches prioritaires

- [x] P2-T01 — moteur d’exécution local.
- [x] P2-T02 — implémentation réelle des actions critiques.
- [x] P2-T03 — normalisation dry-run / changed / audit / trace.
- [x] P2-T04 — protections capacités/autorisations.

## Phase 3 — Persistance et sécurité production

**Objectif :** rendre la flotte durable et sûre.

### Tâches prioritaires

- [x] P3-T01 — abstraction de persistance production.
- [x] P3-T02 — migration depuis JSON.
- [x] P3-T03 — PRA/backup/restore control plane.
- [x] P3-T04 — mTLS / rotation / révocation.
- [x] P3-T05 — audits sécurité de bout en bout.

## Phase 4 — Convergence des interfaces

**Objectif :** aligner REST, Console et MCP sur les mêmes capacités.

### Tâches prioritaires

- [x] P4-T01 — catalogue canonique de capacités.
- [x] P4-T02 — parité REST ↔ MCP.
- [x] P4-T03 — console branchée sur surfaces stabilisées.
- [x] P4-T04 — documentation API/operator par surface.

## Phase 5 — Console opérateur modulaire

**Objectif :** faire de la console un vrai poste d’exploitation.

### Phase 5 — Console opérateur modulaire

- [x] P5-T01 — composants UI de base.
- [x] P5-T02 — refonte navigation + loaders + erreurs.
- [x] P5-T03 — vues flotte/adoption/gouvernance/PRA/observabilité.
- [x] P5-T04 — accessibilité et design system.

## Phase 6 — Industrialisation produit

**Objectif :** fiabiliser packaging, upgrades, CI/CD, runbooks et support.

### Phase 6 — Industrialisation produit

- [x] P6-T01 — source unique de version pour packaging + release.
- [x] P6-T02 — upgrade/rollback testés.
- [x] P6-T03 — runbooks exhaustifs.
- [x] P6-T04 — release automatisée.

## Phase 7 — Vision commerciale finale

**Objectif :** durcir l’opération interne récursive pour livrer un SaaS robuste.

### Tâches prioritaires

- [x] P7-T01 — scripts YunoHost (install/remove/upgrade/restore).
- [x] P7-T02 — isolation de données et secrets.
- [x] P7-T03 — scaling horizontal (planifié).
- [x] P7-T04 — entitlements/quotas/support.
- [x] P7-T05 — positionnement commercial finalisé.

## Phase 8 — Hardening commercial final

**Objectif :** Lever les derniers points de friction identifiés lors de l'audit de readiness.

### Tâches prioritaires

- [x] P8-T01 — unification du cycle de vie bootstrap vs package ynh.
- [x] P8-T02 — support installation offline / wheel bundling.
- [x] P8-T03 — extension de la couverture de tests comportementaux (API & idempotence).
- [x] P8-T04 — implémentation du mode "purge" auditable lors de l'uninstall.
- [x] P8-T05 — approfondissement des préchecks d'adoption YunoHost existant (collisions de chemins imbriquées, état nginx, readiness certificats domaine, gate `safe_to_install` côté script).

## Phase 9 — Finalisation SaaS post-audit (livrée)

**Objectif :** clôturer les écarts restants de la trajectoire SaaS souverain sur la base de l'audit directionnel.

### Tâches prioritaires

- [x] P9-T01 — appliquer un scope tenant systématique sur toutes les routes gouvernance/sécurité restantes (lecture + mutation).
- [x] P9-T02 — lier strictement le tenant scope API aux claims d'authentification (au-delà du header) via `X-Nexora-Tenant-Claim` en mode scoped-token.
- [x] P9-T03 — garantir le tagging `tenant_id` de tous les artefacts d'audit/snapshot/export à la création.
- [x] P9-T04 — étendre la matrice de tests d'isolation API (cas cross-tenant sur l'ensemble des surfaces critiques).
- [x] P9-T05 — appliquer `max_apps_per_node` et `max_storage_gb` dans les flux runtime réellement exécutés.
- [x] P9-T06 — exposer un endpoint canonique `usage vs quota` par tenant pour pilotage opérateur/commercial.
- [x] P9-T07 — publier le plan d'industrialisation persistance transactionnelle (SQL + RLS) et ses jalons de migration.

## Phase 10 — Exécution finale post-vision (active)

**Objectif :** convertir les livrables de planification finale en garanties opérationnelles de scale SaaS.

### Tâches prioritaires

- [x] P10-T01 — exécuter J0/J1 de migration SQL/RLS (dual-write + read switch piloté).
- [x] P10-T02 — ajouter un gate CI "vision finale ready" (cohérence docs + persistance SQL + smoke multi-tenant).
- [x] P10-T03 — industrialiser un test de charge multi-tenant long-run avec seuils d'alerte.
- [x] P10-T04 — publier une matrice opérateur vs abonné exhaustive sur les surfaces sensibles.
- [x] P10-T05 — aligner roadmap/checkpoints/master-plan sans divergence de statut.

### Progression déjà livrée sur Phase 9

- `P9-T01` (livré): routes sécurité secondaires alignées tenant-scope (`/api/security/updates`, `fail2ban/*`, `open-ports`, `permissions-audit`, `recent-logins`) avec réponses tenant-aware.
- `P9-T02` (livré): claim HMAC `X-Nexora-Tenant-Claim` exigé quand le mapping token→tenant est activé.
- `P9-T03` (livré): tagging `tenant_id` renforcé sur artefacts de sécurité et événements runtime critiques (`security_audit`, `node_action_events`, snapshots).
- `P9-T04` (livré): matrice d'isolation étendue aux surfaces sécurité secondaires et mutations fail2ban en mode token scope claim.
- `P9-T05` (livré): quotas `max_apps_per_node` et `max_storage_gb` appliqués dans les flux runtime d'enrollment/import.
- `P9-T06` (livré): endpoint canonique `/api/tenants/usage-quota` exposé avec payload `usage`/`limits`/`exceeded` par tenant (scope via `X-Nexora-Tenant-Id`).
- `P9-T07` (livré): plan SQL + RLS publié dans `docs/CONTROL_PLANE_PERSISTENCE.md` avec jalons J0→J3 et gates.

### Passe d’exécution récente (2026-03-24)

- `src/nexora_core/adoption.py` enrichi pour produire `blocking_collisions` + `warnings` et dériver explicitement `safe_to_install`.
- `deploy/bootstrap-adopt.sh` aligné sur ce contrat (blocage d'installation si collisions bloquantes).
- couverture test Deep ajoutée avec `tests/test_adoption_report.py` (happy/error/edge).
- documentation synchronisée (`docs/DEPLOYMENT.md`, `docs/DOC_CODE_AUDIT.md`, `docs/CHANGELOG.md`).

### Passe de continuation (2026-03-24) — P0-T04

- conventions de nommage inter-surfaces formalisées dans `docs/SURFACE_NAMING_CONVENTIONS.md` (capability ids, REST, MCP, Console, payloads).
- master plan mis à jour pour marquer `P0-T04` comme livré.
- traçabilité documentaire alignée via `docs/docs_inventory.yaml` et `docs/CHANGELOG.md`.

### Passe de continuation (2026-03-24) — bloc P8 complet

- support offline/wheel bundling implémenté pour bootstrap et package (`scripts/build_offline_bundle.sh`, installation depuis bundle via `NEXORA_WHEEL_BUNDLE_DIR`).
- couverture de tests comportementaux étendue avec `tests/test_p8_behavioral.py` (API adoption + idempotence import).
- mode uninstall `purge` auditable livré dans `ynh-package/scripts/remove` avec rapport JSON (`/var/log/nexora-uninstall-report.json`).
- documentation d'exploitation ajoutée dans `docs/UNINSTALL.md`.

### Passe complémentaire (2026-03-24) — bug bounty transversal

- correction d'un risque de replay des confirmation tokens (`src/nexora_core/modes.py`) avec consommation one-shot.
- durcissement CSRF sur requêtes mutantes (`src/nexora_core/auth.py`) : `Origin` ou `Referer` désormais obligatoire.
- durcissement du chemin d'installation offline : installation ciblée sur `nexora_platform-*.whl` uniquement.
- artefact d'audit ajouté : `docs/BUG_BOUNTY_2026-03-24.md`.

### Passe de continuation (2026-03-24) — optimisation CI sélective

- ajout d'un job `changes` dans `.github/workflows/ci.yml` pour détecter les modifications code et activer un fast-path docs-only.
- exécution conditionnelle des jobs `test-collection` et `tests` lorsque `code_changed == true`, tout en conservant le gate `docs-quality` systématique.
- contrat de gouvernance CI étendu (`tests/test_ci_guardrails.py`) et documentation synchronisée (`docs/CI_QUALITY_GATES.md`).

### Passe de continuation (2026-03-24) — SaaS tenant-scope hardening

- ajout d'un contrôle optionnel de scope tenant lié au token API (`NEXORA_API_TOKEN_SCOPE_FILE`) dans `TokenAuthMiddleware` : tout `X-Nexora-Tenant-Id` hors scope autorisé est rejeté (`403`).
- tagging `tenant_id` des nouveaux snapshots d'inventaire (`adoption-import`, `heartbeat`, `node-action-inventory-refresh`) pour renforcer l'isolation des artefacts.
- endpoint `/api/governance/snapshot-diff` rendu tenant-aware via filtrage explicite des snapshots.
- surfaces gouvernance renforcées (`/api/scores`, `/api/governance/report`, `/api/governance/risks`, `/api/security/posture`, `/api/pra`) avec inventaire/scoring tenant-aware lorsque `X-Nexora-Tenant-Id` est fourni.
- `security/posture` n'utilise plus l'inventaire global en mode tenant-scopé (permissions lues depuis l'inventaire tenant).
- ajout d'un claim HMAC `X-Nexora-Tenant-Claim` (dérivé du token API) exigé quand un mapping token→tenant est configuré, pour lier cryptographiquement le header tenant au token authentifié.
- couverture de non-régression enrichie (`tests/test_p8_behavioral.py`) sur scope token↔tenant, snapshot diff tenant-aware et denial cross-tenant sur routes gouvernance.
- l'audit directionnel est promu en backlog exécutable via la nouvelle **Phase 9** (tâches `P9-T01` à `P9-T07`).

---

## 7. Dépendances critiques

## Dépendances fonctionnelles

- **P1 dépend de P0** : on ne stabilise pas l’orchestration sans frontières claires.
- **P2 dépend de P1** : le node-agent réel doit être piloté par des services canoniques.
- **P3 dépend de P1** : la persistance cible doit porter les services d’orchestration.
- **P4 dépend de P1 + P2** : la convergence d’interfaces suppose des capacités stables.
- **P5 dépend de P4** : la console modulaire doit se brancher sur des contrats durables.
- **P6 dépend de P1 à P5** : industrialiser avant stabilisation ferait dériver support et upgrade.
- **P7 dépend de P3 à P6** : pas de SaaS crédible sans durabilité, sécurité et opérabilité.

## Dépendances organisationnelles

- l’ADR doit être mise à jour à chaque changement de frontière ;
- chaque phase doit produire au moins un lot de tests d’intégration ;
- chaque passe majeure doit mettre à jour docs + checkpoints + audit code↔docs.
- toute exécution AI-Driven MUST commencer par la lecture explicite et complète de `.agents/instructions/AI_DRIVEN_DEV.md` et `.agents/workflows/nexora-prod-ready.md` (version active), avec traçabilité de cet arbitrage dans le livrable final.

---

## 8. Définition de done par phase

## Done Phase 0

- docs, code et packaging racontent exactement la même architecture ;
- les adaptateurs sont à leur bonne place ;
- les checkpoints sont à jour.

## Done Phase 1

- enrollment/lifecycle passent par les services canoniques ;
- bootstrap n’écrit plus directement les transitions métier critiques ;
- tests d’intégration validés.

## Done Phase 2

- plus aucun endpoint d’action node-agent critique en placeholder ;
- dry-run, changed, trace et audit sont réels ;
- backends locaux testés.

## Done Phase 3

- persistance de production disponible ;
- migration depuis JSON testée ;
- recovery et sécurité de transport validés.

## Done Phase 4

- parité démontrée entre REST, MCP et Console sur les capacités principales ;
- documentation par surface publiée.

## Done Phase 5

- console modulaire, accessible, maintenable ;
- workflows opérateur critiques disponibles.

## Done Phase 6

- packaging, release, upgrade, rollback, runbooks, support industrialisés.

## Done Phase 7

- plateforme opérateur interne mature ;
- extension SaaS abonné possible sans refonte d’architecture ;
- segmentation commerciale finalisée.

---

## 9. Backlog exécutable immédiat

Voici l’ordre recommandé **dès maintenant** pour les prochains cycles :

1. [x] **NEXT-01** — inventorier les transitions métier encore dans les scripts shell.
2. [x] **NEXT-02** — définir le catalogue canonique de capacités métier.
3. [x] **NEXT-03** — brancher bootstrap enrollment/lifecycle sur les services Python.
4. [x] **NEXT-04** — remplacer les actions placeholder du node-agent par un backend réel minimal sur `inventory/refresh`, `permissions/sync`, `healthcheck/run`.
5. [x] **NEXT-05** — choisir et introduire l’abstraction de persistance du control plane.
6. [x] **NEXT-06** — formaliser la parité REST ↔ MCP sur les surfaces fleet/lifecycle.
7. [x] **NEXT-07** — modulariser la Console (navigation, composants, styles inline).
8. [x] **NEXT-08** — finaliser la doc packaging vs platform boundaries.
9. [x] **NEXT-09** — écrire les runbooks manquants pour restore, node perdu, enrollment cassé.
10. [x] **NEXT-10** — préparer la page de positionnement commercial SaaS abonné (self-hosting interne uniquement).
11. [x] **NEXT-11** — unifier le cycle de vie bootstrap/package (Blocker A Readiness).
12. [x] **NEXT-12** — implémenter le mode purge auditable (Blocker D Readiness).
13. [ ] **NEXT-13** — compléter le tenant scope end-to-end sur routes gouvernance/sécurité.
14. [ ] **NEXT-14** — finaliser le binding tenant scope ↔ claims d'auth.
15. [ ] **NEXT-15** — appliquer quotas runtime complets (`max_apps_per_node`, `max_storage_gb`).
16. [ ] **NEXT-16** — exposer reporting `usage vs quota` par tenant.
17. [ ] **NEXT-17** — formaliser le plan SQL/RLS de migration de persistance.
18. [ ] **NEXT-18** — corriger le bug `validate_scoped_secret` (logique post-match hors boucle `for`, risque de bypass auth — S1 audit sécurité 2026-03-26). **[CORRIGÉ dans ce sprint]**
19. [ ] **NEXT-19** — corriger le crash silencieux `purge_tenant_secrets` (`logger` non importé — S2 audit sécurité 2026-03-26). **[CORRIGÉ dans ce sprint]**
20. [ ] **NEXT-20** — ajouter `Content-Security-Policy` dans `SecurityHeadersMiddleware` (S6 audit sécurité 2026-03-26). **[CORRIGÉ dans ce sprint]**
21. [ ] **NEXT-21** — persister le rate-limiting (`_AUTH_FAILURES`) et la replay-detection (`_consumed_tokens`) en base (S3, S4 audit sécurité).
22. [ ] **NEXT-22** — éclater `auth.py` (748 LOC) en sous-modules dédiés : `auth/token.py`, `auth/middleware.py`, `auth/secret_store.py`, `auth/rate_limit.py`.
23. [ ] **NEXT-23** — ajouter jobs linting (`ruff`, `mypy`) et scan de sécurité (`bandit`, `pip-audit`) dans CI.
24. [ ] **NEXT-24** — publier `docs/SUBSCRIBER_GUIDE.md` (bloqueur SaaS D5).
25. [ ] **NEXT-25** — implémentation RLS réelle pour isolation multi-tenant (A1 — multitenant.py stub 68 LOC).

### Artefacts déjà produits pour le backlog immédiat

- `docs/BOOTSTRAP_SERVICE_BOUNDARY_AUDIT.md` couvre **NEXT-01**.
- `src/nexora_core/capabilities.yaml` + `src/nexora_core/capabilities.py` + `GET /api/capabilities` couvrent **NEXT-02**.
- `src/nexora_core/bootstrap.py` + `deploy/bootstrap-*.sh` couvrent **NEXT-03** et le lot **WS1**.
- `src/nexora_core/node_actions.py` + `apps/node_agent/api.py` couvrent **NEXT-04** pour `inventory/refresh`, `permissions/sync` et `healthcheck/run`.
- `src/nexora_core/persistence.py` + `NexoraService.persistence_status()` + `GET /api/persistence` couvrent **NEXT-05**.
- `src/nexora_core/interface_parity.py` + `GET /api/interface-parity/fleet-lifecycle` + les outils MCP fleet alignés couvrent **NEXT-06**.

---

---

## 11. État des Checkpoints (Audit Continu)

Nexora évolue par checkpoints explicites. Chaque item coché `[x]` a été vérifié par audit code↔docs.

### 11.1 Checkpoints Produit (CP)
- [x] **CP-01 — Frontières explicites** : Node / Control Plane / Console / MCP / Value Modules.
- [x] **CP-02 — Enforcements des frontières** : Délégation métier aux services Python, pas de logique MCP isolée.
- [x] **CP-03 — Orchestrateur canonique** : API Control Plane autoritaire, enrollment de bout en bout.
- [x] **CP-04 — Node Runtime Pro** : Backends réels pour actions node (branding, permissions, etc.).
- [x] **CP-05 — Documentation Opérateur** : ADRs, contrats API groupés, limites support vs plateforme.
- [x] **CP-06 — SaaS & Multi-tenancy** : Quotas (apps, storage), isolation par `tenant_id`.
- [x] **CP-07 — Isolation post-audit** : Enforcement du scope tenant sur gouvernance/sécurité.
- [x] **CP-08 — Vision finale** : Persistance SQL (J0/J1), Gate CI vision-ready, matrice d'accès.

### 11.2 Checkpoints Ingénierie (ENG)
- [x] **ENG-01 — Source unique de version** : Constante partagée par app et packaging.
- [x] **ENG-02 — Durabilité de l'état** : Journalisation JSON, politique backup/restore.
- [x] **ENG-03 — Console modulaire** : Primitives UI, navigation normalisée, doc opérateur.

---

## 12. Mode d’utilisation du plan


À chaque reprise de travail :

1. choisir la **première tâche non faite** de la phase active ;
2. implémenter complètement le lot ;
3. mettre à jour les tests ;
4. mettre à jour `docs/CHECKPOINTS.md` ;
5. mettre à jour ce plan si l’ordre, la portée ou les dépendances changent ;
6. créer/mettre à jour un ADR si les frontières d’architecture évoluent.

# Architecture documentaire Nexora

_Dernière mise à jour : 2026-03-24._

## 1) Objectif

Ce document définit la structure professionnelle de la documentation Nexora:

- hiérarchie des documents,
- niveaux d’autorité documentaire,
- règles d’interdépendance,
- cycle de vie (canonique vs snapshot d’audit),
- obligations de maintenance pour les passes AI-Driven.

## 2) Hiérarchie documentaire

## Niveau A — Direction produit & exécution

- `docs/IMPLEMENTATION_MASTER_PLAN.md` (source de pilotage WS/Phases)
- `docs/CHECKPOINTS.md` (état opérationnel synthétique)
- `docs/ROADMAP.md` (cadence et trajectoire)
- `docs/CHANGELOG.md` (traçabilité des livraisons)

## Niveau B — Architecture & contrats

- `docs/ARCHITECTURE.md`
- `docs/RUNTIME_BOUNDARIES.md`
- `docs/API_REFERENCE.md`
- `docs/API_SURFACE_REFERENCE.md`
- `docs/SURFACE_NAMING_CONVENTIONS.md`
- `docs/adr/*.md`

## Niveau C — Opérations & sécurité

- `docs/DEPLOYMENT.md`
- `docs/RUNBOOKS.md`
- `docs/SECURITY.md`
- `docs/CONTROL_PLANE_PERSISTENCE.md`
- `docs/PACKAGING.md`
- `docs/UNINSTALL.md`

## Niveau D — Audits & snapshots datés

Tous les rapports datés (ex: `*_2026-03-24.md`) sont des **snapshots historiques**.
Ils ne sont pas des SoT fonctionnelles; leur validité est bornée à leur date/passe.

## 3) Typologie documentaire

Chaque document `docs/*.md` doit appartenir à l’un des types suivants:

- `canonical`: référence active maintenue en continu;
- `audit_snapshot`: photographie datée d’un état passé.

La classification de référence est portée par `docs/docs_inventory.yaml`.

## 4) Règles d’interdépendance

1. Toute dépendance documentaire doit être explicitée dans `docs/docs_inventory.yaml`.
2. Une dépendance cassée (fichier absent) est bloquante.
3. Une doc canonique ne doit pas s’appuyer uniquement sur un snapshot d’audit.
4. Les décisions d’architecture long terme doivent vivre en ADR (`docs/adr/`).

## 5) Règles de maintenance

Pour chaque PR impactant docs/code/CI:

1. mettre à jour les docs canoniques touchées;
2. mettre à jour `docs/docs_inventory.yaml` si ajout/suppression/renommage;
3. vérifier les tests docs (`tests/test_docs_*`);
4. exécuter `scripts/docs_obsolescence_audit.py --enforce-removal`;
5. marquer les métriques “état courant” avec la valeur recalculée de la branche.

## 6) ADR — convention de gestion

Les ADR dans `docs/adr/` doivent inclure:

- identifiant stable (`000X-*`),
- contexte, décision, conséquences,
- statut (`Accepted`, `Superseded`, `Deprecated`) dans l’en-tête.

Le fichier `docs/adr/README.md` sert d’index opérateur.

## 7) Définition de conformité documentaire

La documentation est considérée conforme si:

- inventaire complet et exact,
- dépendances résolues,
- zéro contenu explicitement obsolète non supprimé,
- checkpoints/master-plan/changelog cohérents entre eux,
- instructions `.agents` alignées avec la structure documentaire active.

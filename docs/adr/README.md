# Architecture Decision Records (ADR)

_Dernière mise à jour : 2026-03-24._

## Objectif

Les ADR tracent les décisions d’architecture structurantes de Nexora:

- pourquoi la décision a été prise,
- quelles alternatives ont été écartées,
- quelles conséquences elle impose sur code/docs/ops.

## Index ADR actifs

| ADR | Sujet | Statut |
|---|---|---|
| [ADR-0001](0001-control-plane-platform.md) | Nexora est une plateforme control-plane | Accepted |
| [ADR-0002](0002-ynh-package-is-distribution.md) | Le package YunoHost est un artefact de distribution | Accepted |
| [ADR-0003](0003-mcp-as-adapter.md) | MCP est un adaptateur d’interface, pas le domaine cœur | Accepted |
| [ADR-0004](0004-shared-version-source.md) | Source de version Python partagée | Accepted |
| [ADR-0005](0005-state-corruption-surfaced.md) | Corruption d’état explicitement surfacée | Accepted |

## Convention de cycle de vie

- **Accepted**: décision active de référence.
- **Superseded**: décision remplacée par une ADR plus récente.
- **Deprecated**: décision encore connue mais non recommandée pour nouveaux développements.

Toute évolution de frontière produit (Node / Control Plane / MCP / Console / Package) doit mettre à jour:

1. ADR concernée,
2. `docs/ARCHITECTURE.md` et/ou `docs/RUNTIME_BOUNDARIES.md`,
3. `docs/docs_inventory.yaml` si le périmètre documentaire change.

# Registre de dette technique

_Dernière mise à jour : 2026-03-26._

## Objectif

Ce registre centralise les dettes techniques actives de Nexora, leur criticité,
leur propriétaire, et leur plan de remboursement.

## Dettes actives (priorisées)

| ID | Domaine | Dette | Criticité | Propriétaire | Échéance cible | Statut |
|---|---|---|---|---|---|---|
| TD-001 | Multi-tenant orchestration | Filtrage tenant incomplet dans les agrégations dashboard/fleet | Haute | Core Platform | 2026-03-27 | **Done** |
| TD-002 | Runtime resilience | Blocs d'exception silencieux (`except ...: pass`) dans surfaces critiques | Haute | Core + MCP | 2026-03-27 | **Done** |
| TD-003 | MCP adapter | Dépendance à des attributs privés de la registry MCP | Moyenne | MCP Layer | 2026-03-24 | **Done** |
| TD-004 | Tests contractuels | Couverture incomplète des scénarios header tenant / isolation API | Moyenne | QA Platform | 2026-03-31 | **Done** |
| TD-005 | CI guardrails | Absence d'un garde-fou dédié anti "silent swallow" | Moyenne | DevEx | 2026-03-31 | **Done** |

## Règles de clôture

Une dette est clôturée seulement si:

1. la correction est mergée,
2. un test de non-régression existe,
3. le changement est tracé dans `docs/CHANGELOG.md`,
4. l'impact CI/documentation est explicitement évalué.

## Notes d'exécution

- Ce registre est aligné avec les exigences Deep (`Doc Inventory`, `gates pass/fail`,
  traçabilité commandes/tests) définies par les politiques agentiques Nexora.
- Les dettes “Planned” doivent être requalifiées en “In progress” ou “Deferred”
  à chaque cycle de revue.

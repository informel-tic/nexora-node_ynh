# Plan: Finalisation complète Nexora

Objectif recommandé : traiter la finalisation en 2 paliers. Le palier 1 ferme la release opérateur supportée de bout en bout (produit exploitable, documenté, testable, relâchable). Le palier 2 ferme la trajectoire SaaS production complète (isolation SQL/RLS réelle, industrialisation multi-tenant, opérations abonné et gouvernance de service). Ce séquencement est cohérent avec l'état actuel du dépôt : la majorité des surfaces produit existent déjà, mais les vrais bloqueurs de complétude sont concentrés dans l'isolation multi-tenant, quelques écarts de parité d'interface, certaines dettes de sécurité/résilience, et la consolidation documentaire/ops.

## Étapes

### Phase 0 — Prérequis

1. **Baseline de clôture et gel des critères de sortie.**
   Définir une check-list de "done" commune à tout le projet à partir de `README`, `ROADMAP`, `IMPLEMENTATION_MASTER_PLAN`, `SECURITY`, `CI_QUALITY_GATES` et `TECH_DEBT_REGISTER`. Sortie attendue : une matrice de complétude unique qui distingue clairement ce qui est requis pour le palier 1 et ce qui reste réservé au palier 2. Cette étape bloque toutes les autres car elle évite de fermer le projet sur des critères contradictoires.

2. **Audit d'écart final contre la baseline.**
   Rejouer l'inventaire des surfaces Control Plane, Node Agent, Console, MCP, packaging, exploitation et docs pour classer chaque gap en : bloquant release opérateur, bloquant SaaS production, ou amélioration post-release. Cette étape dépend de 1 et peut être menée en parallèle sur 4 axes : backend/sécurité, console/parité, packaging/déploiement, docs/ops.

---

### Palier 1 — Release opérateur supportée

3. **Clôture des dettes critiques déjà identifiées.**
   Priorité absolue à `TD-001`, `TD-002`, `TD-004`, `TD-005`, `S3`, `S4`, `S5`, `A1` et `A2`. Ordre recommandé : d'abord fermer le filtrage tenant incomplet et les exceptions silencieuses, ensuite compléter la couverture contractuelle tenant/isolation et le garde-fou CI anti-swallow, puis traiter la persistance des mécanismes de replay/rate-limit et la rotation de token, enfin finaliser la trajectoire SQL/RLS. Cette étape dépend de 2.

4. **Consolidation du socle multi-tenant.**
   Vérifier que `tenant_id` est imposé et testé sur toutes les surfaces REST, MCP, logs, métriques, secrets, agrégations fleet/dashboard/governance et opérations sur nœuds. Le but n'est pas seulement d'avoir des en-têtes, mais une séparation de données réellement prouvée par tests fonctionnels, tests de charge et comportement des middlewares. Cette étape dépend de 3 et conditionne le passage au palier 2.

5. **Durcissement sécurité et auth.**
   Découper le travail en trois sous-lots parallélisables après 3 :
   - a) rendre durables replay detection et rate limiting
   - b) introduire une rotation de token opérable avec runbook et tests
   - c) réduire le risque de régression dans `auth.py` en préparant un refactoring contrôlé vers des sous-modules sans changer le contrat externe.
   Cette étape est nécessaire pour considérer la plateforme comme finalisée et supportable.

6. **Fermeture des écarts d'interface prioritaires.**
   Aligner REST, MCP et Console sur les surfaces critiques à forte valeur opérateur.
   - Priorité palier 1 : garantir la complétude opérateur sur `governance.risks`, proxy REST des `node.actions` côté control plane, et documenter explicitement les surfaces `operator-only`.
   - Priorité palier 2 : compléter les vues console manquantes pour docker, SLA, notifications, storage et hooks, puis résorber les gaps REST/MCP restants sur sécurité et adoption.
   Cette étape peut démarrer en parallèle de 5 si 3 est clos.

7. **Validation réelle des workflows d'exploitation.**
   Exécuter et stabiliser les parcours `fresh`, `adopt`, `augment`, enrollment `pull`, upgrade, rollback, restore PRA, incidents sécurité et surveillance. Le but est de transformer les runbooks en procédures réellement vérifiées et non seulement décrites. Cette étape dépend de 3 pour éviter de valider des workflows sur une base multi-tenant incomplète.

8. **Fermeture packaging, distribution et release.**
   Vérifier la chaîne version unique, artefacts wheel, bundle offline, package YunoHost, scripts de bootstrap, scripts release et frontières operator/subscriber. La sortie attendue est une release opérateur reproductible avec matrice de validation documentée et preuve que les modes `fresh`/`adopt`/`augment` tiennent. Cette étape peut s'exécuter en parallèle de 7.

9. **Documentation de clôture opérateur.**
   Mettre à jour la documentation de vérité pour qu'elle reflète exactement l'état final obtenu : architecture, API surface, sécurité, déploiement, runbooks, changelog, dette restante, guide console, guide abonné, modèle commercial, docs inventory. Il faut supprimer les ambiguïtés entre "fait", "stabilisé", "baseline" et "vision finale", et rendre visible la frontière entre produit opérateur supporté et SaaS production complet. Cette étape dépend de 6, 7 et 8.

10. **Gate Palier 1.**
    Déclarer la release opérateur finalisée seulement si tous les jobs CI requis sont verts, les scénarios e2e opérateur sont rejoués, les dettes bloquantes palier 1 sont fermées, les runbooks critiques sont validés, et la documentation est cohérente sans dérive entre roadmap/master plan/changelog/inventory. Cette étape dépend de 9.

---

### Palier 2 — SaaS production complet

11. **Migration effective vers la persistance SQL/RLS.**
    Dérouler les jalons J0/J1/J2/J3 jusqu'à une isolation réelle par tenant au niveau données. Cela implique lecture/écriture fiables sur backend SQL, activation contrôlée, politiques RLS testées, migration depuis JSON, sauvegarde/restauration SQL, et stratégie de rollback. Cette étape dépend du gate palier 1 si l'on veut sécuriser d'abord la base opérateur, mais peut être préparée techniquement dès 3.

12. **Industrialisation SaaS abonné.**
    Finaliser le mode `subscriber` comme offre exploitable : durcir les frontières de surface, compléter le guide abonné, vérifier les quotas et l'offboarding RGPD, stabiliser les procédures support/escalade, et confirmer que la séparation operator/private vs subscriber/public tient dans les docs, la CI et les artefacts distribués. Cette étape dépend de 11 pour éviter de promettre un SaaS "complet" sans isolation RLS réelle.

13. **Capacité, performance et observabilité de service.**
    Garder les seuils du job `vision-final-ready` au vert, étendre les tests longue durée multi-tenant, vérifier la cohérence de persistance sous charge, consolider les métriques et journaux nécessaires au support de production, et figer les seuils SLO/SLA qui serviront d'engagement interne. Cette étape dépend de 11 et peut se mener en parallèle de 12.

14. **Fermeture des écarts UX et produit secondaires.**
    Compléter les vues console manquantes, améliorer la parité adoption/security/node-actions, et fermer les dernières zones "partial" du référentiel de surface. Cette étape dépend de 12 et 13, car elle ne doit pas prendre le pas sur l'isolation et l'exploitabilité du service.

15. **Gate Palier 2.**
    Déclarer le projet "finalisé complet" uniquement quand la plateforme est à la fois opérable par l'équipe Nexora et défendable comme SaaS souverain multi-tenant en production : isolation RLS effective, documentation abonné/opérateur cohérente, CI verte, charge multi-tenant validée, procédures de support/runbooks fermées, et backlog restant explicitement reclassé en `v2.1+` non bloquant.

---

## Fichiers de référence

| Fichier | Rôle dans la finalisation |
|---------|--------------------------|
| `README.md` | Source de vérité sur la frontière produit, les modes de déploiement et le modèle opérateur/SaaS |
| `docs/ROADMAP.md` | Trajectoire active et file d'exécution phase 10 |
| `docs/IMPLEMENTATION_MASTER_PLAN.md` | Plan directeur existant et points de cohérence à réaligner |
| `docs/TECH_DEBT_REGISTER.md` | Liste priorisée des dettes à fermer avec règles de clôture |
| `docs/SECURITY.md` | Invariants non négociables, dettes S3/S4/S5/A1/A2, responsabilités et limites |
| `docs/CI_QUALITY_GATES.md` | Contrats de validation nécessaires avant toute clôture |
| `docs/API_SURFACE_REFERENCE.md` | Base de travail pour fermer les gaps REST/MCP/Console |
| `docs/RUNBOOKS.md` | Procédures à transformer en workflows réellement validés |
| `docs/DEPLOYMENT.md` | Vérité de déploiement operator-side pour fresh/adopt/augment |
| `docs/SUBSCRIBER_GUIDE.md` | Documentation abonné à compléter et réaligner avec les frontières réelles |
| `apps/control_plane/api.py` | Middlewares, surfaces operator-only, routes tenant-aware, proxys REST à compléter |
| `apps/node_agent/api.py` | Surfaces agent et contrats d'enrollment/actions |
| `src/nexora_core/auth.py` | Auth, scoped secrets, rate limit, replay detection, rotation |
| `src/nexora_core/orchestrator.py` | Agrégations fleet/dashboard et contrôles tenant |
| `src/nexora_core/persistence.py` | Backend de persistance, migration, sauvegarde et reprise |
| `src/nexora_core/multitenant.py` | Point critique à sortir du statut stub pour le palier 2 |
| `src/nexora_core/interface_parity.py` | Matrice de convergence REST/MCP/Console à utiliser comme référence |
| `src/yunohost_mcp/server.py` | Exposition d'outils et garde-fous côté IA |
| `src/yunohost_mcp/policy.py` | Filtrage de politique MCP |
| `deploy/bootstrap-full-platform.sh` | Parcours d'installation à revalider de bout en bout |
| `deploy/bootstrap-node.sh` | Bootstrap nœud — même périmètre de validation |
| `scripts/release.sh` | Chaîne de release complète |
| `scripts/sync_version.py` | Source de version unique |
| `scripts/build_offline_bundle.sh` | Artefact offline pour déploiement restreint |
| `scripts/e2e_operator_matrix.sh` | Preuve de sortie pour fresh/adopt/augment |
| `scripts/load_test_multitenant.py` | Preuve de capacité multi-tenant |
| `tests/test_ci_guardrails.py` | Contrat CI — à garder vert |
| `tests/test_debt_guardrails.py` | Régressions sur dettes actives |
| `tests/test_docs_completeness.py` | Cohérence inventaire documentaire |
| `tests/test_docs_inventory_contract.py` | Contrats de dépendance documentaire |
| `tests/test_persistence_backend.py` | Contrat backend de persistance |
| `tests/test_multitenant_extended.py` | Isolation multi-tenant approfondie |
| `tests/test_ws9_multitenancy.py` | Durcissement Phase 9 multi-tenant |
| `tests/test_p8_behavioral.py` | Matrice operator-only et séparation subscriber |
| `tests/test_load_test_multitenant.py` | Gate de charge multi-tenant |

---

## Vérification

Suite minimale à rejouer avant chaque gate de clôture :

```bash
# 1. Collecte complète
PYTHONPATH=src python -m pytest --collect-only -q

# 2. Cohérence CI/docs
PYTHONPATH=src python -m pytest tests/test_ci_guardrails.py tests/test_docs_completeness.py \
  tests/test_docs_inventory_contract.py tests/test_repo_split_contract.py \
  tests/test_docs_obsolescence_contract.py -q

# 3. Dettes actives et séparation operator/subscriber
PYTHONPATH=src python -m pytest tests/test_debt_guardrails.py tests/test_persistence_backend.py \
  tests/test_multitenant_extended.py tests/test_ws9_multitenancy.py \
  tests/test_p8_behavioral.py tests/test_load_test_multitenant.py -q

# 4. Suite globale
PYTHONPATH=src python -m pytest tests/ -v --tb=short

# 5. Gate de capacité multi-tenant
PYTHONPATH=src python scripts/load_test_multitenant.py \
  --tenants 12 --requests 1500 --workers 24 --duration-seconds 45 \
  --max-failures 0 --max-p95-ms 750

# 6. Matrice e2e opérateur (fresh / adopt / augment)
./scripts/e2e_operator_matrix.sh
```

**Vérification manuelle supplémentaire :**
Rejouer un scénario complet enrollment → fleet lifecycle → PRA restore → incident sécurité → rollback package et consigner les écarts. Vérifier ensuite que roadmap, master plan, changelog, debt register, API surface reference et docs inventory racontent exactement la même vérité de sortie.

---

## Décisions structurantes

- La finalisation est conduite en **2 paliers** : release opérateur supportée, puis SaaS production complet.
- Le périmètre inclut code, sécurité, tests, déploiement, exploitation, documentation opérateur et documentation abonné.
- Le projet ne peut être déclaré "complètement finalisé" tant que `src/nexora_core/multitenant.py` n'est plus un stub et que l'isolation SQL/RLS n'est pas réellement prouvée.
- Les finitions console non critiques passent **après** les travaux multi-tenant, auth, persistance et résilience.
- Tout élément non bloquant une fois le gate palier 2 passé est reclassé explicitement en backlog `v2.1+`.

---

## Recommandations complémentaires

1. **Organisation** : ouvrir un tableau de pilotage avec trois colonnes "Palier 1", "Palier 2", "v2.1+" pour éviter de remélanger bloquants et améliorations.
2. **Gouvernance documentaire** : imposer qu'aucun statut "done" dans la doc ne soit conservé sans preuve testée ou runbook rejoué — sinon la cohérence documentaire restera fragile.
3. **Cadence** : traiter d'abord multi-tenant/auth/persistance en lot serré, puis seulement ensuite les finitions console et packaging secondaire.

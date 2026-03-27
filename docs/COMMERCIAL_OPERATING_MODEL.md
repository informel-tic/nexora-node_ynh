# Nexora — Modèle fonctionnel SaaS vs Subscriber (commercial & marketing)

_Dernière mise à jour : 2026-03-24._

## 1) Positionnement produit

Nexora opère selon une séparation stricte:

- **Côté SaaS opérateur (privé)**: control-plane, console, gouvernance, orchestration multi-tenant, facturation d’usage, politiques avancées.
- **Côté subscriber (public)**: node-agent + enrollment uniquement.

La valeur commerciale centrale reste côté SaaS opérateur; le subscriber runtime est un connecteur d’exécution.

## 2) Modèle de distribution (2 repos)

### Repo privé opérateur

- Contient la plateforme complète (control-plane + console + packaging opérateur).
- Utilisé par l’équipe Nexora pour l’exploitation SaaS et le dogfooding interne.

### Repo public subscriber

- Contient le périmètre client “agent-only”.
- Exclut les artefacts control-plane/console.
- Sert uniquement à connecter des nœuds clients au SaaS Nexora.

## 3) Modèle commercial

### Offre

1. **Abonnement SaaS** (mensuel/annuel) par tenant.
2. **Options**:
   - quota nœuds/apps/stockage,
   - SLA renforcé,
   - support prioritaire,
   - conformité avancée.

### Ce qui est vendu

- exploitation managée,
- gouvernance centralisée,
- sécurité et audit multi-tenant,
- orchestration de flotte à échelle.

### Ce qui n’est pas vendu

- self-hosting complet du control-plane par les subscribers.

## 4) Modèle marketing (GTM)

### ICP cibles

- MSP / infogérants,
- équipes IT PME/ETI,
- opérateurs infrastructures YunoHost multi-sites.

### Messages clés

1. **Souveraineté opérée**: vous gardez vos nœuds, Nexora opère la couche de pilotage.
2. **Moins de risque**: surface critique centralisée, subscribers en agent-only.
3. **Mise en service rapide**: enrollment sécurisé des nœuds via runtime léger.

### Funnel recommandé

1. Démo SaaS control-plane,
2. POC avec 1–3 nœuds subscriber,
3. montée en charge progressive + upsell SLA/compliance.

## 5) Sécurité & conformité orientées business

- séparation operator/subscriber imposée (scope + artefacts),
- tokens tenant-scopés, claims signés, mTLS,
- journal d’audit et traçabilité des actions,
- politique de revocation/rotation comme exigence contractuelle.

## 6) Indicateurs de pilotage commercial

- MRR / ARR par tenant,
- coût d’acquisition et délai POC→prod,
- churn logo & churn revenu,
- nœuds actifs par tenant,
- taux d’adoption des options SLA/compliance.

## 7) Règle de gouvernance non négociable

Toute évolution produit, packaging, documentation et CI doit préserver l’invariant:

> **Le control-plane SaaS complet reste côté opérateur. Le subscriber ne reçoit qu’un agent d’enrollment/exécution.**

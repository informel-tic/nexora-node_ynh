# Runbooks d'Exploitation Nexora

Ce document détaille les procédures opérationnelles pour maintenir et réparer une flotte Nexora.

## Runbook : Récupération d'un Enrollment Échoué
**Symptôme :** Un nœud reste en statut `attested` ou `degraded` après une tentative d'ajout.

### Procédure de diagnostic
1. Vérifier la connectivité : `curl -k https://<node-ip>:38121/api/health`.
2. Consulter les logs du Control Plane : `NEXORA_JSON_LOGS=1 journalctl -u nexora-control-plane`.
3. Vérifier le token : `nexora-cli fleet tokens list`.

### Résolution
1. **Révocation forcée :** Si le nœud est bloqué, révoquer l'ID : `nexora-cli fleet nodes revoke <node-id> --force`.
2. **Nouveau Token :** Générer un token frais : `nexora-cli fleet enroll request --mode pull`.
3. **Ré-attestation :** Relancer le bootstrap sur le nœud cible avec le nouveau token.

---

## Runbook : Réponse aux Incidents de Sécurité
**Symptôme :** Alerte critique de type `token_replay_detected` ou `csrf_violation`.

### Procédure d'urgence
1. **Isolation du Nœud :** Passer le nœud compromis en mode `cordon` pour stopper toute nouvelle tâche.
2. **Audit des Événements :** Exporter le journal HMAC pour analyse : `/api/v1/security/journal/export`.
3. **Rotation des Identités :** Déclencher une rotation immédiate des certificats mTLS : `nexora-cli fleet nodes rotate-credentials <node-id>`.

---

## Runbook : Restauration du Control Plane (PRA)
**Symptôme :** Perte de la base de données de persistance ou corruption du `state.json`.

### Étapes de restauration
1. **Arrêt des Services :** Stopper `nexora-control-plane`.
2. **Identification du Snapshot :** Lister les archives disponibles dans `/opt/nexora/var/backups`.
3. **Restauration Physique :** Remplacer le fichier `state.json` par le snapshot le plus récent : `cp /opt/nexora/var/backups/state_XXXX.json /opt/nexora/var/state.json`.
4. **Validation :** Redémarrer et vérifier l'intégrité de la flotte via `/api/v1/fleet/topology`.

---

## Runbook : Monitoring et Alerting
**Symptôme :** Dérive du score de santé (Health Score < 60).

### Actions recommandées
- Vérifier la liste des services critiques : `/api/v1/health`.
- Contrôler l'espace disque sur les nœuds signalés : `/api/v1/storage/usage`.
- En cas d'alerte persistante, vérifier la configuration SLA dans `sla-data.json`.

---

## Convention : artefacts de test

Pour éviter la pollution de la racine du dépôt et les commits accidentels, la convention suivante est obligatoire :

- **Emplacement autorisé** : tous les artefacts de sortie de tests (rapports texte, dumps, traces) doivent être écrits dans `artifacts/tests/` (ou `.artifacts/tests/` pour un usage local masqué).
- **Racine du dépôt** : il est interdit de déposer des fichiers `test_*` non Python (`.py`) à la racine.
- **Git hygiene** : les répertoires d'artefacts de test et les patterns textuels de rapport (ex. `*.pytest-report.txt`) doivent rester ignorés via `.gitignore`.

Exemple recommandé :

```bash
mkdir -p artifacts/tests
PYTHONPATH=src python -m pytest tests/ -v --tb=short > artifacts/tests/pytest-report.txt
```

---

## Runbook : Validation CI avant PR

**Objectif :** garantir qu'une PR déclenche un pipeline complet sans régression de workflow.

### Vérifications locales minimales
1. Contrat CI : `PYTHONPATH=src python -m pytest tests/test_ci_guardrails.py -q`
2. Documentation : `PYTHONPATH=src python -m pytest tests/test_docs_completeness.py -q`
3. Suite globale : `PYTHONPATH=src python -m pytest tests/ -v --tb=short`

### Politique de merge
- Une PR ne doit pas être fusionnée si un des jobs `test-collection`, `docs-quality` ou `tests` échoue.
- Le job `tests` doit rester dépendant des deux jobs de qualité pour éviter les contournements.
- Toute modification du workflow CI doit inclure la mise à jour de `docs/CI_QUALITY_GATES.md`.

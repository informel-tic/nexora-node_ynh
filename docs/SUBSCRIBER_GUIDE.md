# Guide Abonné Nexora

_Dernière mise à jour : 2026-03-26._

---

## 1. Qu'est-ce que Nexora pour un abonné ?

Nexora est une **plateforme SaaS d'orchestration YunoHost** exploitée par l'opérateur Nexora.  
En tant qu'abonné, vous conservez la propriété et le contrôle de vos serveurs YunoHost. Nexora fournit la **couche de pilotage centralisée** :

- gouvernance de flotte multi-nœuds,
- enrollment sécurisé de vos nœuds,
- audit, scoring et alertes,
- actions opérateur à distance via la Console.

**Ce que Nexora ne fait PAS** : modifier vos applications YunoHost, accéder à vos données utilisateur, ou prendre le contrôle de votre infrastructure sans action opérateur explicite.

---

## 2. Architecture côté abonné

```
Votre infrastructure              Nexora SaaS (opérateur)
     │                                     │
     ▼                                     │
[Serveur YunoHost 1]                       │
  └── Nexora Node Agent ──── enrollment ──►│
[Serveur YunoHost 2]           mTLS        │◄── Console opérateur
  └── Nexora Node Agent ──────────────────►│◄── API REST
[Serveur YunoHost N]                       │◄── MCP / IA
  └── Nexora Node Agent ──────────────────►│
```

Le **Nexora Node Agent** est le seul composant installé sur vos serveurs. Il est léger, en lecture seule par défaut, et n'expose aucune surface réseau externe.

---

## 3. Pré-requis

| Requis | Détail |
|--------|--------|
| YunoHost | Version supportée (voir `compatibility.yaml`) |
| Python | 3.11+ |
| Accès réseau | Port sortant HTTPS vers le control plane Nexora |
| Droits système | `sudo` ou root pour l'installation |

---

## 4. Enrollment d'un nœud

### Étape 1 — Obtenir un token d'enrollment

Depuis la Console Nexora ou l'API :

```bash
curl -X POST https://<control-plane>/api/fleet/enroll/request \
  -H "Authorization: Bearer <votre-token>" \
  -H "X-Nexora-Action: enroll-request" \
  -H "Content-Type: application/json" \
  -d '{"requested_by": "admin", "mode": "fresh", "ttl_minutes": 60}'
```

Réponse :
```json
{
  "enrollment_token": "...",
  "expires_at": "2026-03-26T15:00:00Z"
}
```

### Étape 2 — Installer le Node Agent sur votre serveur

```bash
# Sur votre serveur YunoHost
curl -fsSL https://pkg.nexora.io/install-node-agent.sh | sudo bash
```

Ou via le package YunoHost :

```bash
sudo yunohost app install nexora-node
```

### Étape 3 — Attester l'enrollment

Après installation, le node agent atteste automatiquement son identité :

```bash
# Vérification depuis votre serveur
sudo nexora-agent status
```

### Étape 4 — Vérifier dans la Console

Votre nœud apparaît dans la vue **Fleet** de la Console Nexora avec le statut `enrolled`.

---

## 5. Variables d'environnement du Node Agent

| Variable | Requise | Description |
|----------|---------|-------------|
| `NEXORA_CONTROL_PLANE_URL` | Oui | URL du control plane SaaS |
| `NEXORA_API_TOKEN_FILE` | Oui | Chemin vers le token d'authentification |
| `NEXORA_STATE_PATH` | Non | Répertoire état local (défaut `/opt/nexora/var`) |
| `NEXORA_DEPLOYMENT_SCOPE` | Oui | Doit être `subscriber` |
| `NEXORA_TENANT_ID` | Oui | Identifiant tenant fourni par l'opérateur |

---

## 6. Surfaces API accessibles en mode subscriber

En mode `subscriber`, seules ces routes sont accessibles :

```
GET  /api/health           — santé du service
GET  /api/v1/health        — santé (versionnée)
POST /api/fleet/enroll/attest   — attestation d'enrollment
POST /api/fleet/enroll/register — enregistrement nœud
```

Toutes les autres routes retournent `403 Subscriber deployment scope forbids this route`.

---

## 7. Sécurité

### Ce qui protège votre infrastructure

- **Token scopé par tenant** : votre token ne peut accéder qu'à votre tenant.
- **mTLS** : communications chiffrées entre votre nœud et le control plane.
- **Audit trail** : toutes les actions sont tracées avec horodatage et identifiant opérateur.
- **Aucune clé privée** partagée avec l'opérateur Nexora.

### Bonnes pratiques

- Stockez le token dans `/etc/nexora/api-token` (permissions `0o600`).
- Activez la rotation de token régulièrement (contactez votre gestionnaire de compte).
- Surveillez les logs : `journalctl -u nexora-node-agent -f`.

---

## 8. Quotas et limites

Votre abonnement définit des limites opérationnelles :

| Limite | Description |
|--------|-------------|
| `max_nodes` | Nombre maximum de nœuds enrollés |
| `max_apps` | Nombre maximum d'applications par nœud |
| `max_storage_gb` | Quota de stockage total |

Vérifiez votre usage courant :

```bash
curl -X GET https://<control-plane>/api/tenants/usage-quota \
  -H "Authorization: Bearer <token>" \
  -H "X-Nexora-Tenant-Id: <votre-tenant-id>"
```

Réponse type :
```json
{
  "tenant_id": "votre-tenant",
  "usage": {"nodes": 3, "apps": 12, "storage_gb": 45},
  "limits": {"max_nodes": 10, "max_apps": 50, "max_storage_gb": 100},
  "exceeded": []
}
```

---

## 9. Désinstallation / Offboarding

### Désinstaller le Node Agent

```bash
sudo yunohost app remove nexora-node
```

Ou manuellement :

```bash
sudo systemctl stop nexora-node-agent
sudo pip uninstall nexora-platform
sudo rm -rf /opt/nexora /etc/nexora
```

### Demander la suppression de vos données (GDPR)

Conformément au RGPD, vous pouvez demander la suppression de toutes vos données :

1. Contactez votre gestionnaire de compte Nexora.
2. Une purge complète de votre tenant (`purge_tenant_secrets`, état flotte, logs d'audit) sera exécutée sous 30 jours.
3. Un rapport de purge signé vous sera fourni.

---

## 10. Support et escalade

| Canal | Usage |
|-------|-------|
| Console Nexora — onglet Support | Incidents courants, questions |
| Email support | support@nexora.io |
| Documentation | Ce guide + `docs/RUNBOOKS.md` |
| Urgences SLA | Canal dédié fourni à la souscription |

---

## 11. Glossaire

| Terme | Définition |
|-------|------------|
| **Tenant** | Votre espace isolé dans le SaaS Nexora |
| **Node Agent** | Composant léger installé sur vos serveurs |
| **Control Plane** | Cœur de la plateforme SaaS Nexora (opéré par Nexora) |
| **Enrollment** | Processus d'enregistrement d'un nœud dans votre flotte |
| **Fleet** | L'ensemble de vos nœuds YunoHost gérés |
| **mTLS** | Mutual TLS — authentification mutuelle chiffrée |
| **Token scopé** | Token d'API limité à votre tenant uniquement |

# Modèle de Sécurité Nexora

_Dernière mise à jour : 2026-03-26  audit sprint complet._

---

## 1. Modèle de menace et périmètre

Nexora expose trois surfaces d'attaque principales :

| Surface | Composant | Exposition |
|---------|-----------|------------|
| API REST | `apps/control_plane/api.py` | réseau interne + opérateur |
| Node Agent | `apps/node_agent/api.py` | réseau interne seulement |
| Console opérateur | `apps/console/` | navigateur opérateur |

**Acteurs de confiance reconnus** : `human`, `machine`, `console`, `mcp`
**Rôles opérateur** : `operator`, `admin`, `architect` (accès surfaces sensibles)

---

## 2. Authentification et tokens

### 2.1 Token API principal (`src/nexora_core/auth.py`)

- Chargé depuis fichier (`/etc/nexora/api-token`, `/opt/nexora/var/api-token`) ou généré à la volée via `secrets.token_urlsafe(32)`.
- Stocké avec permissions `0o600`.
- Accepté via `Authorization: Bearer <token>` ou `X-Nexora-Token: <token>`.
- Comparé en temps constant via `secrets.compare_digest` (protection timing attacks).
- Rotation supportée via `rotate_api_token()` avec métadonnées persistées.
- Rotation automatique optionnelle via `NEXORA_API_TOKEN_AUTO_ROTATE_DAYS`.

### 2.2 Scoped secrets per-nœud/service/opérateur (`SecretStore`)

Implémenté dans `src/nexora_core/auth.py`, classe `SecretStore`.

- Scopes valides : `node`, `service`, `operator`.
- Permissions par scope définies dans `SCOPE_PERMISSIONS` (dict statique).
- Token haché (SHA-256) avant stockage sur disque dans `{state_dir}/secrets/{tenant_id}/{scope}/{entity_hash}.json`.
- Chaque fichier : permissions `0o600`, format JSON avec `token_digest`, `expires_at_ts`, `revoked`, `permissions`.
- TTL configurable (défaut 24h).
- Révocation individuelle (`revoke_scoped_secret`) ou purge tenant (`purge_tenant_secrets`).
- **Bug corrigé (S1, 2026-03-26)** : la logique de validation post-match dans `validate_scoped_secret` était hors de la boucle `for record in records`. Toutes les vérifications sont maintenant dans la boucle.

### 2.3 Tenant scope claims

En mode `NEXORA_API_TOKEN_SCOPE_FILE` actif :

```
X-Nexora-Tenant-Id: <tenant-id>
X-Nexora-Tenant-Claim: HMAC-SHA256(token, tenant_id)
```

### 2.4 Replay detection

`_consumed_tokens` dans `SecretStore` (set en mémoire).
Persisté sur disque dans `consumed-token-digests.json` avec purge TTL configurable (`NEXORA_REPLAY_RETENTION_SECONDS`).

---

## 3. Rate limiting

`_AUTH_FAILURES` : `defaultdict(list)` en mémoire, fenêtre glissante 300s, seuil 10 échecs/IP.
État persisté dans un runtime file (`NEXORA_AUTH_RUNTIME_FILE` ou fallback state dir) pour conserver les échecs au redémarrage.

---

## 4. Middlewares de sécurité

### 4.1 `TokenAuthMiddleware`

- Vérifie Bearer token sur toutes les routes non-publiques.
- Compare en temps constant via `secrets.compare_digest`.
- Retour générique sans fuite d'information.

### 4.2 `SecurityHeadersMiddleware`

Headers injectés sur toutes les réponses :

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Cache-Control: no-store
Permissions-Policy: camera=(), microphone=(), geolocation=()
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
                         img-src 'self' data:; font-src 'self'; connect-src 'self';
                         frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

**Ajout S6 (2026-03-26)** : `Content-Security-Policy` ajouté dans ce sprint.

### 4.3 `CSRFProtectionMiddleware`

- Requiert `X-Nexora-Action` sur tout appel mutant (POST/PUT/DELETE/PATCH).
- Valide `Origin` et `Referer` contre le `Host`.

---

## 5. Contrôle d'accès par surface

### 5.1 Surfaces opérateur-only

Bloquées en mode `subscriber` (`NEXORA_DEPLOYMENT_SCOPE=subscriber`) :

```
/api/persistence, /api/docker/*, /api/failover/strategies
/api/storage/*, /api/notifications/*, /api/sla/tiers
/api/hooks/*, /api/automation/*
```

### 5.2 RBAC tenant-aware

- Routes fleet/gouvernance/sécurité filtrent par `X-Nexora-Tenant-Id`.
- Enrollment respecte `tenant_id` sur chaque nœud.
- `/api/fleet/nodes/{node_id}/*` valide l'appartenance tenant du nœud avant action.

---

## 6. Transport et identité TLS

- **mTLS** entre control plane et node-agent via `src/nexora_core/tls.py`.
- Identité nœud par certificat/token scoped (double mode).
- `src/nexora_core/trust.py`, `trust_policy.py` : politique de confiance.
- `src/nexora_core/identity.py`, `identity_lifecycle.py` : émission/rotation/révocation.

---

## 7. Secrets at-rest

- Secrets scoped stockés avec **digest SHA-256** du token (jamais en clair).
- Fichiers `0o600`, répertoires créés avec `mkdir(parents=True)`.
- **Limitation** : pas de chiffrement AES at-rest. LUKS recommandé en production.

---

## 8. Audit trail

- Événements enrollment/lifecycle/actions/governance tracés avec `tenant_id`.
- `src/nexora_core/security_audit.py` produit rapports de posture.
- Export via `/api/governance/snapshot-diff` et `/api/governance/report`.

---

## 9. Profils de policy

| Rôle | Capacités |
|------|-----------|
| `observer` | lecture seule |
| `operator` | maintenance (install, backup, restart) |
| `architect` | changements système (enrollment, lifecycle) |
| `admin` | actions destructives (purge, retire) |

---

## 10. Dettes de sécurité connues (ouvertes)

| ID | Sévérité | Description | Ticket |
|----|----------|-------------|--------|
| A1 | Critique | `multitenant.py` stub, pas d'isolation RLS réelle | NEXT-25 |
| A2 | Haute | SQL désactivé par défaut en persistance | NEXT-17 |

**Corrigés dans ce sprint (2026-03-26)** :

| ID | Fix |
|----|-----|
| S1 | `validate_scoped_secret`  validation dans boucle `for` |
| S2 | `logger` importé dans `purge_tenant_secrets` |
| S3 | Replay detection rendue durable (registre consommé persistant + TTL) |
| S4 | Rate-limiting auth failures rendu durable via runtime file |
| S5 | Rotation token API implémentée (`rotate_api_token` + auto-rotation optionnelle) |
| S6 | `Content-Security-Policy` ajouté dans `SecurityHeadersMiddleware` |
| S7 | `hmac.new()` avec args nommés |

---

## 11. Responsabilité

| Couche | Responsabilité |
|--------|----------------|
| YunoHost Runtime | Réseau, firewall, TLS public, isolation OS |
| Nexora Node Agent | Identité locale, exécution locale |
| Nexora Control Plane | Auth, CSRF, rate-limit, audit, gouvernance |
| Opérateur | Rotation tokens, backup secrets, surveillance |

---

---

## 13. Limites de protection (Root access)

_Dernière mise à jour : 2026-03-24._

### 13.1 Constat technique
Si un client possède un accès **root** sur sa machine, il peut toujours lire les fichiers installés, observer la mémoire et intercepter les appels locaux. Il n’existe pas de mécanisme pour empêcher totalement la copie du code sur une machine rootée.

### 13.2 Stratégie SaaS de protection
Pour protéger la valeur métier et éviter le self-hosting sauvage :
1. **Agent minimal** (`node-agent`) livré côté client.
2. **Logique critique** (orchestration, règles SaaS) conservée côté control-plane opérateur.
3. **Séparation des dépôts** : Privé (operator) vs Public (subscriber).

### 13.3 Best practices opérationnelles
- **Scopes de déploiement** : `NEXORA_DEPLOYMENT_SCOPE=subscriber` sur les agents clients.
- **Réduction d'impact** : Secrets courts, rotation régulière, mTLS systématique.
- **Cadre légal** : Licence et clauses contractuelles anti-réutilisation.

---

---

## 15. Conformité SaaS et Gouvernance des Données

Ce plan assure l'alignement avec le RGPD, SOC2 et les exigences de souveraineté.

### 15.1 Isolation et Rétention
- **Isolation Tenant** : Partitionnement par `tenant_id` au niveau stockage et secrets.
- **RGPD (Droit à l'oubli)** : `NexoraService.purge_tenant_data(tenant_id)` supprime toutes les données liées à un client.
- **Audit Logs** : Rétention par défaut de 365 jours.

### 15.2 Contrôles de Gouvernance
- **Quotas** : Limites de ressources (nœuds, apps, stockage) via `nexora_core.quotas`.
- **RBAC Multi-tenant** : Les opérateurs ne gèrent que les ressources de leur `organization_id`.
- **Souveraineté** : Priorité à l'hébergement sur infrastructure européenne ou hardware souverain.

---

## 16. Contacts sécurité


Voir `docs/BUG_BOUNTY_2026-03-24.md` pour la politique de divulgation responsable.
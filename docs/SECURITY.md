# Nexora Node Agent — Security

## Modèle de menaces

Le Nexora Node Agent fonctionne en mode **subscriber** sur une machine YunoHost tierce. Les risques principaux sont :

| Menace | Mitigation |
|--------|-----------|
| Token d'enrollment intercepté | Token one-time, usage unique, expiré après enrollment |
| Heartbeat falsifié | Authentification par token timing-safe (`secrets.compare_digest()`) |
| Accès non autorisé à l'API agent | Écoute sur `127.0.0.1:38121` uniquement (localhost), nginx proxy auth |
| Escalade via Docker | Docker géré via overlay, conteneurs non-privileged, Watchtower pour patching |
| Données tenant exposées | Isolation `tenant_id` stricte, jamais de données cross-tenant |
| Man-in-the-middle | HTTPS obligatoire vers le control-plane, mTLS si configuré |
| Déni de service local | Rate limiting sur les endpoints, systemd restart-on-failure |

## Invariants de sécurité

### Token comparison
Toute comparaison de token utilise `secrets.compare_digest()` — jamais `==`.

### Permissions fichiers
- Token file : `0o600` (lecture seule par le propriétaire)
- Credentials directory : `0o700`
- Overlay manifest : `0o600`

### Isolation multi-tenant
- Chaque nœud est associé à un seul `tenant_id`
- L'agent ne traite que les commandes pour son propre tenant
- Le heartbeat inclut le `tenant_id` dans chaque rapport

### Docker overlay
- Docker n'est installé que si explicitement demandé (`enable_docker_overlay=true`)
- Le flag `docker_installed_by_nexora` empêche la suppression de Docker pré-existant
- Les conteneurs s'exécutent en mode non-privileged
- Watchtower applique les mises à jour de sécurité automatiquement

### Rollback
- Le rollback est **idempotent** — safe to run multiple times
- Le rollback ne supprime **jamais** les données YunoHost core
- Un rapport JSON détaillé est généré après chaque désinstallation

## Endpoints exposés

| Endpoint | Visibilité | Auth |
|----------|-----------|------|
| `/health` | Nginx proxy (local + remote) | Aucune |
| `/api/fleet/enroll` | Nginx proxy | Enrollment token |
| `/api/heartbeat` | Nginx proxy | Bearer token |
| `/overlay/*` | Localhost uniquement | Bearer token |

## Détection de dérive

Le node agent surveille en continu :
- Intégrité des fichiers système YunoHost
- Packages installés vs baseline
- Ports ouverts non attendus
- Permissions fichiers critiques

Les anomalies sont remontées au control-plane via le heartbeat.

## Gap connu

**S5 — Rotation automatique de tokens** : pas implémentée. Les tokens doivent être régénérés manuellement. Tracé dans le `TECH_DEBT_REGISTER.md` de la branche operator (ref. `NEXT-22`).

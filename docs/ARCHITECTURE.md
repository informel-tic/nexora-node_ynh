# Nexora Node Agent — Architecture

## Vue d'ensemble

```
┌───────────────────────────────────────────────────────────┐
│  Machine Subscriber (YunoHost)                            │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Nexora Node Agent (FastAPI)          :38121         │ │
│  │    ├── /health           → Health check              │ │
│  │    ├── /api/fleet/enroll → Enrollment                │ │
│  │    ├── /api/heartbeat    → Heartbeat reporting       │ │
│  │    ├── /api/actions/*    → Remote actions            │ │
│  │    └── /overlay/*        → Docker overlay mgmt       │ │
│  └──────────┬───────────────────────────────────────────┘ │
│             │                                             │
│  ┌──────────▼───────────────────────────────────────────┐ │
│  │  Overlay Layer (non-destructive)                     │ │
│  │    ├── Docker CE (si installé par Nexora)            │ │
│  │    ├── Docker services (Redis, Grafana, etc.)        │ │
│  │    ├── Nginx snippets (proxy verso Docker)           │ │
│  │    ├── Cron jobs (backups PRA, maintenance)          │ │
│  │    └── Systemd units (services Nexora)               │ │
│  │                                                       │ │
│  │  Manifest: /opt/nexora/overlay/manifest.json         │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  YunoHost Core (JAMAIS modifié)                      │ │
│  │    ├── Applications installées                        │ │
│  │    ├── LDAP / SSO                                    │ │
│  │    ├── Nginx core config                              │ │
│  │    └── Backups YunoHost natifs                        │ │
│  └──────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
           │
           │ HTTPS (heartbeat, enrollment, actions)
           ▼
┌───────────────────────────────────────────────────────────┐
│  Nexora SaaS Control Plane (opérateur)                     │
│    ├── Fleet management                                    │
│    ├── Multi-tenant orchestration                          │
│    ├── Monitoring & alerting                               │
│    ├── PRA tracking                                         │
│    └── Console opérateur                                    │
└───────────────────────────────────────────────────────────┘
```

## Principe fondamental : overlay non-destructif

Toutes les additions de Nexora sur une machine subscriber sont **trackées dans un manifeste** (`/opt/nexora/overlay/manifest.json`). Ce manifeste enregistre :

- Chaque composant installé (type, nom, date, détails)
- Si Docker a été installé par Nexora (`docker_installed_by_nexora`)
- L'état rollback (`rollback_safe`)

Lors du désenrôlement ou de la désinstallation, le **rollback complet** :
1. Arrête et supprime tous les services Docker overlay
2. Supprime les snippets nginx ajoutés
3. Supprime les cron jobs Nexora
4. Supprime les unités systemd Nexora
5. Désinstalle Docker CE (uniquement si installé par Nexora)
6. Nettoie le répertoire overlay

**Résultat** : la machine retrouve son état YunoHost pur d'avant l'enrollment.

## Composants du Node Agent

### Core SDK (`nexora_node_sdk/`)

| Module | Responsabilité |
|--------|---------------|
| `enrollment_client.py` | Gestion de l'enrollment avec le control-plane |
| `heartbeat.py` | Heartbeat périodique (état, inventaire, métriques) |
| `node_actions.py` | Exécution d'actions locales (sync, backup, restore) |
| `docker.py` | Gestion Docker native |
| `overlay.py` | **Gestionnaire d'overlay** — tracking, déploiement, rollback |
| `security_audit.py` | Scoring sécurité, audit CIS |
| `monitoring.py` | Métriques ressources, dérive, alertes |
| `pra.py` | Plan de reprise d'activité — snapshots, restauration |
| `tls.py` | mTLS, certificats, rotation |
| `identity.py` | Identité du nœud, trust policies |
| `persistence.py` | Persistance état local (JSON/SQLite) |

### API Endpoints

#### Santé & Enrollment
- `GET /health` — Health check
- `POST /api/fleet/enroll` — Enrollment initial
- `POST /api/heartbeat` — Rapport périodique

#### Actions à distance
- `POST /api/actions/sync` — Synchronisation
- `POST /api/actions/backup` — Backup
- `POST /api/actions/restore` — Restauration

#### Overlay Docker
- `GET /overlay/status` — État de l'overlay
- `GET /overlay/services` — Services Docker déployés
- `POST /overlay/docker/install` — Installer Docker CE
- `POST /overlay/docker/uninstall` — Désinstaller Docker CE
- `POST /overlay/service/deploy` — Déployer un service Docker
- `POST /overlay/service/remove` — Supprimer un service
- `POST /overlay/rollback` — Rollback complet

## Sécurité

Voir [SECURITY.md](SECURITY.md) pour le modèle de menaces complet.

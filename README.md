# Nexora Node Agent

**Enroll your YunoHost server into the Nexora SaaS platform — with Docker overlay, monitoring, and full rollback support.**

[![CI](https://github.com/informel-tic/nexora-node/actions/workflows/ci-subscriber.yml/badge.svg)](https://github.com/informel-tic/nexora-node/actions/workflows/ci-subscriber.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

---

Nexora Node Agent runs on your YunoHost server and connects it to the [Nexora SaaS control plane](https://github.com/informel-tic/nexora-node). It provides:

- **Automatic enrollment** — install via YunoHost admin or one-line CLI
- **Docker overlay** — deploy Redis, PostgreSQL, Grafana, and more from Docker Hub without touching YunoHost
- **Full rollback** — unenroll to restore pure YunoHost state (Docker + all additions removed)
- **Periodic heartbeats** — health, inventory, and security scoring sent to the control plane
- **Local actions** — sync, backup, restore, branding, Docker operations
- **PRA compliance** — automated daily backup snapshots reported to your operator
- **Security** — mTLS, timing-safe token auth, CIS audit scoring, drift detection

## Quick Install (YunoHost)

```bash
yunohost app install https://github.com/informel-tic/nexora-node \
  --args "domain=node.example.com&path=/nexora-agent&saas_operator_url=https://saas.nexora.io&enrollment_token=YOUR_TOKEN&tenant_id=YOUR_TENANT&enable_docker_overlay=true&monitoring_level=standard"
```

You'll receive your **enrollment token** and **tenant ID** from the Nexora operator after subscribing.

## Alternative: Bootstrap Script

```bash
curl -fsSL https://raw.githubusercontent.com/informel-tic/nexora-node/main/install.sh \
  | ENROLLMENT_TOKEN=xxx CONTROL_PLANE_URL=https://saas.nexora.io TENANT_ID=yyy bash
```

## Requirements

- **YunoHost ≥ 12.1** (Debian 12 Bookworm)
- **Python ≥ 3.11**
- **150 Mo** disk, **150 Mo** runtime RAM
- Network access to the Nexora control plane (HTTPS)

## Architecture

```
┌─────────────────────────────────────────────┐
│  Your YunoHost Server                       │
│                                             │
│  nexora-node-agent (FastAPI :38121)         │
│    ├── enrollment, heartbeat, actions       │
│    └── overlay manager (Docker, nginx,...)  │
│                                             │
│  Docker Overlay (optional)                  │
│    ├── Redis, PostgreSQL, Grafana, etc.     │
│    └── Tracked in overlay/manifest.json     │
│                                             │
│  YunoHost Core (NEVER modified)             │
└──────────┬──────────────────────────────────┘
           │ HTTPS heartbeats + enrollment
           ▼
┌─────────────────────────────────────────────┐
│  Nexora SaaS Control Plane                  │
│  (managed by your operator)                 │
└─────────────────────────────────────────────┘
```

## Docker Overlay

When `enable_docker_overlay=true`, the agent installs Docker CE and can deploy services from Docker Hub. All installations are tracked in `/opt/nexora/overlay/manifest.json` for clean rollback.

Pre-configured templates: Redis, PostgreSQL, MinIO, Grafana, Prometheus, Uptime Kuma, n8n, Plausible, Portainer, Watchtower.

See [docs/OVERLAY.md](docs/OVERLAY.md) for full documentation.

## Unenrollment & Rollback

Removing the app triggers a **complete overlay rollback**:
- All Docker services stopped and removed
- Docker CE uninstalled (if installed by Nexora)
- All nginx snippets, cron jobs, systemd units cleaned
- Machine restored to pure YunoHost state

```bash
yunohost app remove nexora-node
```

## Documentation

| Document | Content |
|----------|---------|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Installation guide (3 methods) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component model, API endpoints |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, auth, isolation |
| [docs/OVERLAY.md](docs/OVERLAY.md) | Docker overlay system |

## Build & Test

```bash
PYTHONPATH=src python -m pytest tests/ -v --tb=short
```

## License

AGPL-3.0-or-later

## Enrollment Flow

1. Subscribe via the operator portal → receive enrollment token
2. Run the install script with your token
3. The node agent starts and sends an attestation to the control plane
4. The control plane validates the token and registers the node
5. Periodic heartbeats begin (inventory, health, metrics)

## Development

```bash
# Run tests
PYTHONPATH=src python -m pytest tests/ -v --tb=short

# Check SDK isolation (no SaaS imports)
python scripts/ci_check_sdk_isolation.py

# Build wheel
python -m build
```

## Security

- Enrollment tokens are one-time use with short expiration (30 min)
- All communication with the control plane uses HTTPS
- Token files are stored with `0600` permissions
- The agent binds to `127.0.0.1` only — not exposed externally
- Token comparison uses timing-safe `secrets.compare_digest()`

## License

AGPL-3.0-or-later

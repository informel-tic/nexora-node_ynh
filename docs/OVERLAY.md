# Nexora Node Agent — Docker Overlay

## Concept

Le Nexora Node Agent peut installer une **surcouche Docker** sur les machines subscribers. Cette surcouche permet d'exécuter des applications Docker Hub (Redis, PostgreSQL, Grafana, Prometheus, etc.) sans impacter YunoHost.

## Fonctionnement

### Installation de Docker

Quand `enable_docker_overlay=true` est configuré :

1. Docker CE est installé via le script officiel (`get.docker.com`)
2. Le flag `docker_installed_by_nexora=true` est enregistré dans le manifeste
3. L'utilisateur Nexora est ajouté au groupe Docker
4. Docker est activé au démarrage (systemd)

### Déploiement de services

Les services Docker sont déployés via **Docker Compose** :

```bash
# Via l'API du node agent
curl -X POST http://127.0.0.1:38121/overlay/service/deploy \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "redis",
    "compose_content": "version: \"3\"\nservices:\n  redis:\n    image: redis:7-alpine\n    ports:\n      - \"6379:6379\"",
    "nginx_snippet": "location /redis-health { proxy_pass http://127.0.0.1:6379; }"
  }'
```

### Services pré-configurés

Le control-plane Nexora SaaS fournit des templates pour :

| Service | Image Docker | Usage |
|---------|-------------|-------|
| Redis | `redis:7-alpine` | Cache, sessions |
| PostgreSQL | `postgres:16-alpine` | Base de données |
| MinIO | `minio/minio` | Stockage objet S3 |
| Grafana | `grafana/grafana` | Dashboards monitoring |
| Prometheus | `prom/prometheus` | Métriques |
| Uptime Kuma | `louislam/uptime-kuma` | Monitoring uptime |
| n8n | `n8nio/n8n` | Automation workflows |
| Plausible | `plausible/analytics` | Analytics web |
| Portainer | `portainer/portainer-ce` | Gestion conteneurs |
| Watchtower | `containrrr/watchtower` | Auto-update conteneurs |

### Manifeste overlay

Toutes les modifications sont enregistrées dans `/opt/nexora/overlay/manifest.json` :

```json
{
  "version": 1,
  "created_at": "2026-01-15T10:30:00+00:00",
  "updated_at": "2026-01-15T11:00:00+00:00",
  "docker_installed_by_nexora": true,
  "rollback_safe": true,
  "components": [
    {
      "kind": "runtime",
      "name": "docker-engine",
      "installed_at": "2026-01-15T10:30:00+00:00"
    },
    {
      "kind": "docker-service",
      "name": "redis",
      "installed_at": "2026-01-15T10:35:00+00:00",
      "detail": {
        "compose_path": "/opt/nexora/overlay/docker/redis.yml"
      }
    }
  ]
}
```

## Rollback complet

Le rollback supprime **toutes** les additions Nexora dans l'ordre inverse :

1. Arrêt et suppression de tous les services Docker
2. Suppression des snippets nginx ajoutés
3. Suppression des cron jobs Nexora
4. Suppression des unités systemd Nexora
5. Désinstallation de Docker CE (**uniquement** si installé par Nexora)
6. Nettoyage du répertoire `/opt/nexora/overlay/`

```bash
# Via l'API
curl -X POST http://127.0.0.1:38121/overlay/rollback \
  -H "Authorization: Bearer $TOKEN"

# Ou via la désinstallation YunoHost
yunohost app remove nexora-node
```

## API Overlay

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/overlay/status` | État global de l'overlay |
| GET | `/overlay/services` | Liste des services Docker |
| GET | `/overlay/docker/status` | État Docker |
| POST | `/overlay/docker/install` | Installer Docker CE |
| POST | `/overlay/docker/uninstall` | Désinstaller Docker CE |
| POST | `/overlay/service/deploy` | Déployer un service |
| POST | `/overlay/service/remove` | Supprimer un service |
| POST | `/overlay/service/stop-all` | Arrêter tous les services |
| POST | `/overlay/nginx/install` | Ajouter un snippet nginx |
| POST | `/overlay/nginx/remove` | Supprimer un snippet nginx |
| POST | `/overlay/cron/install` | Ajouter un cron job |
| POST | `/overlay/cron/remove` | Supprimer un cron job |
| POST | `/overlay/systemd/install` | Ajouter une unité systemd |
| POST | `/overlay/systemd/remove` | Supprimer une unité systemd |
| POST | `/overlay/rollback` | Rollback complet |

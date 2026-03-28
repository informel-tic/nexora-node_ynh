# Nexora Node Agent — Deployment Guide

Guide de déploiement du Nexora Node Agent sur une machine YunoHost subscriber.

## Prérequis

- **YunoHost ≥ 12.1** (Debian 12 Bookworm)
- **150 Mo** d'espace disque minimum
- **Accès réseau HTTPS** vers le control-plane Nexora SaaS
- **Token d'enrollment** + **Tenant ID** fournis par votre opérateur Nexora

## Méthode 1 — Installation via YunoHost Admin

1. Ouvrir l'interface d'administration YunoHost : `https://votre-domaine/yunohost/admin`
2. Aller dans **Applications → Installer**
3. Rechercher **Nexora Node Agent** ou ajouter le catalogue custom
4. Remplir le formulaire d'installation :

| Champ | Description |
|-------|-------------|
| Domain | Domaine pour le node agent |
| Path | Chemin d'accès (défaut : `/nexora-agent`) |
| SaaS operator URL | URL du control-plane Nexora (fourni par l'opérateur) |
| Enrollment token | Token one-time (fourni par l'opérateur) |
| Tenant ID | Identifiant de votre tenant |
| Docker overlay | `true` pour activer Docker (Redis, Grafana, etc.) |
| Monitoring level | `basic`, `standard`, ou `full` |
| Auto-update containers | Watchtower pour les mises à jour Docker |
| Automated backups | Sauvegardes PRA quotidiennes |

5. Cliquer sur **Installer**

## Méthode 2 — Installation en ligne de commande

```bash
# Installer via yunohost CLI
yunohost app install https://github.com/informel-tic/nexora-node \
  --args "domain=node.example.com&path=/nexora-agent&saas_operator_url=https://saas.nexora.io&enrollment_token=YOUR_TOKEN&tenant_id=YOUR_TENANT&enable_docker_overlay=true&monitoring_level=standard"
```

## Méthode 3 — Script bootstrap (sans YunoHost packaging)

```bash
curl -fsSL https://raw.githubusercontent.com/informel-tic/nexora-node/main/install.sh \
  | ENROLLMENT_TOKEN=xxx CONTROL_PLANE_URL=https://saas.nexora.io TENANT_ID=yyy bash
```

## Post-installation

### Vérification du service

```bash
# Status du node agent
systemctl status nexora-node-node-agent

# Logs
journalctl -u nexora-node-node-agent -f

# Health check
curl -s http://127.0.0.1:38121/health
```

### Vérification de l'enrollment

```bash
# État de l'enrollment
curl -s http://127.0.0.1:38121/api/fleet/status

# État de l'overlay
curl -s http://127.0.0.1:38121/overlay/status
```

### Docker overlay (si activé)

```bash
# Containers en cours
docker ps

# Services overlay déployés
curl -s http://127.0.0.1:38121/overlay/services
```

## Mise à jour

```bash
yunohost app upgrade nexora-node
```

## Désinstallation & rollback

La désinstallation effectue un **rollback complet** :
- Suppression de tous les services Docker overlay
- Suppression de Docker CE (si installé par Nexora)
- Nettoyage des cron jobs, snippets nginx, unités systemd
- Restauration de l'état YunoHost pur

```bash
# Suppression avec préservation des données
yunohost app remove nexora-node

# Suppression complète (purge des données)
NEXORA_UNINSTALL_MODE=purge yunohost app remove nexora-node
```

Un rapport JSON est généré : `/var/log/nexora-node-uninstall-report.json`

## Dépannage

| Symptôme | Diagnostic | Solution |
|----------|-----------|----------|
| Agent ne démarre pas | `journalctl -u nexora-node-node-agent` | Vérifier les credentials dans `$data_dir/credentials/` |
| Enrollment échoué | `curl http://127.0.0.1:38121/api/fleet/status` | Vérifier l'URL du control-plane et le token |
| Docker non disponible | `docker version` | Vérifier que `enable_docker_overlay=true` |
| Overlay status vide | `curl http://127.0.0.1:38121/overlay/status` | Docker overlay non activé ou pas de services déployés |

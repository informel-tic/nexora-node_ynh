# Guide de Déploiement Nexora


## Deploy From Fresh Yunohost

# Deploy from a fresh Debian/YunoHost target

## Official sequence

For a YunoHost node on Debian (11.x, 12.x, 13.x target track), Nexora enforces the following sequence:

1. OS prechecks (Debian family only, major track 11/12/13)
2. YunoHost installation
3. YunoHost ↔ Nexora compatibility validation
4. Nexora bootstrap (`control-plane`, `node-agent-only`, or `control-plane+node-agent`)
5. Node attestation and fleet registration

## Recommended command

```bash
MODE=fresh \
PROFILE=control-plane+node-agent \
ENROLLMENT_MODE=pull \
DOMAIN=example.org \
PATH_URL=/nexora \
./deploy/bootstrap-full-platform.sh
```

## Alternative profiles

### Control plane only

```bash
MODE=fresh PROFILE=control-plane ENROLLMENT_MODE=pull DOMAIN=example.org PATH_URL=/nexora ./deploy/bootstrap-full-platform.sh
```

### Node agent only

```bash
MODE=fresh PROFILE=node-agent-only ENROLLMENT_MODE=pull TARGET_HOST=node-01.internal ./deploy/bootstrap-full-platform.sh
```

## What happens

1. `deploy/bootstrap-node.sh` validates OS support, architecture, DNS, network, disk, and time services.
2. YunoHost detection is resilient (`yunohost tools version`, `yunohost --version`, puis `dpkg-query`) before deciding installation/refusal.
3. YunoHost compatibility is assessed against Nexora policy before mutation.
4. A node coherence audit report (`/opt/nexora/var/node-coherence-report.json`) is generated to inventory package versions, node constraints, scope/profile alignment, blockers and adaptation hints.
5. Nexora creates its system user, virtualenv, state directories, and node identity material.
6. Systemd units are enabled according to the selected profile.
7. For profiles exposing the control plane, the local YunoHost package is installed on the requested `domain + path`.

## Logs

Bootstrap steps are appended to:

- `/var/log/nexora/bootstrap-node.log`
- `/var/log/nexora/bootstrap-slo.jsonl` (SLO events: success rate, duration, failure reason)

Quick SLO summary:

```bash
python scripts/bootstrap_slo_summary.py --log /var/log/nexora/bootstrap-slo.jsonl
```


## Deploy On Existing Yunohost

# Deploy Nexora on an existing YunoHost

Nexora supports adoption on a populated YunoHost instance.

## Principles
- inventory first
- no implicit rewrite of existing apps/domains/permissions
- advanced collision checks on `domain + path` (exact + nested path conflicts)
- nginx health precheck in adoption report
- domain certificate readiness warnings in adoption report
- adoption report generated before install
- imported state snapshot stored in Nexora state before augmenting the node
- compatibility validated against `compatibility.yaml`
- explicit bootstrap profile (`control-plane`, `node-agent-only`, `control-plane+node-agent`)

## Dry-run first

```bash
MODE=adopt \
PROFILE=control-plane+node-agent \
ENROLLMENT_MODE=pull \
DOMAIN=example.org \
PATH_URL=/nexora \
./deploy/bootstrap-full-platform.sh
```

This generates:

- `/opt/nexora/var/adoption-report.json`

and **does not install anything yet**.

If blocking collisions are detected (`missing-domain`, `path-already-used`, `path-prefix-conflict`, `nginx-unhealthy`),
bootstrap exits with a failure and suggests a safe alternative path.

## Apply adoption

```bash
MODE=adopt PROFILE=control-plane+node-agent ENROLLMENT_MODE=pull DOMAIN=example.org PATH_URL=/nexora CONFIRM_ADOPT=yes ./deploy/bootstrap-full-platform.sh
```

## Augment an already adopted node

```bash
MODE=augment PROFILE=control-plane+node-agent ENROLLMENT_MODE=pull DOMAIN=example.org PATH_URL=/nexora CONFIRM_AUGMENT=yes ./deploy/bootstrap-full-platform.sh
```

## Agent-only enrollment on an existing node

```bash
MODE=augment PROFILE=node-agent-only ENROLLMENT_MODE=pull TARGET_HOST=node-01.internal ./deploy/bootstrap-full-platform.sh
```

If the requested path is already used, Nexora aborts and prints a suggested free path.

## Recommended flow

1. run in `MODE=adopt`
2. review the adoption report
3. validate compatibility and the suggested install path
4. install on a free path
5. use Nexora Console to observe/import/augment gradually
6. only then enable stronger governance or fleet synchronization


## Offline / restricted-network installation

Nexora peut être installé sans accès Internet en préparant un bundle de wheels.

```bash
./scripts/build_offline_bundle.sh
NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle MODE=augment PROFILE=control-plane+node-agent DOMAIN=example.org PATH_URL=/nexora ./deploy/bootstrap-full-platform.sh
```

Le package YunoHost utilise aussi ce bundle si `NEXORA_WHEEL_BUNDLE_DIR` est défini (ou si `$install_dir/offline-bundle/wheels` existe).
Si un dossier de bundle existe mais ne contient pas `nexora_platform-*.whl`, le bootstrap peut basculer automatiquement en installation online (par défaut) ; forcer le mode strict offline avec `NEXORA_ALLOW_ONLINE_WHEEL_FALLBACK=no`.

### Procédure recommandée pour VM de test non exposée en entrée (upload FTP/SFTP)

Cas visé : VM YunoHost (track 11/12/13) accessible uniquement depuis votre réseau d’exploitation, sans exposition publique entrante.

1. Sur une machine de build (connectée), générer un kit uploadable.
   Par défaut, le kit est **subscriber** (node-agent-only, sans control-plane livré):
   ```bash
   ./scripts/build_vm_offline_kit.sh
   ```
   Pour un kit opérateur interne uniquement:
   ```bash
   KIT_SCOPE=operator ./scripts/build_vm_offline_kit.sh
   ```
   Ce script inclut déjà:
   - le bundle offline (`dist/offline-bundle`) ;
   - un snapshot de repo prêt à extraire sur la VM ;
   - un checksum SHA256 pour vérification avant exécution.

2. Uploader l’archive `dist/vm-offline-kit/*.tar.gz` (et son `.sha256`) vers la VM via FTP/SFTP.

3. Sur la VM:
   ```bash
   sha256sum -c nexora-vm-offline-kit-<timestamp>.tar.gz.sha256
   tar -xzf nexora-vm-offline-kit-<timestamp>.tar.gz
   cd nexora-vm-offline-kit-<timestamp>
   ```

4. Exécuter l’installation en forçant le bundle local (kit subscriber par défaut):
   ```bash
   NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle \
   NEXORA_DEPLOYMENT_SCOPE=subscriber \
   SKIP_NETWORK_PRECHECKS=yes \
   MODE=augment \
   PROFILE=node-agent-only \
   ENROLLMENT_MODE=pull \
   TARGET_HOST=node-01.internal \
   ./deploy/bootstrap-full-platform.sh
   ```
5. Option opérateur interne (control-plane+node-agent) uniquement:
   ```bash
   NEXORA_DEPLOYMENT_SCOPE=operator \
   NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle \
   SKIP_NETWORK_PRECHECKS=yes \
   MODE=adopt \
   PROFILE=control-plane+node-agent \
   ENROLLMENT_MODE=pull \
   DOMAIN=example.org \
   PATH_URL=/nexora \
   ./deploy/bootstrap-full-platform.sh
   ```
   Variante VM interne sans domaine public/externe: omettre `DOMAIN` pour installer seulement les services systemd (control-plane + node-agent) sans exposition YunoHost/nginx.
   ```bash
   NEXORA_DEPLOYMENT_SCOPE=operator \
   NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle \
   SKIP_NETWORK_PRECHECKS=yes \
   MODE=augment \
   PROFILE=control-plane+node-agent \
   ENROLLMENT_MODE=pull \
   TARGET_HOST=vm-operator.internal \
   ./deploy/bootstrap-full-platform.sh
   ```

### Important: portée réelle du mode offline

- Le mode offline couvre l’installation Python (pas de téléchargement pip externe si le bundle est présent).
- Si `DOMAIN` n'est pas fourni avec un profil control-plane, Nexora installe les services mais saute l’installation du package YunoHost (pas d’endpoint nginx `domain + path`).
- Le bootstrap effectue des préchecks réseau externes par défaut (`deb.debian.org`, `repo.yunohost.org`).
- Pour une VM isolée, utiliser `SKIP_NETWORK_PRECHECKS=yes` pour ignorer ces vérifications.
- Recommandation: ne skipper ces préchecks que sur des environnements de test maîtrisés (VM interne), pas pour une production ouverte.

## Checklist VM de test YunoHost (tracks 11/12/13) — SaaS opérateur Nexora

Cette checklist sert à valider rapidement si une VM de test est prête pour un déploiement SaaS Nexora (opérateur interne).

### 1) Préparation VM

- Debian à jour (track 11/12/13 selon la cible supportée, `apt update && apt upgrade`).
- Horloge NTP stable (sinon l’attestation peut dériver).
- DNS fonctionnel vers le domaine cible.
- Ports nécessaires ouverts côté VM/hyperviseur.

### 2) Préchecks obligatoires avant install

1. Lancer le bootstrap en mode simulation `adopt` pour générer le rapport d’adoption.
2. Vérifier l’absence de collisions de chemin (`path-already-used`, `path-prefix-conflict`).
3. Vérifier l’état nginx (`nginx-unhealthy` absent).
4. Vérifier la compatibilité YunoHost ↔ Nexora via `compatibility.yaml`.

### 3) Installation recommandée sur VM de test

- Si VM vierge: séquence `fresh`.
- Si VM déjà utilisée: séquence `adopt` puis `CONFIRM_ADOPT=yes`.
- Pour valider le runtime complet SaaS opérateur: profil `control-plane+node-agent`.

### 4) Validation post-install (go/no-go)

- Services systemd Nexora actifs.
- Endpoint nginx accessible sur le `domain + path` choisi.
- Nœud visible dans la flotte et attestation fonctionnelle.
- Actions non destructives exécutables depuis API/Console (`inventory`, `healthcheck`).
- Exécution d’un `package_check` (install/remove/upgrade/backup_restore) avant diffusion plus large.

### 5) Points encore à faire avant une diffusion SaaS élargie

- Rejouer les scénarios `upgrade` et `rollback/restore` sur la VM (pas seulement l’install initiale).
- Tester explicitement les chemins `fresh`, `adopt`, `augment` sur des états de VM différents.
- Valider les opérations nginx sensibles uniquement sur domaine déjà préparé.
- Valider le scénario offline complet avec upload FTP/SFTP de bundle et installation depuis `NEXORA_WHEEL_BUNDLE_DIR`.

### 6) Rappel de positionnement SaaS

Le self-hosting complet est réservé à l’Opérateur Nexora. Les clients finaux consomment Nexora via l’offre SaaS (abonnement), pas via un déploiement autonome de la plateforme complète.

En distribution package/VM, la surface operator-only est verrouillée par défaut: les routes operator-only exigent un rôle de confiance explicite (`operator`/`admin`/`architect`) via un mapping local root-owned (`/etc/nexora/api-token-roles.json`), initialisé vide à l’installation.

## Modèle recommandé si le SaaS Nexora est exposé en ligne (best practices)

Pour éviter tout glissement vers du self-hosting “plateforme complète” côté client:

1. **Séparer strictement les artefacts**
   - artefact **operator**: control-plane + console (interne Nexora uniquement) ;
   - artefact **client**: agent d’enrôlement/exec (sans console/control-plane exposé).
2. **Forcer le scope de déploiement**
   - `NEXORA_DEPLOYMENT_SCOPE=operator` pour l’infra interne Nexora ;
   - `NEXORA_DEPLOYMENT_SCOPE=subscriber` pour tout runtime client si un control-plane est présent (bloque les surfaces control-plane non autorisées).
3. **Conserver les garde-fous operator-only**
   - `NEXORA_OPERATOR_ONLY_ENFORCE=1` ;
   - `NEXORA_API_TOKEN_ROLE_FILE=/etc/nexora/api-token-roles.json` root-owned, vide par défaut.
4. **Approche client recommandée**
   - imposer `node-agent-only` pour les déploiements clients ;
   - enrôlement vers le control-plane SaaS opérateur, avec token scope tenant + claim HMAC.

### Stratégie Git recommandée (2 dépôts séparés)

- **Repo operator (privé)** : code complet (control-plane + console + packaging opérateur).
- **Repo subscriber (public)** : scope node-agent-only, sans artefacts control-plane.

Export local conseillé avant publication:

```bash
./scripts/export_split_repos.sh
```

Sorties:
- `dist/repo-split/operator-private`
- `dist/repo-split/subscriber-public`

> Important : avec un accès root client, on ne peut pas empêcher totalement la lecture/copie locale du code déployé. La stratégie correcte est de ne pas livrer la logique SaaS critique côté client. Voir `docs/SECURITY.md`.

---

## Packaging YunoHost (Artefact de distribution)

Le paquet YunoHost Nexora est un **artefact de distribution** pour un runtime Nexora supporté.

### Support vs Platform Boundaries
- **Platform Boundaries** : Le cœur métier de Nexora (Core, Agent, Control Plane, MCP) gère le comportement certifié.
- **Support Boundaries** : Les scripts YunoHost (le paquet) gèrent nginx, systemd, l'utilisateur système et le filesystem.

### Responsabilités du paquet
- Cycle de vie : `install`, `upgrade`, `remove`, `backup`, `restore`.
- Aide à l'installation offline via wheel bundle.
- Stratégie d'uninstall `preserve` / `purge`.

---

## Uninstall & Purge Nexora


_Dernière mise à jour : 2026-03-24._

### Modes supportés

Le script `ynh-package/scripts/remove` supporte deux modes explicites :

1. **preserve** (défaut)
   - conserve les données Nexora (`$data_dir`), les exports et les logs,
   - supprime service + config nginx YunoHost,
   - adapté aux suppressions non destructives.
2. **purge**
   - active via `NEXORA_UNINSTALL_MODE=purge`,
   - supprime les données applicatives Nexora (`$install_dir`, `$data_dir`, logs/export),
   - désactive également les unités bootstrap standalone `nexora-control-plane` et `nexora-node-agent` si présentes.

### Rapport auditable d’uninstall

Chaque désinstallation produit un rapport JSON machine-readable :

- chemin : `/var/log/nexora-uninstall-report.json`
- contenu : timestamp, mode, `purge_requested`, `removed_paths`, `preserved_paths`, notes d’exploitation.

### Exemples d'usage

- **Uninstall non destructif** : `yunohost app remove nexora`
- **Uninstall avec purge** : `NEXORA_UNINSTALL_MODE=purge yunohost app remove nexora`

### Garanties de suppression
- Nexora ne supprime pas les données cœur YunoHost.
- Le mode `purge` cible uniquement le périmètre applicatif Nexora.
- Le rapport d’uninstall permet de prouver ce qui a été conservé/supprimé.


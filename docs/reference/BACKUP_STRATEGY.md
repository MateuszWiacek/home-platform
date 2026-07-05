# Backup Strategy

How data is protected in this platform, what's covered, what's not, and what the recovery plan looks like.

For the technical reference (scripts, schedules, variables), see [`VARIABLES.md`](VARIABLES.md).

---

## Backup tiers

Not everything deserves the same level of protection. The tiers are based on one question: **can I recreate this data if it's gone?**

### Tier 1 - Irreplaceable

Data that cannot be recreated. If this is lost, it's lost forever.

| Data | Location | Why it's tier 1 |
|---|---|---|
| Photos library | NAS HDD pool (ZFS) | Family photos, memories. No backup can regenerate these. |
| Documents archive | NAS HDD pool (ZFS) | Scanned legal documents, contracts, certificates. Originals may not exist anymore. |
| Vaultwarden `/data` | NAS SSD pool | Encrypted password vault, TOTP seeds, secure notes. Losing TOTP seeds means losing access to accounts with MFA. Losing secure notes means losing data that may exist nowhere else. This is not "just passwords". |

### Tier 2 - Important

Data that takes real effort to recreate but is not irreplaceable.

| Data | Location | Why it's tier 2 |
|---|---|---|
| Immich PostgreSQL | Ryzen NVMe | Photo metadata, albums, face recognition data. Rebuildable from raw files, but reindexing and re-tagging takes time. |
| Paperless PostgreSQL | Ryzen NVMe | Document metadata, tags, correspondents. Rebuildable from raw files via re-OCR, but manual tagging is lost. |
| Linkwarden PostgreSQL + archived data | Ryzen NVMe | Bookmark metadata, tags, collections, page archives, and screenshots. Rebuildable only by re-crawling saved links. |
| Authentik PostgreSQL | NAS SSD pool | Users, groups, policies, provider configs. Rebuildable from scratch, but reconfiguring SSO across all services is a full day of work. |
| Authentik assets | NAS SSD pool | Custom branding, icons, templates. Low effort to recreate, but annoying. |
| AdGuard Home state | NAS SSD pool | Local DNS rewrites, resolver config, stats, and query state. Rebuildable, but annoying and easy to misconfigure. |
| SiYuan workspace | Ryzen NVMe | Notes and assets. Treat as important if actively used. |
| Mealie data | Ryzen NVMe | Recipes and meal planning state. Small and worth backing up. |

### Tier 3 - Replaceable

Data that can be recreated from code, config, or re-setup with minimal effort.

| Data | Source of truth | Recovery path |
|---|---|---|
| App configurations | Ansible roles + group_vars | Redeploy from repo |
| Container images | Public registries | `docker compose pull` |
| Navidrome / Audiobookshelf / Calibre-Web DBs | Local app state + archwright app-state backups | Re-scan media libraries if the app-state backup is unavailable |
| Syncthing identity/config | Local app state + archwright app-state backups | Restore device identity/config or reconnect devices manually |
| Jellyfin metadata | NAS SSD pool + archwright app-state backups | Re-scan media library if the app-state backup is unavailable |
| Traefik ACME state | NAS SSD pool + archwright app-state backups | Restore `acme.json` or re-issue certificates |
| AI model caches (Immich ML) | Public model repos | Re-downloaded on first run |

---

## What is backed up today

| Data | Method | Schedule | Retention | Destination |
|---|---|---|---|---|
| AdGuard Home state | archwright (file collection) | Daily 02:05 | 7 archives | NAS SSD pool |
| Traefik ACME state | archwright (file collection) | Daily 02:10 | 7 archives | NAS SSD pool |
| Jellyfin config + watched state | archwright (file collection) | Daily 02:20 | 7 archives | NAS SSD pool |
| Vaultwarden SQLite + files | archwright (SQLite `.backup` + file collection) | Daily 02:30 | 7 archives | NAS SSD pool |
| Authentik assets | archwright (file collection) | Daily 02:40 | 7 archives | NAS SSD pool |
| Authentik PostgreSQL | archwright (`docker_postgres`) | Daily 02:50 | 7 archives | NAS SSD pool |
| Immich PostgreSQL | archwright (`docker_postgres`) | Daily 03:00 | 28 archives | NAS SSD backup dataset |
| Paperless PostgreSQL + app data | archwright (`docker_postgres` + file collection) | Daily 03:10 | 28 archives | NAS SSD backup dataset |
| Linkwarden PostgreSQL + archived data | archwright (`docker_postgres` + file collection) | Daily 03:20 | 28 archives | NAS SSD backup dataset |
| Mealie app data | archwright (file collection) | Daily 03:30 | 28 archives | NAS SSD backup dataset |
| SiYuan workspace | archwright (file collection) | Daily 03:40 | 28 archives | NAS SSD backup dataset |
| Navidrome state | archwright (file collection) | Daily 03:50 | 28 archives | NAS SSD backup dataset |
| Audiobookshelf config + metadata | archwright (file collection) | Daily 04:00 | 28 archives | NAS SSD backup dataset |
| Calibre-Web config | archwright (file collection) | Daily 04:10 | 28 archives | NAS SSD backup dataset |
| Syncthing config + identity | archwright (file collection) | Daily 04:20 | 28 archives | NAS SSD backup dataset |
| Photos library | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |
| Documents archive | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |
| App configs | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |

### Backup tooling

One backup tool, deployed on both nodes:

**archwright** (Python, config-driven) - file collection + SQLite dumps + Docker PostgreSQL dumps:
- Vaultwarden: SQLite `.backup` (hot, safe on live DB) + config files + attachments
- AdGuard, Traefik, Jellyfin: small NAS-side app state that is annoying to rebuild
- Authentik assets: branding, icons, custom templates
- Authentik PostgreSQL: local `docker exec pg_dump` on NAS
- Immich, Paperless, Linkwarden PostgreSQL: local `docker exec pg_dump` on Ryzen
- Paperless app data and Linkwarden archived data: file collection alongside DB dumps
- Mealie, SiYuan, Navidrome, Audiobookshelf, Calibre-Web, Syncthing: Ryzen-side app state
- Runs on both nodes via per-job systemd timers
- Manual CLI usage goes through the host-local wrapper in `archwright_config_dir`
- NAS manual runs should use `sudo`; Ryzen manual runs should use `sudo -u backup` because the NFS backup mount is owned by that runtime user
- Atomic ZIP archives with rotation (keep_last 7 on NAS, 28 on Ryzen)
- Config files: `roles/archwright/templates/archwright/`

---

## What is NOT backed up

Being explicit about gaps is more useful than pretending they don't exist.

| Data | Why not | Risk |
|---|---|---|
| Immich photo originals | Too large for ZIP archives; protected by ZFS snapshots, cold storage, and cloud | High if the non-archwright copies are stale. Keep 3-2-1 current. |
| Paperless document archive | Too large for ZIP archives; protected by ZFS snapshots, cold storage, and cloud | High if the non-archwright copies are stale. Keep 3-2-1 current. |
| Media libraries | Source data lives on NAS media datasets, not in app containers | Low for app rebuilds, high only if NAS/off-site copies fail. |
| Immich thumbnails, ML model cache, Redis caches | Regenerable cache data | Low. Rebuild/re-download after restore. |
| Portainer, Dozzle, monitoring time-series, Excalidraw, utility tools | Low-value or redeployable state | Low. Add dedicated jobs only if these become important. |
| Ntfy cache/history | Mostly transient notification data | Low. Config is generated from Ansible. |

---

## Off-site / 3-2-1 status

The 3-2-1 rule: 3 copies, 2 different media types, 1 off-site.

**Current state for tier 1 data (photos, documents, Vaultwarden vault):**
- ✅ Original data on NAS (ZFS pools)
- ✅ Cold storage on external physical drive (offline, separate location)
- ✅ Cloud backup (encrypted, off-site)
- ✅ **3-2-1 satisfied.** Three copies, two media types (NAS + external drive + cloud), one off-site (cloud).

For tier 1 data, I recommend keeping copies in three physically separate places. A NAS with ZFS snapshots protects against accidental deletion and bit rot, but it does not protect against hardware failure, fire, or theft. An external drive (cold storage) in a different location covers the physical loss scenario. Cloud backup covers the "entire building is gone" scenario. All three together mean that losing tier 1 data requires three independent failures.

**Tier 2 and 3 data:**
- ✅ DB backups on NAS SSD backup dataset (same box, separate backup path)
- ✅ ZFS snapshots protect against accidental deletion
- ⚠️ No off-site copy for tier 2 data. Acceptable - these databases are rebuildable from raw files or repo.

Tier 2 and 3 data does not need the same protection level. If the NAS dies, databases can be rebuilt from raw files (photos, documents) and app configs can be redeployed from the Ansible repo.

---

## Recovery targets

Not an SLA - just honest expectations for how much data I can lose and how long recovery takes.

| Tier | RPO (how much data lost) | RTO (how long to recover) | Notes |
|---|---|---|---|
| Tier 1 - photos/docs | Up to 24h (ZFS snapshot interval) | Hours (ZFS rollback, cold storage, or cloud restore) | 3-2-1 covered: NAS + cold storage + cloud |
| Tier 1 - Vaultwarden | Up to 24h (daily archwright backup) | Minutes (archwright restore) | Automated daily, plus cold storage + cloud |
| Tier 2 - databases | Up to 24h (daily archwright backup) | 30-60 min per DB (restore + verify) | Straightforward `pg_restore` from `docker_postgres` dumps |
| Tier 2/3 - app state | Up to 24h (daily archwright backup) | Minutes to hours | Restore small app-state ZIPs or rebuild from raw libraries |
| Tier 3 - app configs | Zero (in git) | Minutes to hours (ansible deploy) | Full redeploy from repo |
| Tier 3 - replaceable DBs | Full loss acceptable | Varies (re-scan, re-index) | Media files are the source of truth |

---

## Restore procedures

### PostgreSQL databases (Linkwarden tested)

archwright archives contain config files and `pg_dump --format=custom` dumps. `archwright restore` handles the config files. The database dump needs manual `pg_restore` because loading into a live container is provider-specific.

This example uses Linkwarden because that restore path has already been tested. Other `docker_postgres` jobs follow the same pattern, but they stay out of the tested list until they get their own drill.

```bash
# List available archives (example: Linkwarden on Ryzen)
sudo -u backup /opt/backups/archwright/archwright list --config /opt/backups/archwright/linkwarden-db.yml

# Preview what archwright would extract
sudo -u backup /opt/backups/archwright/archwright restore \
  --config /opt/backups/archwright/linkwarden-db.yml \
  --archive /mnt/nas_backup/archwright/linkwarden-db/<archive>.zip \
  --dry-run

# Restore config files
sudo -u backup /opt/backups/archwright/archwright restore \
  --config /opt/backups/archwright/linkwarden-db.yml \
  --archive /mnt/nas_backup/archwright/linkwarden-db/<archive>.zip \
  --overwrite

# Extract the dump from the archive
sudo -u backup unzip /mnt/nas_backup/archwright/linkwarden-db/<archive>.zip \
  "databases/*" -d /tmp/db-restore/

# Restore into the container
sudo docker exec -i linkwarden_db pg_restore \
  --username linkwarden --dbname linkwarden --clean \
  < /tmp/db-restore/databases/linkwarden_db/*.dump

# Clean up
rm -rf /tmp/db-restore
```

For Authentik (runs on NAS, uses `sudo`), the same pattern applies - see [Authentik disaster recovery](../operations/INCIDENT_RESPONSE.md#authentik-disaster-recovery-full-restore) for the full procedure.

### Vaultwarden (via archwright)

```bash
# List available backups
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright list --config /mnt/example_apps/appdata/docker/config/archwright/vaultwarden.yml

# Dry run - see what would be restored
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright restore \
  --config /mnt/example_apps/appdata/docker/config/archwright/vaultwarden.yml \
  --archive /mnt/example_apps/backup/archwright/vaultwarden/<archive>.zip \
  --dry-run

# Stop Vaultwarden, restore, start
cd /mnt/example_apps/appdata/docker/config/vaultwarden
sudo docker compose down
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright restore \
  --config /mnt/example_apps/appdata/docker/config/archwright/vaultwarden.yml \
  --archive /mnt/example_apps/backup/archwright/vaultwarden/<archive>.zip \
  --overwrite
sudo docker compose up -d
```

### Vaultwarden (manual, from cold storage)

```bash
# If archwright backups are unavailable, restore from cold storage / cloud
cd /mnt/example_apps/appdata/docker/config/vaultwarden
sudo docker compose down
sudo cp -a /path/to/backup/vaultwarden/data /mnt/example_apps/appdata/docker/config/vaultwarden/data
sudo docker compose up -d
```

### ZFS snapshot rollback (photos, documents)

```bash
# List available snapshots
zfs list -t snapshot | grep <dataset>

# Rollback (destroys all changes after the snapshot)
zfs rollback <pool>/<dataset>@<snapshot>
```

> ZFS rollback is destructive - everything after the snapshot is gone. For selective file recovery, mount the snapshot read-only and copy individual files instead.

---

## Restore testing

A backup that has never been tested is not a backup. It's a hope.

| Test | Last tested | Result | Notes |
|---|---|---|---|
| Vaultwarden archwright restore | 2026-03-22 | PASS | Restored on a fresh VM, test container started, HTTP `200`, SQLite schema non-empty |
| Linkwarden PostgreSQL restore | 2026-03-22 | PASS | Restored on a fresh VM into a disposable PostgreSQL container, schema non-empty |
| Authentik assets archwright restore | - | - | No restore drill yet; job may legitimately produce no archive when assets are empty |
| ZFS snapshot file recovery | - | - | |

> Fill this in after each restore test. Even testing once gives more confidence than never testing.

---

## Known gaps and TODOs

- [x] Automate Vaultwarden backup (archwright - SQLite + files, daily)
- [x] Automate Authentik assets backup (archwright - file collection, daily)
- [x] Move PostgreSQL backups into archwright (`docker_postgres`) on NAS and Ryzen
- [x] Add small app-state backups for AdGuard, Traefik, Jellyfin, Paperless, Linkwarden, Mealie, SiYuan, Navidrome, Audiobookshelf, Calibre-Web, and Syncthing
- [ ] Schedule periodic restore tests (at least once per quarter)
- [ ] Add archwright web UI/control-plane deployment after the GUI branch is cleaned up and tested
- [ ] Decide whether Ntfy, Portainer, monitoring state, or Stirling PDF config need archwright jobs

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
| Linkwarden PostgreSQL | Ryzen NVMe | Bookmark metadata, tags, and collections. Archived page content still lives outside the DB. |
| Authentik PostgreSQL | NAS SSD pool | Users, groups, policies, provider configs. Rebuildable from scratch, but reconfiguring SSO across all services is a full day of work. |
| Authentik media | NAS SSD pool | Custom branding, icons. Low effort to recreate, but annoying. |

### Tier 3 - Replaceable

Data that can be recreated from code, config, or re-setup with minimal effort.

| Data | Source of truth | Recovery path |
|---|---|---|
| App configurations | Ansible roles + group_vars | Redeploy from repo |
| Container images | Public registries | `docker compose pull` |
| Navidrome / Audiobookshelf / Calibre-Web DBs | Local app state | Re-scan media libraries |
| SiYuan / Excalidraw / Mealie / Linkwarden archive data | App-level storage | Accept loss or restore from manual export if available |
| AI model caches (Immich ML) | Public model repos | Re-downloaded on first run |

---

## What is backed up today

| Data | Method | Schedule | Retention | Destination |
|---|---|---|---|---|
| Immich PostgreSQL | `pg_dump` via `backup_dbs.sh` | Daily 03:00 | 28 days | NAS fast data pool |
| Paperless PostgreSQL | `pg_dump` via `backup_dbs.sh` | Daily 03:00 | 28 days | NAS fast data pool |
| Linkwarden PostgreSQL | `pg_dump` via `backup_dbs.sh` | Daily 03:00 | 28 days | NAS fast data pool |
| Authentik PostgreSQL | `pg_dump` via SSH (optional) | Daily 03:00 | 28 days | NAS fast data pool |
| Photos library | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |
| Documents archive | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |
| App configs | ZFS snapshots (TrueNAS) | TrueNAS snapshot schedule | Per TrueNAS config | Same pool (local snapshots) |

### Backup tooling

Current: bash script (`backup_dbs.sh`), cron-scheduled, with gzip compression.

Future: a Python backup module is in active development. The goal is to replace the bash script with something more robust - structured config, proper error handling, rotation logic, and testability. It started as a single-file utility but has grown into a proper module. It will be published as a separate repo once stable. Even with AI assistance, backup tooling is critical enough that it requires careful, deliberate work.

---

## What is NOT backed up

Being explicit about gaps is more useful than pretending they don't exist.

| Data | Why not | Risk |
|---|---|---|
| Vaultwarden `/data` | Covered by cold storage + cloud, but no automated script | **Medium.** Off-site copies exist, but backup frequency depends on manual discipline. Automating this is a priority. |
| Authentik media | Low priority | Low. Custom branding, easily recreated. |
| SiYuan notes | No export automation | Medium if actively used. Consider periodic manual export. |
| Mealie / Excalidraw / Linkwarden archive data | No backup script | Low to medium. Accept loss or add manual exports. |
| Navidrome / Audiobookshelf / Calibre-Web DBs | Replaceable via library re-scan | Low. Media files are the source of truth, not the DB. |

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
- ✅ DB backups on NAS fast data pool (same box, different pool)
- ✅ ZFS snapshots protect against accidental deletion
- ⚠️ No off-site copy for tier 2 data. Acceptable - these databases are rebuildable from raw files or repo.

Tier 2 and 3 data does not need the same protection level. If the NAS dies, databases can be rebuilt from raw files (photos, documents) and app configs can be redeployed from the Ansible repo.

---

## Recovery targets

Not an SLA - just honest expectations for how much data I can lose and how long recovery takes.

| Tier | RPO (how much data lost) | RTO (how long to recover) | Notes |
|---|---|---|---|
| Tier 1 - photos/docs | Up to 24h (ZFS snapshot interval) | Hours (ZFS rollback, cold storage, or cloud restore) | 3-2-1 covered: NAS + cold storage + cloud |
| Tier 1 - Vaultwarden | Up to last cold storage / cloud sync | Hours (restore `/data` dir) | Automate backup frequency to reduce RPO |
| Tier 2 - databases | Up to 24h (daily pg_dump) | 30-60 min per DB (restore + verify) | Straightforward pg_restore |
| Tier 3 - app configs | Zero (in git) | Minutes to hours (ansible deploy) | Full redeploy from repo |
| Tier 3 - replaceable DBs | Full loss acceptable | Varies (re-scan, re-index) | Media files are the source of truth |

---

## Restore procedures

### PostgreSQL databases (Immich, Paperless, Linkwarden, Authentik)

```bash
# Find the backup
ls -lh /mnt/nas_fast_data/backups/db/ | tail -10

# Restore (example: Immich)
gunzip < /mnt/nas_fast_data/backups/db/immich_YYYY-MM-DD.sql.gz | docker exec -i immich_postgres psql -U immich -d immich
```

### Vaultwarden

```bash
# Stop the container
cd /mnt/example_apps/appdata/docker/config/vaultwarden
sudo docker compose down

# Restore the /data directory from backup
sudo cp -a /path/to/backup/vaultwarden/data /mnt/example_apps/appdata/docker/config/vaultwarden/data

# Start the container
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
| Immich pg_dump restore | - | - | |
| Paperless pg_dump restore | - | - | |
| Linkwarden pg_dump restore | - | - | |
| Vaultwarden `/data` restore | - | - | |
| ZFS snapshot file recovery | - | - | |

> Fill this in after each restore test. Even testing once gives more confidence than never testing.

---

## Known gaps and TODOs

- [ ] Automate Vaultwarden backup to match tier 1 protection level (currently manual)
- [ ] Schedule periodic restore tests (at least once per quarter)
- [ ] Enable Authentik remote backup (requires SSH setup between nodes)
- [ ] Evaluate whether SiYuan/Mealie/Linkwarden archive data needs backup automation based on actual usage
- [ ] Publish Python backup module once stable

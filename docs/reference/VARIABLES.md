# Variables and Secrets

Variable map, secrets reference, backup coverage, and infrastructure config.

---

## Infrastructure

| Node | IP | OS | Role | Ansible group |
|---|---|---|---|---|
| NAS | 10.0.0.10 | TrueNAS SCALE | Core + media services | `n100` |
| Ryzen VM | 10.0.0.30 | Debian (Proxmox VM) | Docker host + apps, tools, books, notes, and collaboration services | `docker_nodes` |
| Proxmox | 10.0.0.20 | Proxmox VE | Hypervisor (hosts Ryzen VM) | *(unmanaged by Ansible)* |

Common paths on NAS:
- NAS SSH: `admin@10.0.0.10`
- Ryzen SSH: `admin@10.0.0.30`
- `docker_config_dir`: `/mnt/example_apps/appdata/docker/config`
- `docker_data_dir`: `/mnt/example_apps/appdata/docker/data`
- Domain: `homelab.local`

---

## Variable map

| File | Contains |
|---|---|
| `group_vars/all.yml` | Domains, NAS IP, shared ports/endpoints, per-service auth modes |
| `group_vars/n100.yml` | Paths (`docker_config_dir`, `docker_data_dir`), image tags, compatibility toggles |
| `group_vars/docker_nodes.yml` | Docker node SSH user, NFS source paths, mount points, prod app versions |
| `roles/prod_apps/defaults/main.yml` | Default stack layout for Immich/Paperless/backups |
| `secrets.yml` | `cert_email`, `cloudflare_token`, `authentik_*`, app DB passwords, OIDC client secrets, widget tokens, `vault_siyuan_access_code`, Linkwarden secrets |

---

## Backups

Full backup strategy, tiers, restore procedures, and recovery targets: [`BACKUP_STRATEGY.md`](BACKUP_STRATEGY.md).

Backup-related variables:
- `db_backup_retention_days` in `roles/prod_apps/defaults/main.yml`
- `enable_authentik_remote_backup`, `nas_backup_ssh_user`, `nas_backup_ssh_key_path` in `roles/prod_apps/defaults/main.yml` (override in inventory only if needed)

---

## Docker log rotation

### Ryzen node

Docker daemon on the Ryzen VM is configured with log rotation via `/etc/docker/daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

This limits each container's log to 3 files of 10MB each (30MB max per container). Without this, the default `json-file` driver has no size limit and will eventually fill disk. The playbook merges these keys into an existing `daemon.json` instead of overwriting unrelated Docker daemon settings.

### NAS (TrueNAS SCALE)

Docker daemon is managed by TrueNAS. Log rotation is handled at the TrueNAS level. If logs grow unexpectedly:
```bash
ssh admin@10.0.0.10 "sudo du -sh /var/lib/docker/containers/*//*.log | sort -rh | head -10"
```

# Variables and Secrets

Variable map, secrets reference, backup coverage, and infrastructure config.

---

## Infrastructure

| Node | IP | OS | Role | Ansible group |
|---|---|---|---|---|
| NAS | 10.0.0.10 | TrueNAS SCALE | Core + media services | `n100` |
| Ryzen VM | 10.0.0.30 | Debian (Proxmox VM) | Docker host + apps, tools, books, notes, and collaboration services | `docker_nodes` |
| Proxmox | 10.0.0.20 | Proxmox VE | Hypervisor (hosts Ryzen VM) | *(unmanaged by Ansible)* |

Common paths and mounts:
- NAS SSH: `admin@10.0.0.10`
- Ryzen SSH: `admin@10.0.0.30`
- `docker_config_dir`: `/mnt/example_apps/appdata/docker/config`
- `docker_data_dir`: `/mnt/example_apps/appdata/docker/data`
- `archwright_backup_dir`: `/mnt/example_apps/backup/archwright`
- `nas_source_backup`: `/mnt/example_apps/backup`
- `mnt_backup`: `/mnt/nas_backup`
- Domain: `homelab.local`

---

## Variable map

| File | Contains |
|---|---|
| `group_vars/all.yml` | Domains, NAS IP, shared ports/endpoints, feature toggles, per-service auth modes |
| `group_vars/n100.yml` | Paths (`docker_config_dir`, `docker_data_dir`), image tags, compatibility toggles |
| `group_vars/docker_nodes.yml` | Docker node SSH user, NFS source paths, mount points, app versions, monitoring stack versions |
| `roles/prod_apps/defaults/main.yml` | Default stack layout for Immich/Paperless/backups |
| `roles/monitoring_stack/defaults/main.yml` | Monitoring stack layout, retention, memory caps |
| `secrets.yml` | `cert_email`, `cloudflare_token`, `authentik_*`, app DB passwords, OIDC client secrets, widget tokens, `vault_siyuan_access_code`, Linkwarden secrets, Grafana admin password |

---

## Backups

Full backup strategy, tiers, restore procedures, and recovery targets: [`BACKUP_STRATEGY.md`](BACKUP_STRATEGY.md).

Backup-related variables:
- `archwright_config_dir`, `archwright_cli_path`, `archwright_backup_dir`, `archwright_keep_last` in `roles/archwright/defaults/main.yml` (override in `group_vars/n100.yml` and `group_vars/docker_nodes.yml` per host)
- `archwright_source_mode`, `archwright_source_archive_url`, `archwright_local_source_dir` in `roles/archwright/defaults/main.yml` control whether archwright is pulled from its public repo or copied from a local checkout
- `archwright_jobs` defined per host in `group_vars/n100.yml` and `group_vars/docker_nodes.yml` (defaults to empty list in `roles/archwright/defaults/main.yml`)
- `archwright_run_user`, `archwright_run_group` in `group_vars/docker_nodes.yml` for NFS-safe writes into the backup dataset
- `nas_source_backup`, `mnt_backup` in `group_vars/docker_nodes.yml` for the Ryzen-side NFS mount into the NAS backup dataset

---

## Monitoring

Monitoring is controlled by `monitoring_enabled` in `group_vars/all.yml`. It is enabled in the current repo state, but still kept behind one flag in case the whole stack needs to be disabled cleanly.

Feature toggle and shared endpoints:
- `monitoring_enabled` in `group_vars/all.yml`
- `dozzle_enabled` in `group_vars/all.yml`
- `grafana_domain`, `grafana_service_port`, `prometheus_service_port`, `alertmanager_service_port` in `group_vars/all.yml`
- `grafana_auth_mode`, `dozzle_auth_mode` in `group_vars/all.yml`

Image tags:
- `node_exporter_version`, `cadvisor_version` in `group_vars/n100.yml`
- `smartctl_exporter_version` in `group_vars/n100.yml`
- `node_exporter_version`, `cadvisor_version`, `prometheus_version`, `grafana_version`, `alertmanager_version` in `group_vars/docker_nodes.yml`

SMART and NAS-critical settings:
- `smartctl_exporter_enabled` in `group_vars/n100.yml`
- `smartctl_exporter_port`, `smartctl_exporter_poll_interval`, `smartctl_exporter_rescan_interval` in `roles/monitoring_exporters/defaults/main.yml`
- `nas_apps_pool_warning_percent`, `nas_apps_pool_critical_percent`, `nas_media_pool_warning_percent`, `nas_media_pool_critical_percent` in `roles/monitoring_stack/defaults/main.yml`
- `smartctl_temperature_warning_celsius`, `smartctl_temperature_critical_celsius` in `roles/monitoring_stack/defaults/main.yml`

Secrets:
- `vault_grafana_admin_password` in `secrets.yml`

Provisioned dashboards:
- shipped from `roles/monitoring_stack/files/grafana/dashboards/`
- templated NAS dashboard from `roles/monitoring_stack/templates/grafana/dashboards/`
- loaded by Grafana file provisioning on deploy

Reference:
- [`MONITORING_STACK.md`](MONITORING_STACK.md)

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

# Version Drift Checker

Detects outdated Docker image versions by comparing pinned tags in `group_vars/` against latest GitHub releases.

---

## Why

Every service in this repo has a pinned version. When upstream ships a security fix or a new feature, there is no built-in signal that tells you. This script is that signal.

---

## What it does

1. Reads all `*_version` variables from `group_vars/*.yml`, tracking **per-file values** so that `--host nas` reports the NAS file's version, not Ryzen's.
2. For each tracked service, queries the GitHub Releases API for the latest stable (non-prerelease) tag. Requests run **in parallel** (8 threads) and shared repos are deduplicated (e.g. Loki + Promtail = 1 request to `grafana/loki`).
3. Normalizes version strings (strips `v`, `version/` prefixes, extracts upstream version from LinuxServer compound tags).
4. Compares current vs latest.
5. Checks coupled services (Loki/Promtail, Dozzle/dozzle_agent) for version drift.
6. Optionally writes latest versions back to `group_vars/` files (`--write`), using each file's actual value for the regex match.
7. Optionally pushes a summary to ntfy.
8. Optionally outputs JSON for scripting (`--json`).
9. Optionally caches GitHub responses to a file (`--cache`) to save API calls.

---

## Files

| File | Purpose |
|---|---|
| `scripts/version-check.py` | The script (single file, ~940 lines) |
| `config/version-check.yml` | Service registry: maps variables to GitHub repos |
| `tests/test_version_check.py` | Unit tests (49 tests) |

---

## Usage

Basic report:

```bash
./scripts/version-check.py
```

Only NAS or only Ryzen services (host-specific files like `n100.yml` take precedence over shared `all.yml`):

```bash
./scripts/version-check.py --host nas
./scripts/version-check.py --host ryzen
```

Check specific services only:

```bash
./scripts/version-check.py --only grafana,loki
./scripts/version-check.py --only traefik
```

Silent mode (output only when updates exist, useful for cron):

```bash
./scripts/version-check.py --quiet
```

Push results to ntfy (fires when updates, drift, or errors exist):

```bash
./scripts/version-check.py --notify
```

Combined (weekly cron):

```bash
./scripts/version-check.py --quiet --notify
```

Higher GitHub API rate limit (60/h unauthenticated, 5000/h with token):

```bash
GITHUB_TOKEN=ghp_... ./scripts/version-check.py
```

Ntfy authentication (when ntfy has auth enabled):

```bash
# Token auth (env var takes priority over config)
NTFY_TOKEN=tk_... ./scripts/version-check.py --notify

# Or configure in config/version-check.yml:
#   ntfy:
#     url: "https://ntfy.homelab.local"
#     topic: "homelab-updates"
#     token: "tk_..."            # access token
#     # OR basic auth:
#     user: "admin"
#     password: "secret"
```

Machine-readable JSON (for scripting or piping to `jq`):

```bash
./scripts/version-check.py --json
./scripts/version-check.py --json --only grafana | jq '.services[0].latest'
```

Cache GitHub responses (avoids API rate limits on repeated runs):

```bash
# First run: fetches from GitHub and saves to file
./scripts/version-check.py --cache /tmp/vc.json

# Second run: reads from cache, zero API calls
./scripts/version-check.py --cache /tmp/vc.json

# Refresh: delete the cache file and re-run
rm /tmp/vc.json && ./scripts/version-check.py --cache /tmp/vc.json
```

---

## Reading the output

```text
OK  navidrome               0.60.3            up to date
UP  grafana                 11.6.0            -> v12.4.1
!!  some_service            v1.0.0            rate limited
--  excalidraw              no pinned version
```

| Prefix | Meaning |
|---|---|
| `OK` | Current version matches latest release |
| `UP` | Update available |
| `!!` | Error (rate limit, network, no releases) |
| `--` | Skipped (no pinned version or set to `latest`) |

Exit codes:

- `0` - everything up to date, no drift
- `1` - updates available, coupled drift, or errors

---

## Writing versions back (`--write`)

The `--write` flag updates `group_vars/` files in place with the latest upstream versions. Use `--dry-run` to preview changes without modifying files.

```bash
./scripts/version-check.py --write --dry-run   # preview
./scripts/version-check.py --write              # apply
```

**Multi-file awareness:** some variables (e.g. `promtail_version`, `node_exporter_version`, `cadvisor_version`) are pinned in both `group_vars/n100.yml` and `group_vars/docker_nodes.yml`. The script tracks each file's actual value independently, so even if the two files have diverged (e.g. NAS at `3.4.0` and Ryzen at `3.5.0`), both are updated correctly to the latest version.

**Quoting style is preserved:** double-quoted (`"3.5.0"`), single-quoted (`'3.5.0'`), and bare values (`v1.9.0`) all keep their original style after the update.

**LinuxServer images are skipped** by `--write` because the upstream GitHub tag does not match the Docker image tag (e.g. Jellyfin's GitHub tag is `v10.12.0` but the LinuxServer Docker tag is `10.12.0ubu2404-ls21`). These require manual updates.

---

## Coupled version drift

Some services share the same upstream release and must stay in sync:

| Group | Shared repo |
|---|---|
| `loki` + `promtail` | `grafana/loki` |
| `dozzle` + `dozzle_agent` | `amir20/dozzle` |

If these pairs are pinned to different versions, the script prints a warning before the main report:

```text
Coupled Version Drift:
  * loki (3.4.0) != promtail (3.5.0) - should be same version
```

---

## LinuxServer images

Some services use LinuxServer images with compound tags like `10.11.6ubu2404-ls20`. The `extract` field in the config strips the suffix so only the upstream version is compared:

```yaml
jellyfin:
  github: jellyfin/jellyfin
  variable: jellyfin_version
  extract: '([\d.]+)'
```

This extracts `10.11.6` from `10.11.6ubu2404-ls20` and compares it against Jellyfin's GitHub release tag.

---

## Adding a new service

Edit `config/version-check.yml`:

```yaml
services:
  my_new_app:
    github: owner/repo          # GitHub owner/repo
    variable: my_new_app_version  # Ansible variable name
    host: ryzen                 # nas, ryzen, or both
    # Optional:
    extract: '([\d.]+)'        # Regex to extract version from compound tag
    coupled_with: [other_svc]  # Services that must share the same version
    note: "Shown when update is available"
```

The script picks up the new entry on the next run. No code changes needed.

To add a custom group_vars file, use the explicit format in the `group_vars` section:

```yaml
group_vars:
  - group_vars/all.yml                          # host inferred from filename
  - path: group_vars/custom.yml                 # "path" key is required
    host: nas                                   # nas, ryzen, or both
```

---

## Intentionally skipped services

These are not tracked and require manual checks:

| Service | Reason |
|---|---|
| `excalidraw` | Pinned to `latest` - no version to compare |
| `it_tools` | Date-based tags (`2024.10.22-7ca5933`) - no semver releases |
| `*_postgres_image` | Infrastructure dependency - update on a separate cadence |
| `*_redis_image` | Infrastructure dependency - update on a separate cadence |

---

## Cron setup

Weekly check with ntfy notification:

```bash
# /etc/cron.d/version-check
0 8 * * 1  admin  cd /path/to/hybrid-workstation-setup && ./scripts/version-check.py --quiet --notify 2>&1 | logger -t version-check
```

Subscribe to the `homelab-updates` topic in the ntfy app to receive push notifications.

---

## Dependencies

- Python 3.10+
- PyYAML (`pip install pyyaml` - already present if Ansible is installed)
- No other dependencies. Uses only stdlib `urllib` for HTTP.

---

## Where this fits

```text
group_vars/*.yml
      |
      v
scripts/version-check.py  -->  ntfy (homelab-updates topic)
      ^
      |
config/version-check.yml
      ^
      |
GitHub Releases API
```

Related docs:

- [Monitoring Stack](MONITORING_STACK.md) - Prometheus, Alertmanager, Grafana, Loki
- [Variables](VARIABLES.md) - all Ansible variables including version pins
- [Deploy Commands](DEPLOY_COMMANDS.md) - how to apply version bumps

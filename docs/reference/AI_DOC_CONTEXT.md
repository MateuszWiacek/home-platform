# AI Documentation Context

Internal briefing for future AI sessions.

Purpose: avoid re-reading the whole repo before every run.
This file is a cache, not a source of truth. If it conflicts with code or docs, trust the code or docs.

Last reviewed: 2026-03-22
Reviewed against: `README.md`, `ARCHITECTURE.md`, `DESIGN_PHILOSOPHY.md`, docs under `docs/identity`, `docs/operations`, `docs/setup`, and `docs/reference`, plus `group_vars/*.yml`, `smoke_test.yml`, `roles/archwright/`, and `roles/prod_apps/`.

---

## Current Snapshot

- `main` is the operational source of truth.
- `publication` is the anonymized/public-safe export branch. Do not assume it matches `main` line-for-line.
- Two-node split is the backbone of the whole repo:
  - NAS / TrueNAS = control plane + storage
  - Ryzen VM = heavier app and monitoring workloads
- Monitoring is enabled in the repo (`monitoring_enabled: true`).
- Live auth on `main`:
  - ForwardAuth: AdGuard, Portainer, Homepage, Excalidraw, IT-Tools, Stirling-PDF, Grafana
  - Native OIDC: Immich, Paperless
  - Most other apps still local
- Authentik Postgres is intentionally hardened:
  - `max_connections=50`
  - memory limit `512M`
  - `shm_size: 256m`
- Monitoring stack now includes:
  - SMART monitoring for the NAS
  - Authentik Postgres exporter
  - `Authentik Health` Grafana dashboard
  - alert rules for queue/channel pressure
- Grafana is behind Traefik ForwardAuth, but the repo does not configure native Grafana OIDC.

---

## What Is Strong

- README is now a strong landing page without losing practical repo value.
- `ARCHITECTURE.md` is clear on node split, storage placement, and traffic flow.
- `DESIGN_PHILOSOPHY.md` explains trade-offs in a way that matches the actual system.
- `docs/identity/AUTH_MODEL.md` and `AUTH_ROLLOUT.md` form a useful target-vs-rollout pair.
- `docs/operations/INCIDENT_RESPONSE.md` is operationally valuable, not just descriptive.
- `docs/operations/NON_TECHNICAL_RECOVERY.md` is one of the strongest proof points in the repo.
- `docs/setup/COMMON_ISSUES.md` is practical and now covers the Authentik failure modes that actually happened.
- `docs/reference/MONITORING_STACK.md` reflects the real monitoring scope and dashboards.
- `docs/reference/BACKUP_STRATEGY.md` is honest about what is and is not protected.

---

## High-Value Clarifications

- Do not rewrite the README into generic portfolio fluff. The current tone is deliberate and already good.
- `AUTH_MODEL.md` is not pure target-state anymore. It contains current live auth-mode values too. For real rollout status, still cross-check:
  - `docs/identity/AUTH_ROLLOUT.md`
  - `group_vars/all.yml`
- Do not re-flag Linkwarden DB backup as missing. It is already handled by `archwright` on the Ryzen node.
- Monitoring is intentionally small by design:
  - no Loki
  - no Promtail
  - no Blackbox
  - no `ntfy`
- Alertmanager still has no external notification receiver. Alerts exist, but delivery is UI-only for now.
- `smoke_test.yml` is useful, but it is still a smoke test:
  - container presence
  - basic endpoint reachability
  - not full app-level functional verification
- Some docs intentionally use real LAN IPs and the real domain on `main`. Do not "fix" that there unless the user explicitly wants anonymization.

---

## Authentik Incident Note (March 2026)

This is worth remembering because it was the main real incident in this repo recently.

### What happened

- `authentik-worker` ran hot for a long time
- task queue grew above 100k
- `django_channels_postgres_message` filled with expired rows
- earlier on, Authentik Postgres also hit OOM and needed reindex/cleanup work

### What the real root cause was

Not just "big queue".

The real issue was stale memberships in the shared group for the embedded proxy outpost in `django_channels_postgres_groupchannel`.

That caused logout/session-end work to fan out into dead channels, which kept re-filling `django_channels_postgres_message` and stopped the worker from catching up cleanly.

### What actually fixed it

In order:

1. Fix Postgres limits and shared memory pressure
2. Reindex if corruption errors appear
3. Clean expired channel rows
4. Inspect `django_channels_postgres_groupchannel`
5. Prune stale memberships from the oversized embedded outpost shared group
6. Only then consider narrow task purges for old backlog

### Where this is documented

- `docs/setup/COMMON_ISSUES.md`
- `docs/operations/INCIDENT_RESPONSE.md`
- `docs/reference/MONITORING_STACK.md`
- `docs/reference/sql/authentik_maintenance.sql`

### Monitoring added because of this

The first place to look now is the `Authentik Health` dashboard.

It tracks:

- queued tasks total
- queued tasks by actor
- expired channel messages
- total channel messages
- largest channel group
- oldest logout queue age
- Authentik container CPU and memory
- session counts

---

## Real Gaps Still Open

1. Vaultwarden backup automation is still manual.
   - Off-site copies exist, but the automated path is not done yet.

2. Restore testing evidence is still missing.
   - The restore table in `docs/reference/BACKUP_STRATEGY.md` is still empty.

3. Alert delivery is not finished.
   - Alertmanager runs, but there is no external receiver yet.

4. Some lower-priority app data is still accepted as manual-export or best-effort backup territory.
   - This is documented honestly, but it is still a gap if usage grows.

---

## Quick Review Paths

Use the shortest path that matches the task.

### If asked for portfolio / landing page review

1. `docs/reference/AI_DOC_CONTEXT.md`
2. `README.md`
3. `ARCHITECTURE.md`
4. `DESIGN_PHILOSOPHY.md`

### If asked about auth / SSO

1. `docs/reference/AI_DOC_CONTEXT.md`
2. `docs/identity/AUTH_MODEL.md`
3. `docs/identity/AUTH_ROLLOUT.md`
4. `group_vars/all.yml`
5. `docs/identity/FORWARDAUTH_SETUP.md` or `docs/identity/OIDC_SETUP.md`

### If asked about incidents / runtime debugging

1. `docs/reference/AI_DOC_CONTEXT.md`
2. `docs/operations/INCIDENT_RESPONSE.md`
3. `docs/setup/COMMON_ISSUES.md`
4. `docs/reference/MONITORING_STACK.md`
5. `docs/reference/sql/authentik_maintenance.sql`

### If asked about backups / recovery

1. `docs/reference/AI_DOC_CONTEXT.md`
2. `docs/reference/BACKUP_STRATEGY.md`
3. `docs/operations/NON_TECHNICAL_RECOVERY.md`
4. `docs/reference/VARIABLES.md`
5. `roles/archwright/templates/archwright/`

### If asked what is live right now

1. `group_vars/all.yml`
2. `group_vars/n100.yml`
3. `group_vars/docker_nodes.yml`
4. `smoke_test.yml`

---

## One-Line Summary

The docs are mature and credible. The remaining weak spots are operational proof and a few unfinished automation edges, not understanding of the system.

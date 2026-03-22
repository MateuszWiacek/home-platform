# Monitoring Stack

What is deployed, what each component does, and where to look when something feels off.

---

## Scope

The monitoring stack covers metrics, logs, alerting, and notifications:

- `node_exporter` on NAS and Ryzen
- `cadvisor` on NAS and Ryzen
- `smartctl_exporter` on NAS
- `Promtail` on NAS and Ryzen
- optional `Dozzle agent` on NAS
- `Prometheus` on Ryzen
- `Loki` on Ryzen
- `Alertmanager` on Ryzen
- `Grafana` on Ryzen
- optional `Dozzle` on Ryzen
- `ntfy` on NAS

Not included:

- `Blackbox` - no external HTTP/TLS probing yet

The stack is still small but covers the full loop: metrics, logs, alerts, and delivery to your phone.

---

## Topology

### NAS

- `node_exporter`
- `cadvisor`
- `smartctl_exporter`
- `Promtail` - ships container logs to Loki on Ryzen
- optional `Dozzle agent` - exposes Docker socket for live log viewing
- `ntfy` - push notification server

### Ryzen

- `node_exporter`
- `cadvisor`
- `Promtail` - ships container logs to Loki (localhost)
- `Prometheus`
- `Loki` - log aggregation and search
- `Alertmanager`
- `Grafana`
- optional `Dozzle` - real-time log viewer (connects to local Docker + NAS agent)

Reasoning:

- exporters and Promtail are lightweight and run on both hosts
- scrape, alerting, log storage, and dashboards live on the Ryzen node
- ntfy runs on NAS so it stays available even when Ryzen is down for maintenance
- Grafana is exposed through Traefik by default; Dozzle is opt-in in the public branch because it requires a direct host port on the Ryzen node

---

## What each component does

### `node_exporter`

Host metrics:

- CPU
- memory
- load
- disks
- filesystems
- network

### `cadvisor`

Container metrics:

- per-container CPU
- per-container memory
- restart/runtime stats
- OOM-related container signals

### `Prometheus`

The metrics engine:

- scrapes exporters
- stores time series locally
- evaluates alert rules

### `Loki`

Log aggregation:

- receives log streams from Promtail instances on both hosts
- stores logs locally with 7-day retention
- queryable from Grafana via Explore

### `Promtail`

Log shipper:

- discovers all Docker containers via Docker socket
- tails container logs and ships them to Loki
- labels each log line with container name, service, and host
- runs on both NAS and Ryzen

### `Alertmanager`

The alert backend:

- receives firing alerts from Prometheus
- groups alerts and delivers to ntfy via webhook
- Watchdog alert is silenced (Prometheus self-test heartbeat)

### `ntfy`

Push notification server:

- receives webhooks from Alertmanager on topic `homelab-alerts`
- delivers push notifications to Android/iOS ntfy app
- runs on NAS to stay available during Ryzen maintenance
- auth: open access on LAN (no Authentik dependency - alerts must arrive even during auth outage)
- also receives weekly version drift reports on topic `homelab-updates`

### `Dozzle` (optional)

Real-time Docker log viewer:

- main instance on Ryzen with multi-host support
- lightweight agent on NAS exposes Docker socket over port 7007
- single UI to tail logs from all containers across both hosts
- no persistent storage - purely live view
- use Dozzle for "what is happening now", use Grafana/Loki for "what happened earlier"

### `Grafana`

The main UI:

- reads from Prometheus (metrics) and Loki (logs)
- shows dashboards and lets you explore metrics and log queries
- protected by Authentik ForwardAuth
- ships with provisioned dashboards from the repo (8 dashboards)

---

## Access model

### Public (via Traefik)

- `Grafana`: `https://monitor.homelab.local`
- `Dozzle`: `https://logs.homelab.local` (if enabled; local auth on a trusted LAN)
- `ntfy`: `https://ntfy.homelab.local` (open - no ForwardAuth, must work during auth outages)

### Internal only

- `Prometheus`: `http://10.0.0.30:9090` on Ryzen
- `Alertmanager`: `http://10.0.0.30:9093` on Ryzen
- `Loki`: `http://10.0.0.30:3100` on Ryzen (bound to LAN IP so NAS Promtail can push)
- `Dozzle agent`: `http://10.0.0.10:7007` on NAS (if enabled)

Prometheus, Alertmanager, and Loki stay private. Grafana is the main day-to-day UI. Dozzle is an optional live-log shortcut.

---

## How data flows

```text
                          Metrics path
node_exporter ──┐
cadvisor ───────┤──> Prometheus ──> Alertmanager ──> ntfy ──> phone
smartctl ───────┘        |
                         v
                      Grafana  <──  Loki
                                     ^
                          Logs path  |
Docker containers ──> Promtail ──────┘

                       Live logs
Docker socket ──> Dozzle agent (NAS) ──> Dozzle (Ryzen) ──> browser
Docker socket ──────────────────────────────┘
```

In practice:

1. Exporters expose `/metrics`, Prometheus scrapes both hosts
2. Prometheus stores metrics and evaluates alert rules
3. Alertmanager receives firing alerts and POSTs to ntfy
4. ntfy pushes notification to your phone
5. Promtail on each host tails Docker container logs and ships to Loki
6. Grafana queries both Prometheus (metrics) and Loki (logs)
7. If enabled, Dozzle provides a separate live log tail UI across both hosts

---

## What is alerting today

Current rules cover:

- host down
- high CPU
- high memory
- low disk space
- critical disk space
- NAS apps pool usage
- NAS media pool usage
- SMART exporter down
- SMART failures and NVMe critical warnings
- high disk temperatures
- increasing SMART error counters
- `cadvisor` down
- container OOM events

This is enough to catch the obvious failures without turning the stack into noise.

---

## Useful UIs

### Grafana

Daily UI:

- `https://monitor.homelab.local`

Use it for:

- host health
- container usage
- quick visual checks

Provisioned dashboards:

- `Homelab Overview`
  - CPU
  - memory
  - root filesystem usage
  - full filesystem usage
  - network throughput
  - firing alert count
- `Containers Overview`
  - top CPU containers
  - top memory containers
  - selected container CPU
  - selected container memory
  - OOM events over the last 24 hours
- `NAS Critical Signals`
  - apps pool usage
  - media pool usage
  - SMART failing disks
  - hot disks
  - disk temperatures
  - SMART health by device
  - SMART error deltas over the last 24 hours
- `Authentik Health`
  - queued tasks total
  - queued tasks by actor
  - expired channel messages
  - total channel messages
  - largest channel group
  - oldest logout queue age in days
  - Authentik container CPU and memory
  - authenticated sessions vs Django sessions
- `Logs Overview`
  - log volume by host
  - error rate by service
  - top 10 noisiest services
  - top 10 services by errors
  - error log stream
- `Logs Explorer`
  - filtered log volume chart
  - full log stream with regex search
  - collapsible context panel with CPU/memory/processes from Prometheus
  - filters: host, service, container, stream (stdout/stderr), search
- `Traefik`
  - healthy/unhealthy backends
  - HTTPS req/s, 4xx/s, 5xx/s, p95 latency
  - requests per second per service
  - response codes by status class
  - p95 latency per service
  - latency percentiles (p50/p95/p99)
  - TLS versions
  - total requests by service
- `Container Status`
  - green/red status grid per host (NAS vs Ryzen)
  - uptime timeline (state-timeline showing up/down over time)
  - container restarts in selected range
  - OOM kills in selected range

### Prometheus UI

Prometheus has its own UI, but it is mainly for debugging.

Useful pages:

- `/targets` - see if scrape targets are `UP`
- `/graph` - run PromQL manually
- `/alerts` - see active alerts
- `/config` - verify loaded config

### Alertmanager UI

Alertmanager also has a UI.

Use it for:

- seeing which alerts are active
- checking grouping/silencing once notification routes are added

---

## How to reach Prometheus and Alertmanager safely

### On the Ryzen host

```bash
ssh admin@10.0.0.30
curl -I http://127.0.0.1:9090
curl -I http://127.0.0.1:9093
```

### Through SSH tunnels

```bash
ssh -L 9090:127.0.0.1:9090 admin@10.0.0.30
ssh -L 9093:127.0.0.1:9093 admin@10.0.0.30
```

Then open locally:

- `http://127.0.0.1:9090`
- `http://127.0.0.1:9093`

---

## Useful first Prometheus queries

Host up/down:

```promql
up
```

CPU by instance:

```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

Memory usage by instance:

```promql
100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))
```

Filesystem usage:

```promql
100 * (1 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}))
```

SMART status by disk:

```promql
smartctl_device_smart_status{instance="nas"}
```

SMART temperatures:

```promql
smartctl_device_temperature{instance="nas", temperature_type="current"}
```

Container memory by name:

```promql
container_memory_working_set_bytes{name!=""}
```

Container CPU by name:

```promql
sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m]))
```

---

## Where this is configured in the repo

- exporters + Promtail + Dozzle agent:
  - `roles/monitoring_exporters/`
- main monitoring stack (Prometheus, Alertmanager, Loki, Grafana):
  - `roles/monitoring_stack/`
- Dozzle (main instance):
  - `roles/dozzle/`
- ntfy:
  - `roles/ntfy/`
- enable flag and shared endpoints:
  - `group_vars/all.yml`
- NAS image pins:
  - `group_vars/n100.yml`
- Ryzen image pins:
  - `group_vars/docker_nodes.yml`
- Grafana route:
  - `roles/core_services/templates/traefik/dynamic_conf.yml.j2`
- Homepage entry:
  - `roles/media_stack/templates/homepage/services.yaml.j2`
- post-deploy checks:
  - `smoke_test.yml`
- Grafana dashboards as code:
  - `roles/monitoring_stack/files/grafana/dashboards/`
- Grafana dashboard provider:
  - `roles/monitoring_stack/templates/grafana/provisioning/dashboards/dashboards.yml.j2`
- Loki config:
  - `roles/monitoring_stack/templates/loki/loki-config.yml.j2`
- Promtail config:
  - `roles/monitoring_exporters/templates/promtail/promtail.yml.j2`
- version drift checker:
  - `scripts/version-check.py` + `config/version-check.yml`

---

## Operating notes

- If Grafana returns `404`, first verify the Traefik route was rendered with `monitoring_enabled: true`.
- If Grafana returns `302`, ForwardAuth is working and the request is reaching Authentik.
- If Authentik starts flapping, check the Authentik Postgres memory cap before touching Traefik.
- If `Authentik Health` shows a large queue and the largest channel group starts climbing again, check `django_channels_postgres_groupchannel` before you start deleting queued tasks.
- Prometheus and Alertmanager stay private on purpose.

---

## What to add later

Reasonable next steps:

1. Blackbox probes for external HTTP/TLS checks
2. Uptime Kuma for a public status page

Related docs:

- [Version Check](VERSION_CHECK.md) - automated version drift detection with ntfy notifications

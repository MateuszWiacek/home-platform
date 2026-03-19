# Monitoring Stack

What is deployed, what each component does, and where to look when something feels off.

---

## Scope

This repo intentionally keeps monitoring small:

- `node_exporter` on NAS and Ryzen
- `cadvisor` on NAS and Ryzen
- `smartctl_exporter` on NAS
- `Prometheus` on Ryzen
- `Alertmanager` on Ryzen
- `Grafana` on Ryzen

Not included:

- `Loki`
- `Promtail`
- `Blackbox`
- `ntfy`

This keeps the stack small. The goal is baseline metrics and alerting, not a full observability stack.

---

## Topology

### NAS

- `node_exporter`
- `cadvisor`
- `smartctl_exporter`

### Ryzen

- `node_exporter`
- `cadvisor`
- `Prometheus`
- `Alertmanager`
- `Grafana`

Reasoning:

- exporters are lightweight and run on both hosts
- scrape, alerting, and dashboards live on the Ryzen node
- only Grafana is exposed through Traefik

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

### `Alertmanager`

The alert backend:

- receives firing alerts from Prometheus
- handles grouping and delivery logic

Right now:

- running
- no external notification channel configured yet

### `Grafana`

The main UI:

- reads from Prometheus
- shows dashboards and lets you explore metrics
- protected by Authentik ForwardAuth
- ships with baseline dashboards provisioned from the repo

---

## Access model

### Public

- `Grafana`: `https://monitor.homelab.local`

### Internal only

- `Prometheus`: `http://127.0.0.1:9090` on Ryzen
- `Alertmanager`: `http://127.0.0.1:9093` on Ryzen

This is intentional. Grafana is the day-to-day UI. Prometheus and Alertmanager are kept private unless there is a strong reason to expose them.

---

## How data flows

```text
node_exporter/cadvisor -> Prometheus -> Alertmanager
                               |
                               v
                            Grafana
```

In practice:

1. exporters expose `/metrics`
2. Prometheus scrapes both hosts
3. Prometheus stores metrics and evaluates rules
4. Alertmanager receives alerts
5. Grafana queries Prometheus

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

- exporters:
  - `roles/monitoring_exporters/`
- main monitoring stack:
  - `roles/monitoring_stack/`
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

---

## Operating notes

- If Grafana returns `404`, first verify the Traefik route was rendered with `monitoring_enabled: true`.
- If Grafana returns `302`, ForwardAuth is working and the request is reaching Authentik.
- If Authentik starts flapping, check the Authentik Postgres memory cap before touching Traefik.
- Prometheus and Alertmanager stay private on purpose.

---

## What to add later

Reasonable next steps:

1. Alert delivery channel for Alertmanager
2. SMART or disk health monitoring for the NAS
3. Log aggregation with Loki/Promtail
4. Blackbox probes for external HTTP/TLS checks

Do not add all of that at once. Start with metrics, then add more only if you actually need it.

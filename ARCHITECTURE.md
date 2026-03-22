# Platform Engineering at Home - Architecture

System design reference. For trade-off reasoning and design principles, see [`DESIGN_PHILOSOPHY.md`](DESIGN_PHILOSOPHY.md).
For incident response: [`docs/operations/INCIDENT_RESPONSE.md`](docs/operations/INCIDENT_RESPONSE.md).

---

## Table of Contents

- [Node Roles](#node-roles)
- [Constraints and Success Criteria](#constraints-and-success-criteria)
- [Storage Placement](#storage-placement)
- [Operational Targets](#operational-targets)
- [Service Endpoints](#service-endpoints)
- [Network Flow](#network-flow)
- [Ansible Structure](#ansible-structure)

---

## Node Roles

### Node 1 - NAS / Control Plane (Intel N100)

| | |
|---|---|
| **Hardware** | Intel N100 (4-core, ~6W TDP) |
| **OS** | TrueNAS SCALE |
| **Role** | 24/7 backbone: storage + DNS + ingress + identity |

This box stays on. It's the control plane of the home network: DNS, TLS termination, SSO, storage. Low power by design.

ZFS stability is the constraint here. Containers are capped with memory limits and I verify the caps via `docker inspect ... HostConfig.Memory`. ZFS ARC doesn't care about your app spike.

Jellyfin lives here on purpose: Intel Quick Sync makes transcoding cheap and predictable, even 4K -> 1080p.

### Node 2 - Compute Lane (AMD Ryzen 5 6600H)

| | |
|---|---|
| **Hardware** | AMD Ryzen 5 6600H |
| **OS** | Debian VM on Proxmox VE |
| **Role** | CPU/RAM-hungry workloads |

Immich, Paperless-ngx, Navidrome, Audiobookshelf, Calibre-Web, SiYuan, Excalidraw, Mealie, Linkwarden, the monitoring stack, and the utility tools do not belong on the NAS. AI inference, OCR, databases, media indexing, heavier app stacks, and monitoring storage do not belong next to ZFS. The Ryzen takes the noisy work and can go down without taking core services with it.

---

## Constraints and Success Criteria

- **Clean URLs**: `https://service.<domain>` not `10.0.0.10:8096`. Nobody wants to memorize ports.
- **No inbound exposure**: TLS via Cloudflare DNS-01. Router stays closed.
- **HTTPS everywhere on LAN**: fewer edge cases, cleaner trust model.
- **Storage first**: ZFS shouldn't crash because an app got hungry.
- **Wife test**: non-technical household member can navigate without help. One dashboard, clean URLs, nothing breaks silently.

> Examples below use `homelab.local` for anonymity. In a real deployment, Cloudflare DNS-01 still requires a real registered domain.

---

## Storage Placement

1Gbit between nodes is fine for photos and documents. It's not a database link.

| Data | Location | Why |
|---|---|---|
| PostgreSQL databases | Ryzen NVMe | No network latency on every query |
| Immich AI model cache | Ryzen NVMe | Avoid 1Gbit bottleneck on model startup |
| Photos library | NAS HDD pool via NFS | ZFS integrity, capacity, snapshots |
| Documents archive | NAS HDD pool via NFS | Central storage + cross-device access |
| App configs | NAS SSD pool via NFS | Fast + snapshot-friendly |

---

## Operational Targets

- **N100** online 24/7. Ryzen VM stoppable without affecting core services.
- **ZFS ARC** target ~4.7 GiB. Container memory caps enforced and verified.
- **DB and AI cache** on Ryzen NVMe, no 1Gbit roundtrip per query.

---

## Service Endpoints

Everything behind Traefik, HTTPS via Cloudflare DNS-01. No inbound router exposure. Traefik dashboard is LAN-only.

| Service | URL | Node |
|---|---|---|
| Traefik dashboard | `http://10.0.0.10:8090` *(LAN-only)* | NAS |
| Authentik | `https://auth.homelab.local` | NAS |
| AdGuard Home | `https://dns.homelab.local` | NAS |
| Vaultwarden | `https://vault.homelab.local` | NAS |
| Portainer | `https://portainer.homelab.local` | NAS |
| Homepage | `https://home.homelab.local` | NAS |
| Jellyfin | `https://vod.homelab.local` | NAS |
| Immich | `https://photos.homelab.local` | Ryzen VM |
| Paperless-ngx | `https://docs.homelab.local` | Ryzen VM |
| Stirling-PDF | `https://pdf.homelab.local` | Ryzen VM |
| IT-Tools | `https://tools.homelab.local` | Ryzen VM |
| Navidrome | `https://music.homelab.local` | Ryzen VM |
| Audiobookshelf | `https://audiobooks.homelab.local` | Ryzen VM |
| Calibre-Web | `https://books.homelab.local` | Ryzen VM |
| SiYuan | `https://notes.homelab.local` | Ryzen VM |
| Excalidraw | `https://draw.homelab.local` | Ryzen VM |
| Mealie | `https://recipes.homelab.local` | Ryzen VM |
| Linkwarden | `https://links.homelab.local` | Ryzen VM |
| Syncthing | `https://sync.homelab.local` *(optional)* | Ryzen VM |
| Grafana | `https://monitor.homelab.local` *(optional)* | Ryzen VM |
| Dozzle | `https://logs.homelab.local` *(optional)* | Ryzen VM |
| ntfy | `https://ntfy.homelab.local` | NAS |
| TrueNAS UI | `https://nas.homelab.local` | NAS |
| Proxmox | `https://pve.homelab.local` | NAS -> Proxmox |

Immich, Paperless-ngx, Navidrome, Audiobookshelf, Calibre-Web, SiYuan, Excalidraw, Mealie, Linkwarden, Grafana, and the utility tools run on the Ryzen VM but route through NAS Traefik via file provider. Docker socket provider only sees local containers. ntfy runs on NAS and stays available even when Ryzen is down - alert delivery cannot depend on the compute node. Dozzle is optional in the public branch because it exposes a direct host port on the Ryzen node. Syncthing is optional because its sync directory must exist on the NAS first. Monitoring is optional because metrics are useful, but they are not part of the minimum viable homestack.

---

## Network Flow

Traffic path from client to service:

```
                    ┌───────────────┐
Client (LAN/WiFi) ->│ AdGuard (DNS) │ -> resolves service.homelab.local -> 10.0.0.10
                    └──────┬────────┘
                           │
                           v
                    ┌───────────────┐
                    │ Traefik (TLS) │  Cloudflare DNS-01 -> valid certs on LAN
                    └──────┬────────┘
                           │ ForwardAuth (optional per-service)
                           v
                    ┌───────────────┐
                    │   Authentik   │  SSO + policies
                    └──────┬────────┘
                           │
          ┌────────────────┴────────────────┐
          v                                 v
   NAS-local apps                      Ryzen VM apps
 (Vaultwarden, Jellyfin, etc.)        (Immich, Paperless, Navidrome, Mealie, Linkwarden, utility tools, DBs)
```

Two nodes, split by responsibility and power profile:

```
┌─────────────────────────────────┐     ┌──────────────────────────────────┐
│         NAS - Intel N100        │     │       Compute - Ryzen 5 6600H    │
│         TrueNAS SCALE           │     │       Debian VM on Proxmox       │
│                                 │     │                                  │
│  Traefik    AdGuard Home        │     │  Immich       Paperless-ngx      │
│  Authentik  Vaultwarden         │<----│  Navidrome    Audiobookshelf     │
│  Jellyfin   Homepage            │ NFS │  Calibre-Web  SiYuan             │
│  Portainer  ntfy                │     │  Excalidraw   Mealie             │
│                                 │     │  Linkwarden   Optional Syncthing │
│                                 │     │  Grafana      Prometheus         │
│                                 │     │  Alertmanager Loki               │
│                                 │     │  Dozzle       cAdvisor           │
│                                 │     │  Node Exporter                   │
│                                 │     │  Heavy CPU/RAM workloads         │
│                                 │     │  Local NVMe for DB/cache data    │
│  24/7, low power, ZFS storage   │     │                                  │
└─────────────────────────────────┘     └──────────────────────────────────┘
```

---

## Ansible Structure

```text
roles/
├── core_services/   # Traefik, AdGuard Home, Authentik, Vaultwarden, Portainer
├── media_stack/     # Jellyfin, Homepage
├── prod_apps/       # Immich, Paperless-ngx
├── monitoring_exporters/ # Node Exporter, cAdvisor, Promtail, Dozzle agent
├── monitoring_stack/ # Prometheus, Alertmanager, Grafana, Loki
├── navidrome/       # Navidrome music streaming
├── utility_tools/   # Stirling-PDF, IT-Tools
├── books_stack/     # Audiobookshelf, Calibre-Web
├── siyuan/          # SiYuan knowledge base
├── excalidraw/      # Excalidraw collaborative whiteboard
├── mealie/          # Mealie recipe manager
├── syncthing/       # Syncthing file synchronization
├── linkwarden/      # Linkwarden bookmark archive
├── ntfy/            # ntfy push notification server
├── dozzle/          # Dozzle real-time log viewer
├── archwright/      # archwright backup tool (files, SQLite, Docker PostgreSQL)
├── common/          # APT baseline, qemu-guest-agent
├── ssh_hardening/   # Shared SSH policy, both nodes
└── docker_host/     # Docker engine, Portainer Agent
```

```text
group_vars/
├── all.yml               # Global: domains, IPs, shared endpoints, DNS resolvers
├── n100.yml              # NAS-specific: paths, versions, compatibility toggles
└── docker_nodes.yml      # Ryzen: Docker user, NFS mounts, node-specific values

secrets.yml               # Vault: tokens, passwords, API keys; never in git
```

Roles are independently deployable via tags. IPs, domains, versions -> `group_vars`. Credentials -> `secrets.yml` (vault).

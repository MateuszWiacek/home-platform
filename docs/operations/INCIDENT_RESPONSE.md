# Incident Response

Emergency reference. If something is broken in production, start here.

For setup-time issues (things that fail during deployment), see [`COMMON_ISSUES.md`](../setup/COMMON_ISSUES.md).
For non-technical recovery steps (no terminal needed), see [`NON_TECHNICAL_RECOVERY.md`](NON_TECHNICAL_RECOVERY.md).

---

## If it's on fire (60 seconds)

Run these first to get a fast signal on container health, ingress/auth logs, DNS, and ACME:

```bash
# 1) Are the core containers up on the NAS?
ssh admin@10.0.0.10 "sudo docker ps --format '{{.Names}}\t{{.Status}}' | egrep 'traefik|adguard|authentik|vaultwarden|portainer|jellyfin|homepage'"

# 2) Traefik: routing / ACME / forward auth errors
ssh admin@10.0.0.10 "sudo docker logs --tail 200 traefik | tail -n 200"

# 3) Authentik: server/worker health
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-server"
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-worker"

# 4) DNS sanity (AdGuard)
dig +short auth.homelab.local @10.0.0.10

# 5) ACME sanity (DNS-01)
dig TXT _acme-challenge.homelab.local @1.1.1.1
```

---

## Incident playbooks

### SSO outage (Authentik down)

```bash
ssh admin@10.0.0.10
sudo docker ps --format '{{.Names}} {{.Status}}' | grep -E 'authentik|traefik'
cd /mnt/example_apps/appdata/docker/config/authentik
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml up -d --remove-orphans
sudo docker logs --tail 200 authentik-server
```

Temporary bypass - switch ForwardAuth services back to local auth while recovering:
```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard,portainer,homepage \
  -e adguard_auth_mode=local \
  -e portainer_auth_mode=local \
  -e homepage_auth_mode=local

ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik \
  -e excalidraw_auth_mode=local \
  -e it_tools_auth_mode=local \
  -e stirling_pdf_auth_mode=local
```

Re-enable after recovery (redeploy without overrides - picks up `group_vars/all.yml` defaults):
```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard,portainer,homepage,traefik
```

---

### DNS outage

```bash
dig +short dns.homelab.local @10.0.0.10
dig +short auth.homelab.local @10.0.0.10
ssh admin@10.0.0.10 "sudo docker logs --tail 200 adguard"
```

---

### TLS / certificate outage

```bash
ssh admin@10.0.0.10 "sudo docker logs --tail 400 traefik | grep -iE 'acme|challenge|cert|error'"
dig TXT _acme-challenge.<your-real-domain> @1.1.1.1  # DNS-01 needs a real registered domain
ssh admin@10.0.0.10 "cd /mnt/example_apps/appdata/docker/config/traefik && sudo docker compose up -d --remove-orphans"
```

---

### RAM pressure on NAS

```bash
ssh admin@10.0.0.10 "free -h"
ssh admin@10.0.0.10 "sudo docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'"
ssh admin@10.0.0.10 "cat /proc/spl/kstat/zfs/arcstats | grep -E '^(size|c_max|memory_throttle_count)'"
ssh admin@10.0.0.10 "dmesg -T | grep -iE 'out of memory|killed process|oom' | tail -n 30"
```

---

### Monitoring stack unhealthy

Use this only if `monitoring_enabled: true`.

```bash
ssh admin@10.0.0.30 "sudo docker ps --format '{{.Names}} {{.Status}}' | grep -E 'prometheus|grafana|alertmanager|node_exporter|cadvisor'"
ssh admin@10.0.0.30 "sudo docker logs --tail 200 prometheus"
ssh admin@10.0.0.30 "sudo docker logs --tail 200 grafana"
ssh admin@10.0.0.30 "curl -fsS http://127.0.0.1:9090/-/healthy && echo"
ssh admin@10.0.0.30 "curl -fsS http://127.0.0.1:9093/-/healthy && echo"
```

If Grafana is the only thing failing externally, verify Traefik routing on the NAS:

```bash
ssh admin@10.0.0.10 "sudo docker logs --tail 200 traefik | grep -i grafana"
```

---

### Authentik: worker permissions (`/media/public`)

Common failure: `authentik-worker` restart loop with permission errors.

Root cause is volume ownership mismatch. This repo creates required paths with configured `authentik_uid`/`authentik_gid` before startup.

```bash
ssh admin@10.0.0.10 "sudo ls -ld /mnt/example_apps/appdata/docker/config/authentik/media"
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-worker"
```

---

### Authentik: PostgreSQL OOM / restart loop

If `authentik-server` starts flapping, do not assume Traefik is the problem. Check for Postgres OOM first.

Typical signals:
- `auth.homelab.local` returns `502`
- `authentik-server` keeps restarting
- `dmesg` shows `Memory cgroup out of memory: Killed process ... (postgres)`

This repo keeps Authentik Postgres at:
```yaml
command: ["postgres", "-c", "max_connections=50"]
deploy:
  resources:
    limits:
      memory: 512M
```

Quick checks:
```bash
ssh admin@10.0.0.10 "sudo docker ps --format '{{.Names}} {{.Status}}' | grep authentik"
ssh admin@10.0.0.10 "sudo docker logs --tail 120 authentik-db"
ssh admin@10.0.0.10 "sudo dmesg -T | egrep -i 'oom|killed process|out of memory'"
```

If logs also show index corruption errors such as `heap tid from index tuple`, stop Authentik writers, reindex, then bring the stack back:
```bash
ssh admin@10.0.0.10
cd /mnt/example_apps/appdata/docker/config/authentik
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml stop server worker authentik-ldap-outpost
sudo docker exec -it authentik-db psql -U authentik -d authentik -c "REINDEX INDEX authentik_tasks_task_pkey;"
sudo docker exec -it authentik-db psql -U authentik -d authentik -c "REINDEX INDEX authentik_t_message_affe69_idx;"
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml up -d
```

If the database is up but `authentik-worker` still runs hot, check for channel-table bloat and queue pressure before touching Traefik or Authentik routing:

```bash
ssh admin@10.0.0.10
sudo docker stats --no-stream authentik-worker authentik-server authentik-db
sudo docker exec authentik-db psql -U authentik -d authentik -At -c "
SELECT COUNT(*) FROM django_channels_postgres_message WHERE expires < NOW();
SELECT state || E'\t' || COUNT(*) FROM authentik_tasks_task GROUP BY state ORDER BY COUNT(*) DESC;
SELECT actor_name || E'\t' || COUNT(*) FROM authentik_tasks_task WHERE state = 'queued' GROUP BY actor_name ORDER BY COUNT(*) DESC LIMIT 10;
"
```

If `VACUUM` fails with `No space left on device`, use the non-parallel form:

```bash
sudo docker exec authentik-db psql -U authentik -d authentik -c "VACUUM (ANALYZE, PARALLEL 0) django_channels_postgres_message;"
```

If expired channel rows are high, clean them in batches first:

```bash
sudo docker exec authentik-db psql -U authentik -d authentik -c "
WITH doomed AS (
  SELECT ctid
  FROM django_channels_postgres_message
  WHERE expires < NOW()
  LIMIT 50000
)
DELETE FROM django_channels_postgres_message
WHERE ctid IN (SELECT ctid FROM doomed);
"
```

Repeat until the expired count reaches zero, then re-check worker CPU and queued task count. Only consider direct task-queue cleanup if the backlog still does not move after channel cleanup.

For the first queue cleanup pass, stay conservative:

- purge only stale queued jobs older than `14 days`
- limit that purge to:
  - `authentik.providers.proxy.tasks.proxy_on_logout`
  - `authentik.outposts.tasks.outpost_session_end`
  - `authentik.core.tasks.clean_expired_models`
  - `authentik.core.tasks.clean_temporary_users`
- leave `authentik.events.tasks.event_trigger_dispatch` for a second pass only if the queue still does not drain
- delete matching rows from `authentik_tasks_tasklog` before deleting from `authentik_tasks_task`, otherwise the foreign key will block the purge

Reference SQL:
- `docs/reference/sql/authentik_maintenance.sql`

---

## Go-live smoke checklist

### Automated

```bash
ansible-playbook -i inventory.ini smoke_test.yml
```

### Manual verification

```bash
# Syntax check
ansible-playbook -i inventory.ini deploy_n100.yml --syntax-check
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --syntax-check

# Dry run
ansible-playbook -i inventory.ini deploy_n100.yml --check --diff
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --check --diff

# Verify containers are running
ssh admin@10.0.0.10 "sudo docker ps --format '{{.Names}} {{.Status}}'"
ssh admin@10.0.0.30 "sudo docker ps --format '{{.Names}} {{.Status}}'"

# Verify RAM caps are enforced
ssh admin@10.0.0.10 "sudo docker inspect --format '{{.Name}} mem={{.HostConfig.Memory}}' traefik adguard vaultwarden portainer jellyfin homepage"
```

### Endpoint checks

- [ ] `https://auth.homelab.local` - Authentik login page loads
- [ ] `https://dns.homelab.local` - AdGuard Home UI accessible
- [ ] `https://vault.homelab.local` - Vaultwarden loads
- [ ] `https://portainer.homelab.local` - Portainer accessible
- [ ] `https://home.homelab.local` - Homepage accessible
- [ ] `https://vod.homelab.local` - Jellyfin accessible
- [ ] `https://photos.homelab.local` - Immich accessible
- [ ] `https://docs.homelab.local` - Paperless accessible
- [ ] `https://pdf.homelab.local` - Stirling-PDF accessible
- [ ] `https://tools.homelab.local` - IT-Tools accessible
- [ ] `https://music.homelab.local` - Navidrome accessible
- [ ] `https://audiobooks.homelab.local` - Audiobookshelf accessible
- [ ] `https://books.homelab.local` - Calibre-Web accessible
- [ ] `https://notes.homelab.local` - SiYuan accessible
- [ ] `https://draw.homelab.local` - Excalidraw accessible
- [ ] `https://recipes.homelab.local` - Mealie accessible
- [ ] `https://links.homelab.local` - Linkwarden accessible
- [ ] `https://sync.homelab.local` - Syncthing accessible (if enabled)
- [ ] `https://monitor.homelab.local` - Grafana accessible (if monitoring is enabled)
- [ ] `https://nas.homelab.local` - TrueNAS UI accessible
- [ ] `http://10.0.0.10:8090` - Traefik dashboard (LAN only)

---

## SSH hardening verification

```bash
# From your workstation: expected denied, no password fallback
ssh -o PubkeyAuthentication=no root@10.0.0.10

# Then SSH to NAS and validate sshd syntax
ssh admin@10.0.0.10
sudo sshd -t
```

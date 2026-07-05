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
dig TXT _acme-challenge.homelab.local @1.1.1.1  # real domain used for ACME DNS-01
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

### Long offline / wake-up recovery

Use this when the lab was powered off for weeks and comes back half-alive: containers are running, but DNS, Authentik, or backups are noisy.

Typical signals:

- AdGuard container is up, but `dig @10.0.0.10` times out
- `auth.homelab.local` returns `500`
- `authentik-db` logs `FATAL: sorry, too many clients already`
- Archwright units failed right after boot because NFS, Docker, or app containers were not ready yet

Start with the normal smoke test, but expect it to fail on the first broken dependency:

```bash
ansible-playbook -i inventory.ini smoke_test.yml
```

#### 1. Fix AdGuard if DNS is up-but-dead

If AdGuard is running but DNS queries time out, the Docker bridge may be stale after wake-up. Recreate only the AdGuard stack. This keeps the config and data volumes intact.

```bash
ssh admin@10.0.0.10
cd /mnt/example_apps/appdata/docker/config/adguard
sudo docker compose down
sudo docker compose up -d

dig +short auth.homelab.local @127.0.0.1
dig +short auth.homelab.local @10.0.0.10
```

If the NAS itself cannot resolve external names during bootstrap, temporarily add a public resolver to `/etc/resolv.conf`, then restore local DNS once AdGuard is healthy:

```bash
sudo tee /etc/resolv.conf >/dev/null <<'EOF'
domain local
nameserver 10.0.0.10
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF
```

#### 2. Calm down Authentik before deleting anything

If Authentik returns `500` and Postgres says `too many clients already`, stop the worker first. The worker can keep retrying old session/logout jobs and starve the DB.

```bash
ssh admin@10.0.0.10
sudo docker stop authentik-worker

sudo docker exec authentik-db psql -U authentik -d authentik -At -F $'\t' -c "
SELECT state, COUNT(*)
FROM authentik_tasks_task
GROUP BY state
ORDER BY COUNT(*) DESC;

SELECT actor_name, state, COUNT(*), MIN(mtime), MAX(mtime)
FROM authentik_tasks_task
WHERE state IN ('queued', 'running', 'consumed', 'rejected')
GROUP BY actor_name, state
ORDER BY COUNT(*) DESC
LIMIT 30;
"
```

If `psql` still gets `too many clients already`, stop the server too. Keep Postgres running.

```bash
sudo docker stop authentik-server
sudo docker exec authentik-db psql -U authentik -d authentik -At -c "SELECT COUNT(*) FROM pg_stat_activity;"
```

Take a fresh DB backup before cleanup if Postgres accepts connections:

```bash
sudo systemctl start archwright-authentik-db.service
sudo systemctl status archwright-authentik-db.service --no-pager
```

If the backlog is clearly stale session/logout noise, delete task logs first, then tasks. The FK from `authentik_tasks_tasklog` will block direct task deletes.

```bash
sudo docker exec authentik-db psql -v ON_ERROR_STOP=1 -U authentik -d authentik -c "
WITH target AS (
  SELECT message_id
  FROM authentik_tasks_task
  WHERE (state IN ('done', 'rejected') AND mtime < NOW() - INTERVAL '7 days')
     OR (
       actor_name IN (
         'authentik.providers.proxy.tasks.proxy_on_logout',
         'authentik.outposts.tasks.outpost_session_end'
       )
       AND state IN ('queued', 'running', 'consumed')
     )
)
DELETE FROM authentik_tasks_tasklog
WHERE task_id IN (SELECT message_id FROM target);

WITH target AS (
  SELECT message_id
  FROM authentik_tasks_task
  WHERE (state IN ('done', 'rejected') AND mtime < NOW() - INTERVAL '7 days')
     OR (
       actor_name IN (
         'authentik.providers.proxy.tasks.proxy_on_logout',
         'authentik.outposts.tasks.outpost_session_end'
       )
       AND state IN ('queued', 'running', 'consumed')
     )
)
DELETE FROM authentik_tasks_task
WHERE message_id IN (SELECT message_id FROM target);

SELECT state, COUNT(*)
FROM authentik_tasks_task
GROUP BY state
ORDER BY COUNT(*) DESC;
"
```

Bring Authentik back:

```bash
sudo docker restart authentik-server
sudo docker start authentik-worker
curl -skI https://auth.homelab.local/
```

Expected result: `/` returns `302` to the login flow, `/-/health/live/` returns `200`, and `authentik-db` stops logging `too many clients already`.

#### 3. Reset failed backup units after services settle

Archwright jobs may fail during boot if NFS or app containers were not ready yet. After DNS/Auth are stable, reset the failed state and run one NAS job plus one Ryzen job manually.

```bash
ssh admin@10.0.0.10 "sudo systemctl reset-failed 'archwright-*.service' && sudo systemctl start archwright-authentik-db.service"
ssh admin@10.0.0.30 "sudo systemctl reset-failed 'archwright-*.service' && sudo systemctl start archwright-paperless-db.service"
```

Finish with:

```bash
ansible-playbook -i inventory.ini smoke_test.yml
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

Before purging queued tasks, check whether one channel group is doing something stupid:

```bash
sudo docker exec authentik-db psql -U authentik -d authentik -At -F $'\t' -c "
SELECT group_key, COUNT(*)
FROM django_channels_postgres_groupchannel
GROUP BY group_key
ORDER BY COUNT(*) DESC
LIMIT 5;
"
```

If the biggest group is in the hundreds while the rest are small, treat that as suspicious. In this stack the real root cause was stale memberships in the embedded proxy outpost shared group. Every `proxy_on_logout` and `outpost_session_end` task was fanning out into dead channels.

What worked:

- back up the DB first
- keep the live channel row
- delete stale rows from that one oversized group
- delete expired rows from `django_channels_postgres_message`
- `VACUUM (ANALYZE, PARALLEL 0)` both channel tables
- then watch whether queue depth starts falling on its own

That was enough to stop the storm here. After that, the queue drained normally.

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

### Authentik: disaster recovery (full restore)

When reindex and cleanup are not enough - the database is corrupted, lost, or the Authentik container stack is unrecoverable.

**What you lose if Authentik is gone:**

- ForwardAuth stops working (AdGuard, Portainer, Homepage, Stirling-PDF, IT-Tools, Excalidraw, Grafana)
- OIDC stops working (Immich, Paperless-ngx)
- Proxmox OIDC login fails (local root still works)

**What still works without Authentik:**

- Vaultwarden (local auth)
- Jellyfin (local auth)
- Navidrome, Audiobookshelf, Calibre-Web, SiYuan, Mealie, Linkwarden (all local auth)
- ntfy, Dozzle (local auth, no Authentik dependency)
- Traefik (routing works, ForwardAuth middleware returns 401/502)
- DNS (AdGuard still resolves, admin UI needs ForwardAuth bypass)

**Step 1: Temporarily disable ForwardAuth**

If you need access to ForwardAuth-protected services while Authentik is down:

```bash
ssh admin@10.0.0.10
# Edit the Traefik dynamic config to comment out ForwardAuth middleware
# or set auth_mode to "local" for affected services in group_vars/all.yml
# then re-deploy Traefik:
cd /path/to/repo
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
```

**Step 2: Restore the database**

archwright archives contain both config files and database dumps. `archwright restore` handles config files (compose, env, certs) automatically. Database dumps need manual `pg_restore` because loading a dump into a live container is a provider-specific operation.

```bash
ssh admin@10.0.0.10

# List available archives
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright list \
    --config /mnt/example_apps/appdata/docker/config/archwright/authentik-db.yml

# Preview what archwright restore would extract (config files only)
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright restore \
    --config /mnt/example_apps/appdata/docker/config/archwright/authentik-db.yml \
    --archive /mnt/example_apps/backup/archwright/authentik-db/<archive>.zip \
    --dry-run

# Stop Authentik but keep Postgres running
cd /mnt/example_apps/appdata/docker/config/authentik
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml stop server worker authentik-ldap-outpost

# Restore config files (compose, .env, certs)
sudo /mnt/example_apps/appdata/docker/config/archwright/archwright restore \
    --config /mnt/example_apps/appdata/docker/config/archwright/authentik-db.yml \
    --archive /mnt/example_apps/backup/archwright/authentik-db/<archive>.zip \
    --overwrite

# Extract the database dump from the archive
sudo unzip /mnt/example_apps/backup/archwright/authentik-db/<archive>.zip \
    "databases/*" -d /tmp/authentik-restore/

# Drop and recreate the database, then restore the dump
sudo docker exec authentik-db psql -U authentik -d postgres -c "DROP DATABASE authentik;"
sudo docker exec authentik-db psql -U authentik -d postgres -c "CREATE DATABASE authentik OWNER authentik;"
sudo docker exec -i authentik-db pg_restore \
    --username authentik --dbname authentik \
    < /tmp/authentik-restore/databases/authentik_db/*.dump

# Clean up extracted dump
sudo rm -rf /tmp/authentik-restore

# Bring everything back
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml up -d
```

**Step 3: If no backup exists**

Fresh Authentik install with the existing Ansible role. You will need to:

1. Re-run the Authentik setup wizard (create admin account)
2. Recreate OIDC providers for Immich, Paperless, Proxmox
3. Recreate ForwardAuth provider and application mappings
4. Recreate any custom groups and user accounts

This is painful but not catastrophic - the apps themselves keep their data. Only the SSO config is lost.

**Step 4: Post-restore checks**

```bash
# Verify Authentik is healthy
ssh admin@10.0.0.10 "sudo docker ps --format '{{.Names}} {{.Status}}' | grep authentik"

# Check ForwardAuth is working
curl -sI https://dns.homelab.local | head -5

# Check OIDC (try logging into Immich/Paperless via SSO)
# Check the Authentik Health dashboard in Grafana for queue stability
```

**Takeaway:** Authentik DB backup is the most important backup in this stack. Without it, you lose all identity config. archwright handles this automatically via the `authentik-db` job on the NAS (daily 02:50, 7 archives).

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

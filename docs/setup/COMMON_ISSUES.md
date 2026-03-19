# Common Issues

Setup-time gotchas and known fixes. These are problems you hit during initial deployment or service upgrades - not runtime incidents.

For runtime incidents (things breaking in production), see [`INCIDENT_RESPONSE.md`](../operations/INCIDENT_RESPONSE.md).

---

## AdGuard Home: port 53 already in use

**Symptom:** `failed to bind host port 0.0.0.0:53/tcp: address already in use`

**Cause:** On Debian/Ubuntu hosts, `systemd-resolved` listens on `127.0.0.53:53`. AdGuard binds `0.0.0.0:53` (all local addresses, including loopback), so bind fails. This conflict does not apply to TrueNAS SCALE.

**Fix:**
```bash
sudo sed -i 's/^#\?DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard
```

---

## AdGuard Home: 502 after first deploy

**Symptom:** `https://dns.homelab.local` returns 502 right after fresh deploy.

**Cause:** First boot uses setup wizard on `:3000`. Traefik forwards to `:80`. Wizard hasn't run yet.

**Fix:**
```yaml
# group_vars/n100.yml
adguard_setup_mode: true
```
```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard
# Complete wizard at http://10.0.0.10:3000
# Then set adguard_setup_mode: false in group_vars/n100.yml
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard
```

> Default in this repo is `adguard_setup_mode: false`. Enable it only for first-run wizard, then disable and redeploy.

---

## Traefik: container detection fails on Docker Engine 29+

**Symptom:** Services return 404. Traefik logs show:
`client version 1.24 is too old. Minimum supported API version is 1.44, please upgrade your client to a newer version`

**Cause:** Docker 29.0 raised the minimum required API version from 1.24 to 1.44. Traefik v3.0-v3.5 had the API version hardcoded at 1.24. Fixed in Traefik v3.6.1 (auto-negotiation, upstream PR #12256).

**Fix:** Ensure `traefik_version` resolves to `v3.6.1` or newer, then redeploy. This repo pins `traefik_version` to the current live NAS digest for Traefik `v3.6.8`, which satisfies that requirement.
```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
```

---

## Traefik: `acme.json` always shows `changed`

**Cause:** `state: touch` updates timestamps unless `preserve` is set.

**Fix:** Verify the task uses:
```yaml
- name: "Traefik | Ensure acme.json exists with correct permissions"
  ansible.builtin.file:
    path: "{{ docker_data_dir }}/traefik/acme.json"
    state: touch
    mode: '0600'
    modification_time: preserve
    access_time: preserve
```

---

## Traefik: `acme.json` path and permissions

ACME storage must use absolute path `/acme.json` inside the container. File permissions must be `0600` before Traefik starts or it may fall back to self-signed behavior.

```bash
ssh admin@10.0.0.10 "sudo ls -l /mnt/example_apps/appdata/docker/data/traefik/acme.json"
ssh admin@10.0.0.10 "sudo docker logs --tail 200 traefik | grep -iE 'acme|cert|resolver|error'"
```

---

## Traefik: new file-provider route returns 404

**Symptom:** A new file-provider route is present in config on disk, but the hostname still returns Traefik 404 and the browser shows Traefik's default self-signed cert.

**Cause:** `docker compose up -d` does not restart Traefik when only the mounted file changed, and file-watch reload on TrueNAS can be unreliable.

**Fix:** Restart or recreate Traefik, then verify the router appears in the API:
```bash
ssh admin@10.0.0.10
sudo docker restart traefik
curl -s http://127.0.0.1:8090/api/http/routers | jq -r '.[].name' | grep -E 'immich|paperless|stirling|it-tools'
```

This repo now forces Traefik recreation on config changes, so `deploy_n100.yml` applies the safe fix automatically.

---

## Traefik: cannot route to Immich/Paperless on Ryzen

**Symptom:** `photos.homelab.local` / `docs.homelab.local` return 404 from Traefik.

**Cause:** Docker provider is local-only (NAS socket). Ryzen services must be exposed through Traefik file provider routes.

**Fix:** Verify these variables and redeploy Traefik:
- `enable_remote_apps_routes: true` in `group_vars/n100.yml`
- `ryzen_ip`, `immich_service_port`, `paperless_service_port` in `group_vars/all.yml`

```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
```

---

## Fresh machine: module not found

**Symptom:** `community.docker.*` or `ansible.posix.mount` modules unavailable.

**Cause:** Required Ansible collections not installed.

**Fix:**
```bash
ansible-galaxy collection install -r requirements.yml
```

---

## Paperless: 403 behind Traefik

**Symptom:** Paperless container is up, but Traefik returns 403.

**Cause:** Paperless is a Django app. Behind reverse proxy, Django enforces host/origin checks; if `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` are wrong, you get 403 even when containers are healthy.

**Fix:** Ensure these variables are present in Paperless `.env` template:
```env
PAPERLESS_URL=https://{{ paperless_domain }}
PAPERLESS_CSRF_TRUSTED_ORIGINS=https://{{ paperless_domain }}
PAPERLESS_ALLOWED_HOSTS={{ paperless_domain }}
```
```bash
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags paperless
```

---

## Stirling-PDF: restarts with `OutOfMemoryError: Metaspace`

**Symptom:** `stirling_pdf` keeps restarting, Traefik may return 502, logs show `java.lang.OutOfMemoryError: Metaspace`.

**Cause:** Stirling-PDF is heavier than it looks. Java, LibreOffice, OCR tooling, and PDF workers can exhaust a tight container memory limit even when the app briefly becomes reachable.

**Fix:** Raise `stirling_pdf_memory_limit` and redeploy the utility tools role. This repo uses `2G` as the safe baseline.

```bash
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags utility_tools
ssh admin@10.0.0.30
sudo docker logs --tail 200 stirling_pdf
sudo docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' stirling_pdf
```

---

## Authentik Redis: `Can't handle RDB format version`

**Symptom:** Authentik stack fails to start; Redis logs contain `Can't handle RDB format version ...`

**Cause:** Persisted Redis dump was created by a newer Redis format than the current image can read (downgrade mismatch).

**Fix:** Keep `authentik_redis_image` on a compatible/newer tag. If you accept losing Redis cache/sessions, archive old dump and recreate:

```bash
ssh admin@10.0.0.10
sudo docker compose -f /mnt/example_apps/appdata/docker/config/authentik/docker-compose.yml -f /mnt/example_apps/appdata/docker/config/authentik/ldap-outpost.yml down
sudo mv /mnt/example_apps/appdata/docker/config/authentik/redis/dump.rdb /mnt/example_apps/appdata/docker/config/authentik/redis/dump.rdb.bak.$(date +%F_%H-%M-%S) || true
sudo docker compose -f /mnt/example_apps/appdata/docker/config/authentik/docker-compose.yml -f /mnt/example_apps/appdata/docker/config/authentik/ldap-outpost.yml up -d --remove-orphans
```

---

## Authentik PostgreSQL: OOM kill and restart loop

**Symptom:** `auth.homelab.local` starts returning `502`, `authentik-server` enters a restart loop, and `dmesg` shows `Memory cgroup out of memory: Killed process ... (postgres)`.

**Cause:** Authentik Postgres can exceed a tight memory cap during recovery, outpost churn, or heavy write bursts. Raising `max_connections` does not help here. It makes the memory ceiling problem worse.

**Fix:** Keep Authentik Postgres on a lower connection ceiling and a larger memory limit. This repo uses:

```yaml
command: ["postgres", "-c", "max_connections=50"]
deploy:
  resources:
    limits:
      memory: 512M
```

If the crash already happened:

```bash
ssh admin@10.0.0.10
sudo dmesg -T | egrep -i 'oom|killed process|out of memory'
sudo docker logs --tail 120 authentik-db
sudo docker logs --tail 80 authentik-server
```

If you also see index corruption errors such as `heap tid from index tuple`, reindex before restarting everything:

```bash
cd /mnt/example_apps/appdata/docker/config/authentik
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml stop server worker authentik-ldap-outpost
sudo docker exec -it authentik-db psql -U authentik -d authentik -c "REINDEX INDEX authentik_tasks_task_pkey;"
sudo docker exec -it authentik-db psql -U authentik -d authentik -c "REINDEX INDEX authentik_t_message_affe69_idx;"
sudo docker compose -f docker-compose.yml -f ldap-outpost.yml up -d
```

---

## Authentik PostgreSQL: `VACUUM` fails with `No space left on device`

**Symptom:** `VACUUM ANALYZE django_channels_postgres_message;` fails with:
`could not resize shared memory segment ... No space left on device`

**Cause:** This is usually Docker shared memory pressure, not a full dataset. PostgreSQL maintenance needs `/dev/shm`, and default container settings can be too small for large cleanup passes.

**Fix:** Run the maintenance pass without parallel workers, then keep a larger `shm_size` for Authentik Postgres. This repo uses `authentik_postgres_shm_size: "256m"`.

```bash
sudo docker exec authentik-db psql -U authentik -d authentik -c "VACUUM (ANALYZE, PARALLEL 0) django_channels_postgres_message;"
sudo docker exec authentik-db psql -U authentik -d authentik -c "VACUUM (ANALYZE, PARALLEL 0) django_postgres_cache_cacheentry;"
```

If cleanup is still too heavy, delete expired rows in batches first, then rerun `VACUUM (ANALYZE, PARALLEL 0)`.

---

## Authentik worker pressure: expired channels and task backlog

**Symptom:** Authentik stays up, but `authentik-worker` runs hot, task queue keeps growing, and logs show heavy scheduler churn or repeated cleanup retries.

**Cause:** Two things tend to combine here:

- `django_channels_postgres_message` accumulates expired rows
- `authentik_tasks_task` keeps a large historical backlog, often dominated by `proxy_on_logout` and `outpost_session_end`

Expired channel rows can block cleanup work long enough for the worker to spend most of its time on maintenance instead of draining the queue.

**Fix:** Clean expired channel rows first, not the task table.

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

sudo docker exec authentik-db psql -U authentik -d authentik -c "VACUUM (ANALYZE, PARALLEL 0) django_channels_postgres_message;"
```

Then verify:

```bash
sudo docker exec authentik-db psql -U authentik -d authentik -At -c "
SELECT COUNT(*) FROM django_channels_postgres_message WHERE expires < NOW();
SELECT state || E'\t' || COUNT(*) FROM authentik_tasks_task GROUP BY state ORDER BY COUNT(*) DESC;
"
```

Do not start by deleting queued tasks blindly. Let the worker recover first, then decide whether old queued proxy/logout jobs still need manual cleanup.

---

## SiYuan: restarts with `addgroup: permission denied`

**Symptom:** `siyuan` never becomes reachable, Traefik returns 502, logs show `addgroup: permission denied (are you root?)`.

**Cause:** SiYuan needs its entrypoint to create the runtime user/group inside the container. Forcing `user: 1000:1000` blocks that init step.

**Fix:** Do not override the container user. Redeploy and verify:
```bash
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags siyuan
ssh admin@10.0.0.30
sudo docker logs --tail 100 siyuan
curl -I http://127.0.0.1:6806/
```

---

## Calibre-Web: fresh install uses default admin

**Symptom:** Calibre-Web is reachable, but you don't remember setting credentials.

**Cause:** Fresh Calibre-Web starts with the upstream default admin account.

**Default login:** Username: `admin`, Password: `admin123`

**Fix:** Log in once, change the password immediately.

---

## Syncthing: deploy fails because NAS sync directory missing

**Symptom:** The Syncthing role fails before container start with an assertion about `{{ syncthing_sync_dir }}` missing.

**Cause:** This repo treats the sync folder as NAS-owned storage. The role does not create new media directories from the NFS client.

**Fix:** Create the target directory or dataset on the NAS first, then enable Syncthing and redeploy. This repo enables Syncthing by default because the `sync` dataset is expected to exist on the NAS.


---

## macOS: `dig` works but Safari says `Can't Find the Server`

**Symptom:** `dig` resolves homelab domains correctly, but Safari shows `Can't Find the Server` and `curl` fails with `Could not resolve host`.

**Cause:** On macOS, `dig` and the system resolver are not the same thing. `dig` can hit the expected DNS server while Safari, `curl`, and Python still use stale system resolver state or a different resolver path.

**Fix:** Flush the macOS DNS cache and retry:
```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

**Verify:** Use system-level resolution, not only `dig`:
```bash
dscacheutil -q host -a name photos.homelab.local
curl -kI https://photos.homelab.local
```

If `dig` works but `curl` still does not, also check for `iCloud Private Relay`, `Limit IP Address Tracking`, or a VPN overriding DNS on the Mac.

---

## Immich: pgvecto-rs -> VectorChord migration

Required when upgrading Immich from a version using `tensorchord/pgvecto-rs` to `ghcr.io/immich-app/postgres` (VectorChord). From Immich v2.x onwards, VectorChord is the official successor.

**If you have existing data (running Immich instance):**
```bash
# 1. Backup before anything else
docker exec immich_postgres pg_dumpall -U immich > /tmp/immich_backup_pre_migration.sql

# 2. Stop Immich (not the database)
cd /opt/immich
docker compose stop immich-server immich-machine-learning

# 3. Update the postgres image in docker-compose.yml to:
# ghcr.io/immich-app/postgres:14-vectorchord0.4.3
# Via Ansible: update immich_postgres_image in group_vars/docker_nodes.yml and redeploy

# 4. Restart only the database with the new image
docker compose up -d postgres

# 5. Run the migration
docker exec -it immich_postgres psql -U immich -d immich -c "
  ALTER EXTENSION vectors UPDATE;
  SELECT pgvectors_migrate();
"

# 6. Start the rest of the stack
docker compose up -d

# 7. Check logs for errors
docker logs immich_server --tail 50
```

**If this is a fresh install (no data):**
```bash
cd /opt/immich
docker compose down -v   # removes database volumes - all data will be lost
docker compose up -d     # initialises the database with VectorChord from scratch
```

---

## AdGuard Home: local DNS rewrites

For all LAN clients to route through NAS Traefik, configure a DNS rewrite in AdGuard Home:

```
*.homelab.local -> 10.0.0.10
```

Without this, clients may resolve to public IP and bypass the local path. VPN clients may override DNS; split-tunneling or custom DNS config may be required.

---

## Homepage widgets: Ryzen services use direct IP

Homepage widgets for Immich and Paperless use direct Ryzen IP (`http://10.0.0.30:PORT`) instead of their public domains (`https://photos.homelab.local`).

This is intentional. Homepage runs on the NAS and queries widget APIs server-side. Routing through the public domain would mean NAS -> AdGuard DNS -> Traefik -> Ryzen, adding an unnecessary hop and a dependency on Traefik being healthy just to display widget data.

Direct IP is faster, simpler, and survives a Traefik outage.

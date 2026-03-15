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
dig +short authentik.homelab.local @10.0.0.10

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
dig +short adguard.homelab.local @10.0.0.10
dig +short authentik.homelab.local @10.0.0.10
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

### Authentik: worker permissions (`/media/public`)

Common failure: `authentik-worker` restart loop with permission errors.

Root cause is volume ownership mismatch. This repo creates required paths with configured `authentik_uid`/`authentik_gid` before startup.

```bash
ssh admin@10.0.0.10 "sudo ls -ld /mnt/example_apps/appdata/docker/config/authentik/media"
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-worker"
```

---

### Authentik: PostgreSQL "too many clients"

During worker restart loops, connections can spike and exhaust Postgres defaults.

Compose config sets:
```yaml
command: ["postgres", "-c", "max_connections=200"]
```

Check active connections:
```bash
ssh admin@10.0.0.10 "sudo docker exec -i authentik-db psql -U authentik -d authentik -c 'SELECT count(*) FROM pg_stat_activity;'"
```

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

- [ ] `https://authentik.homelab.local` - Authentik login page loads
- [ ] `https://adguard.homelab.local` - AdGuard Home UI accessible
- [ ] `https://vaultwarden.homelab.local` - Vaultwarden loads
- [ ] `https://portainer.homelab.local` - Portainer accessible
- [ ] `https://homepage.homelab.local` - Homepage accessible
- [ ] `https://jellyfin.homelab.local` - Jellyfin accessible
- [ ] `https://immich.homelab.local` - Immich accessible
- [ ] `https://paperless.homelab.local` - Paperless accessible
- [ ] `https://stirling-pdf.homelab.local` - Stirling-PDF accessible
- [ ] `https://it-tools.homelab.local` - IT-Tools accessible
- [ ] `https://music.homelab.local` - Navidrome accessible
- [ ] `https://audiobooks.homelab.local` - Audiobookshelf accessible
- [ ] `https://books.homelab.local` - Calibre-Web accessible
- [ ] `https://notes.homelab.local` - SiYuan accessible
- [ ] `https://draw.homelab.local` - Excalidraw accessible
- [ ] `https://recipes.homelab.local` - Mealie accessible
- [ ] `https://links.homelab.local` - Linkwarden accessible
- [ ] `https://sync.homelab.local` - Syncthing accessible (if enabled)
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

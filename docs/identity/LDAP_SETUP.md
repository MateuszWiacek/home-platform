# LDAP Setup

Authentik LDAP outpost configuration, Base DN, TrueNAS/SSSD integration.

---

## Architecture

Authentik exposes LDAP via a dedicated outpost container (`authentik-ldap-outpost`).

The outpost must attach to two Docker networks:
- `default` - communication with Authentik core
- `proxy_net` - accessible by Traefik and LAN clients

Missing one of these produces routing/lookup errors that are hard to trace.

Port mapping: `389 -> 3389` (plain LDAP), LDAPS exposed through Traefik on `636`.

---

## Base DN

Use exactly the same normalized format everywhere. Case differences can break matching.

```
dc=homelab,dc=local
```

If outpost logs show `No provider found for request`, the first thing to check is Base DN consistency across Authentik provider config, outpost config, and client config.

---

## Operational checklist

Before deep debugging, verify:

- [ ] Outpost is running and healthy
- [ ] Outpost has the LDAP application assigned in Authentik
- [ ] Port mapping is correct (`389 -> 3389`), and LDAPS is exposed through Traefik on `636`
- [ ] Base DN is identical everywhere (`dc=homelab,dc=local`, lowercase, no spaces)
- [ ] Bind user exists and bind flow has no MFA step
- [ ] LDAP provider search mode is `Direct querying` when you need immediate visibility for new users
- [ ] Validate plain LDAP first (`ldap://:389`), then enable/validate TLS (`ldaps://:636`)

---

## Diagnostics

```bash
# Check outpost status
ssh admin@10.0.0.10 "sudo docker ps --format '{{.Names}} {{.Status}}' | grep authentik-ldap-outpost"

# Check port binding
ssh admin@10.0.0.10 "sudo ss -ltnp | egrep ':389|:636'"

# Outpost logs
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-ldap-outpost"
```

Direct bind test from NAS host network:
```bash
ssh admin@10.0.0.10 "sudo docker run --rm --network host alpine:3.19 sh -lc 'apk add --no-cache openldap-clients >/dev/null && ldapwhoami -x -H ldap://127.0.0.1:389 -D \"cn=<bind-user>,ou=users,dc=homelab,dc=local\" -W'"
```

---

## Error quick map

| Error | Likely cause |
|---|---|
| `No provider found for request` | Base DN mismatch or provider routing mismatch |
| `Invalid credentials (49)` | Wrong password, wrong bind user, or MFA in bind flow |
| `SERVER_DOWN` | Host/port/firewall/TLS problem |

---

## TrueNAS / SSSD integration

### Username appears as hash

If username resolves as UUID-like values, map LDAP username to `cn`:

```bash
midclt call ldap.update '{"auxiliary_parameters": "ldap_user_name = cn\nldap_user_gecos = cn\n"}'
sudo sss_cache -E || true
sudo systemctl restart sssd || true
sudo systemctl restart middlewared
```

Verify:
```bash
getent passwd <expected_username>
```

### New users do not appear immediately

```bash
sudo sss_cache -E
```

This flushes the SSSD cache and forces re-query on next lookup.

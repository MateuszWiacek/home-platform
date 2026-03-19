# Proxmox OIDC Setup

Proxmox VE reverse proxy through Traefik + Authentik OIDC login.

This gets its own document because the setup path is unique - it combines Traefik file-provider routing with native Proxmox OIDC, not the standard ForwardAuth or app-level OIDC patterns.

---

## Traffic flow

```
pve.homelab.local
  -> AdGuard DNS rewrite -> 10.0.0.10 (NAS / Traefik)
  -> Traefik router/service
  -> https://10.0.0.20:8006 (Proxmox)
```

The Traefik side is defined in `roles/core_services/templates/traefik/dynamic_conf.yml.j2` using `proxmox_domain` and `proxmox_internal_url`.

---

## OIDC setup

### 1. Create Authentik provider

In Authentik admin, create an OAuth2/OpenID provider for Proxmox.

Set the redirect URI exactly to `https://pve.homelab.local/` (note the trailing slash).

### 2. Configure Proxmox realm

```bash
pveum realm add authentik --type openid \
  --issuer-url https://auth.homelab.local/application/o/proxmox/ \
  --client-id proxmox \
  --username-claim preferred_username \
  --autocreate 1

# autocreate creates user object but does not grant admin ACL
pveum acl modify / --user <login>@authentik --role Administrator
pveum realm list
```

### 3. Verify

TLS sanity check (bypasses browser cache):
```bash
curl -vI https://pve.homelab.local
```

---

## Common issues

**`Redirect URI mismatch`:**
Compare the Authentik redirect URI and what Proxmox sends - byte for byte. The trailing slash matters.

**User created but no admin access:**
`autocreate` creates the user object but does not grant admin ACL. You must explicitly assign the Administrator role.

**Certificate shows Traefik self-signed instead of valid cert:**
Check that the Traefik router for Proxmox has the correct `certresolver` and `tls` configuration. Verify with `curl -vI`.

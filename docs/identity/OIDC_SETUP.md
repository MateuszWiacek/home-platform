# Native OIDC Setup Pattern

How to add native OIDC authentication (via Authentik) to a service that supports OpenID Connect.

This is a pattern document. It covers the common steps - each service will have its own env vars and redirect URI, but the Authentik side is always the same.

---

## When to use native OIDC

Native OIDC is the right fit when:
- The application supports OpenID Connect natively
- You want app-level identity (per-user sessions, user mapping, permissions)
- The service has mobile apps or API clients that would break with proxy-level auth

Target OIDC services: Immich, Paperless-ngx, Mealie, Audiobookshelf, Linkwarden, Proxmox.

See [`AUTH_MODEL.md`](AUTH_MODEL.md) for the full per-service decision matrix.

---

## How it works

```
Client -> Service login page -> "Log in with Authentik" button
                                        │
                                        v
                                   Authentik OIDC
                                        │
                                   authenticated?
                                   ├── yes -> redirect back to service with token
                                   └── no  -> Authentik login flow
```

The application handles the OIDC flow directly. Traefik is not involved in the auth decision - it just routes traffic.

---

## Prerequisites

- Authentik is deployed and reachable at `https://auth.homelab.local`
- The service auth mode is set to `oidc` in `group_vars/all.yml`
- Client ID and client secret are stored in `secrets.yml`
- You know the exact redirect URI for the target application

---

## Steps to add OIDC to a new service

### 1. Create the Authentik provider and application

In Authentik admin (`https://auth.homelab.local/if/admin/`):

1. **Create an OAuth2/OpenID Provider:**
   - Name: `<service>` (e.g. `immich`)
   - Authorization flow: default or implicit consent (depending on trust level)
   - Client type: confidential client if the app uses a client secret
   - Client ID: auto-generated or custom
   - Client Secret: auto-generated
   - Redirect URIs: `https://<service-domain>/auth/callback` (exact URI depends on the app - check its docs)
   - Scopes: `openid profile email` (minimum)

2. **Create an Application:**
   - Name: `<service>`
   - Slug: `<service>`
   - Provider: select the one you just created

### What to set in Authentik for services already scaffolded here

| Service | Provider type | Redirect URI | App-side issuer URL |
|---|---|---|---|
| Immich | OAuth2/OpenID Provider | `https://photos.homelab.local/auth/login` | `https://auth.homelab.local/application/o/immich/` |
| Paperless-ngx | OAuth2/OpenID Provider | `https://docs.homelab.local/accounts/oidc/authentik/login/callback/` | `https://auth.homelab.local/application/o/paperless/.well-known/openid-configuration` |

These two are already implemented in Ansible:
- `roles/prod_apps/templates/immich/env.j2`
- `roles/prod_apps/templates/paperless/env.j2`

### 2. Add secrets to vault

In `secrets.yml`:
```yaml
vault_<service>_oauth_client_id: "<client-id>"
vault_<service>_oauth_client_secret: "<client-secret>"
```

Add the placeholder to `secrets.yml.example` as well.

Current secret names already present in this repo:

```yaml
vault_immich_oauth_client_id
vault_immich_oauth_client_secret
vault_paperless_oauth_client_id
vault_paperless_oauth_client_secret
```

### 3. Set the auth mode variable

In `group_vars/all.yml`:
```yaml
<service>_auth_mode: oidc
```

### 4. Template the OIDC config into the service role

Each app has its own env vars. Common pattern in the `.env.j2` template:

```env
# Example: Immich
{% if immich_auth_mode == 'oidc' %}
OAUTH_ENABLED=true
OAUTH_ISSUER_URL=https://auth.homelab.local/application/o/<service>/
OAUTH_CLIENT_ID={{ vault_immich_oauth_client_id }}
OAUTH_CLIENT_SECRET={{ vault_immich_oauth_client_secret }}
OAUTH_AUTO_REGISTER=true
{% endif %}
```

Check each app's documentation for exact variable names - they're never the same.

### 5. Deploy

```bash
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags <service>
```

### 6. Verify

- Open the service URL in a browser
- Confirm "Log in with Authentik" option appears
- Complete OIDC login flow
- Confirm user is created/mapped in the application
- Verify logout and re-login
- Verify local admin fallback still works (if required by break-glass policy)
- Test with mobile/API clients if applicable

Optional low-level check:

```bash
ssh admin@10.0.0.30 "sudo docker inspect --format '{{.Config.Image}}' <container-name>"
```

Then confirm the generated env/config on disk contains the expected issuer URL and client ID source.

---

## Redirect URI reference

Record every redirect URI here as services are onboarded. Byte-for-byte accuracy matters - a trailing slash mismatch will break the flow.

| Service | Redirect URI | Status |
|---|---|---|
| Immich | `https://photos.homelab.local/auth/login` | Implemented in the reference deployment |
| Paperless-ngx | `https://docs.homelab.local/accounts/oidc/authentik/login/callback/` | Implemented in the reference deployment |
| Mealie | TBD | Planned |
| Audiobookshelf | TBD | Planned |
| Linkwarden | TBD | Planned |
| Proxmox | `https://pve.homelab.local/` | See [PROXMOX_OIDC](../setup/PROXMOX_OIDC.md) |

---

## Common issues

**`Redirect URI mismatch` error:**
Compare the redirect URI in Authentik and what the app sends - byte for byte. Trailing slashes, scheme, and case all matter.

**OIDC option never appears in the app UI:**
Usually one of these is missing:
- auth mode is still `local`
- client ID / secret are missing from `secrets.yml`
- the app env template was not redeployed

**User created but no permissions:**
OIDC auto-register creates the user object but does not grant admin or group membership. Map groups or set permissions in the app after first login.

**OIDC works in browser but local admin is locked out:**
Native OIDC should add a login option, not replace local auth. If local admin access disappears, check the app's config for "disable local login" flags.

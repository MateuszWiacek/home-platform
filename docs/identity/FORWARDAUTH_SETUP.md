# ForwardAuth Setup Pattern

How to add Traefik ForwardAuth (via Authentik) to a browser-only service.

This is a pattern document. It covers all services that use ForwardAuth - you don't need a separate doc per service.

---

## When to use ForwardAuth

ForwardAuth is the right fit when:
- The service is browser-only (no mobile app, no API clients, no sync protocol)
- You don't need app-level identity (no per-user sessions inside the app)
- You just want "authenticated or not" at the Traefik level

Current ForwardAuth services: AdGuard, Portainer, Homepage, Excalidraw, IT-Tools, Stirling-PDF.

See [`AUTH_MODEL.md`](AUTH_MODEL.md) for the full per-service decision matrix.

---

## How it works

```
Client -> Traefik -> ForwardAuth middleware -> Authentik
                                                  │
                                          authenticated?
                                          ├── yes -> Traefik forwards to backend service
                                          └── no  -> redirect to Authentik login
```

Traefik checks every request against Authentik before forwarding. The `authentik-auth` middleware is defined globally in Traefik's dynamic config.

---

## Prerequisites

- Authentik is deployed and reachable at `https://authentik.homelab.local`
- The `authentik-auth` ForwardAuth middleware is defined in `roles/core_services/templates/traefik/dynamic_conf.yml.j2`
- The service has an auth mode variable in `group_vars/all.yml`
- You know which Authentik proxy outpost is currently serving Traefik requests

---

## What to create in Authentik

For each ForwardAuth-protected service, Authentik needs:

- one `Proxy Provider`
- one `Application` attached to that provider
- that application assigned to the active `Proxy Outpost`

If the provider exists but the application is not assigned to the outpost, Traefik will still redirect to Authentik, but Authentik will answer with `404` for that host.

### Exact UI path

1. Open `https://authentik.homelab.local/if/admin/`
2. Go to `Applications -> Applications`
3. Choose `Create with Provider`
4. Select `Proxy Provider`
5. Set:
   - `Name`: service name, e.g. `Portainer`
   - `Authorization flow`: default flow is fine
   - `Mode`: `Forward auth (single application)`
   - `External host`: full public URL, e.g. `https://portainer.homelab.local`
6. Save
7. Go to `Applications -> Outposts`
8. Open the proxy outpost used by Traefik
9. Add the new application to the `Applications` list
10. Save and wait for the outpost to reload

Leave the rest of the provider fields at their defaults unless you have a reason to override them.

### Wave 1 live examples

These are the services currently implemented behind ForwardAuth in this repo:

| Service | Authentik object type | External host | Must be assigned to proxy outpost |
|---|---|---|---|
| AdGuard | Proxy Provider + Application | `https://adguard.homelab.local` | Yes |
| Portainer | Proxy Provider + Application | `https://portainer.homelab.local` | Yes |
| Homepage | Proxy Provider + Application | `https://homepage.homelab.local` | Yes |
| Excalidraw | Proxy Provider + Application | `https://draw.homelab.local` | Yes |
| IT-Tools | Proxy Provider + Application | `https://it-tools.homelab.local` | Yes |
| Stirling-PDF | Proxy Provider + Application | `https://stirling-pdf.homelab.local` | Yes |

---

## Steps to add ForwardAuth to a new service

### 1. Create the Authentik objects first

Follow the steps in [What to create in Authentik](#what-to-create-in-authentik).

Do this before changing the auth mode in Ansible. Otherwise Traefik will be configured to ask Authentik for a host that Authentik does not know yet.

### 2. Set the auth mode variable

In `group_vars/all.yml`:

```yaml
<service>_auth_mode: forwardauth
```

### 3. Add the middleware to the Traefik router

For Docker-label-based services (NAS-local), add the ForwardAuth middleware conditionally:

```yaml
# In the service's docker-compose template
labels:
  - "traefik.http.routers.<service>.middlewares={% if <service>_auth_mode == 'forwardauth' %}authentik-auth@file{% endif %}"
```

For file-provider-based services (Ryzen, routed via `dynamic_conf.yml.j2`), add the middleware to the router definition in the Traefik file provider template.

### 4. Deploy

```bash
# If NAS-local service
ansible-playbook -i inventory.ini deploy_n100.yml --tags <service>

# If Ryzen service routed through Traefik file provider
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
```

### 5. Verify

- Open the service URL in a browser
- Confirm redirect to Authentik login
- Log in and confirm redirect back to the service
- Open a private/incognito window and confirm unauthenticated access is blocked
- Verify logout behavior (closing session should require re-auth)

Optional low-level checks:

```bash
ssh admin@10.0.0.10 "sudo docker logs --tail 200 authentik-server | egrep -i 'Loaded application|<service-domain>'"
curl -kI https://<service-domain>
```

Expected:
- Authentik logs show `Loaded application` for that host
- The HTTP response is not `404` from Authentik
- Typical good responses are `302`, `401`, or `403`

---

## Temporarily disabling ForwardAuth

Useful during Authentik outages or debugging. Override the auth mode at deploy time:

```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags <service> -e <service>_auth_mode=local
```

Re-enable by redeploying without the override (picks up the `group_vars/all.yml` default).

See also: [INCIDENT_RESPONSE.md](../operations/INCIDENT_RESPONSE.md) for the SSO outage playbook.

---

## Common issues

**Service returns 401/403 after enabling ForwardAuth:**
Check that the Authentik outpost is running and the ForwardAuth middleware URL is correct in Traefik config.

**Service returns 404 from Authentik after enabling ForwardAuth:**
The most common cause is not Traefik. It means Authentik does not know this host yet. Check:
- the `Proxy Provider` exists
- the `External host` matches exactly
- the `Application` is assigned to the active proxy outpost

**Redirect loop between Traefik and Authentik:**
Usually a domain mismatch. The ForwardAuth URL and the Authentik external URL must use the same domain and scheme.

**ForwardAuth works in browser but breaks API/CLI clients:**
This is why ForwardAuth is only for browser-only tools. If the service has API clients, use native OIDC or local auth instead. See [`AUTH_MODEL.md`](AUTH_MODEL.md).

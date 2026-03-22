# Authentication Rollout

Implementation status and rollout plan. For the target model, see [`AUTH_MODEL.md`](AUTH_MODEL.md).

---

## Current state

- Phase 1 (per-service auth modes) is **implemented**.
- Auth mode values are configured in `group_vars/all.yml`.
- Defaults remain `local` for every service until migration is done deliberately.

### What is implemented in the reference deployment

| Service | Auth mode | Status |
|---|---|---|
| AdGuard | ForwardAuth | Active |
| Portainer | ForwardAuth | Active |
| Homepage | ForwardAuth | Active |
| Excalidraw | ForwardAuth | Active |
| IT-Tools | ForwardAuth | Active |
| Stirling-PDF | ForwardAuth | Active |
| Grafana | ForwardAuth | Implemented when `monitoring_enabled: true` |

### Native OIDC implemented in the reference deployment

| Service | Auth mode | Status |
|---|---|---|
| Immich | Native OIDC | Active |
| Paperless-ngx | Native OIDC | Active |

### ForwardAuth wiring status

Wired in Traefik config: AdGuard, Portainer, Homepage, Excalidraw, Stirling-PDF, IT-Tools, Grafana, Paperless-ngx, Immich.

Not yet wired: Mealie, Linkwarden, Navidrome, Audiobookshelf, Calibre-Web, SiYuan, Syncthing.

### Authentik objects currently required

| Service | Authentik object | What must be configured |
|---|---|---|
| AdGuard | Proxy Provider + Application | `External host: https://dns.homelab.local`, assigned to proxy outpost |
| Portainer | Proxy Provider + Application | `External host: https://portainer.homelab.local`, assigned to proxy outpost |
| Homepage | Proxy Provider + Application | `External host: https://home.homelab.local`, assigned to proxy outpost |
| Excalidraw | Proxy Provider + Application | `External host: https://draw.homelab.local`, assigned to proxy outpost |
| IT-Tools | Proxy Provider + Application | `External host: https://tools.homelab.local`, assigned to proxy outpost |
| Stirling-PDF | Proxy Provider + Application | `External host: https://pdf.homelab.local`, assigned to proxy outpost |
| Grafana | Proxy Provider + Application | `External host: https://monitor.homelab.local`, assigned to proxy outpost when monitoring is enabled |
| Immich | OAuth2/OpenID Provider + Application | Redirect URI and client secret, no proxy outpost assignment needed |
| Paperless-ngx | OAuth2/OpenID Provider + Application | Redirect URI and client secret, no proxy outpost assignment needed |

---

## Rollout waves

### Wave 1 - ForwardAuth for browser-only tools (completed)

- AdGuard
- Portainer
- Homepage
- Excalidraw
- IT-Tools
- Stirling-PDF

### Wave 2 - Native OIDC for core apps (completed)

- Immich
- Paperless-ngx

### Wave 3 - Native OIDC candidates

- Mealie
- Audiobookshelf
- Linkwarden

### Keep local for now

- Navidrome - Subsonic clients complicate proxy auth
- Calibre-Web - lower value than other OIDC targets
- SiYuan - access-code model is simple and predictable
- Syncthing - sync protocol is the real service, not the GUI

---

## Implementation phases

### Phase 1 - Replace global toggle with per-service auth modes (completed)

Service-level auth mode variables now live in `group_vars/all.yml`.

Traefik ForwardAuth decisions now live in:
- `roles/core_services/templates/traefik/dynamic_conf.yml.j2`
- Service-specific Traefik labels for AdGuard, Portainer, and Homepage

Existing native OIDC app toggles now respect auth mode in:
- `roles/prod_apps/templates/immich/env.j2`
- `roles/prod_apps/templates/paperless/env.j2`

### Phase 2 - Finish ForwardAuth for browser-only tools (completed)

All Wave 1 services are implemented in the reference deployment.

### Phase 3 - Extend native OIDC where it delivers the most value

Recommended next order: Mealie -> Audiobookshelf -> Linkwarden.

For each application, follow the [OIDC setup pattern](OIDC_SETUP.md).

### Phase 4 - Revisit edge cases

- Navidrome: likely local auth for now; revisit only if web-only use is the priority
- Calibre-Web: decide whether local auth is enough or if OIDC is worth the added work
- TrueNAS: keep break-glass admin and LDAP path
- Proxmox: keep native OIDC path separate from Traefik ForwardAuth

---

## Rollout checklists

### For ForwardAuth

- [ ] Add or update router middleware in Traefik config
- [ ] Create `Proxy Provider + Application` in Authentik
- [ ] Assign the application to the active proxy outpost
- [ ] Deploy Traefik config
- [ ] Verify redirect to Authentik
- [ ] Verify logout behavior
- [ ] Verify service still works after browser session refresh
- [ ] Update smoke test expectations if needed
- [ ] Update incident response docs if needed

### For OIDC

- [ ] Create Authentik provider and application
- [ ] Save the exact redirect URI in Authentik
- [ ] Record redirect URI
- [ ] Add secrets to `secrets.yml.example`
- [ ] Add app config or env to the role
- [ ] Deploy service
- [ ] Verify first login
- [ ] Verify logout/login loop behavior
- [ ] Verify existing local admin fallback if required
- [ ] Update incident response docs if needed

---

## Repo gaps to close

- Move selected services from `local` to `forwardauth` or `oidc` in `group_vars/all.yml`
- Add missing OIDC secret placeholders for planned services
- Extend incident response with redirect URI notes and break-glass steps per service
- Decide whether Navidrome and Calibre-Web are worth central auth at all
- Remove any remaining legacy docs references to the old global toggle

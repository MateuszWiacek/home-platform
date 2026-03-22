# Authentication Model

Target authentication model for the platform. One source of truth for per-service auth decisions.

For rollout status and implementation phases, see [`AUTH_ROLLOUT.md`](AUTH_ROLLOUT.md).
For setup instructions, see [`FORWARDAUTH_SETUP.md`](FORWARDAUTH_SETUP.md), [`OIDC_SETUP.md`](OIDC_SETUP.md), [`LDAP_SETUP.md`](LDAP_SETUP.md).

---

## Goals

- Use Authentik as the main identity source for browser-facing services.
- Prefer native OIDC when an application supports it well.
- Use Traefik ForwardAuth for simple web UIs that do not need app-level SSO.
- Avoid adding proxy auth in front of apps that rely on mobile clients, API tokens, sync protocols, or browser extensions.
- Keep break-glass access for core infrastructure.

## Non-goals

- Do not force a single auth mechanism onto every service.
- Do not break mobile apps, sync clients, browser extensions, or service APIs.
- Do not remove local administrator access from core infrastructure.

---

## Per-service authentication matrix

| Service | Node | Auth mechanism | Why |
|---|---|---|---|
| Authentik | NAS | Local + break-glass | Identity provider itself must stay recoverable |
| TrueNAS | NAS | Local + break-glass | Recovery path matters more than central auth |
| Proxmox | NAS -> Ryzen | Native OIDC | Good fit for platform admin login |
| AdGuard | NAS | ForwardAuth | Browser-only admin UI |
| Portainer | NAS | ForwardAuth | Browser-only admin UI |
| Homepage | NAS | ForwardAuth | Dashboard only |
| Vaultwarden | NAS | Local | Native clients and extensions matter |
| Jellyfin | NAS | Local | Native clients and TV apps matter |
| Immich | Ryzen | Native OIDC | Better than proxy auth for app sessions |
| Paperless-ngx | Ryzen | Native OIDC | Better than proxy auth for app sessions |
| Stirling-PDF | Ryzen | ForwardAuth | Admin-style web UI; simple fit |
| IT-Tools | Ryzen | ForwardAuth | Stateless browser-only tool |
| Excalidraw | Ryzen | ForwardAuth | Browser-only collaborative tool |
| Grafana | Ryzen | ForwardAuth | Browser-only monitoring UI |
| Navidrome | Ryzen | Local (for now) | Subsonic clients make proxy auth risky |
| Audiobookshelf | Ryzen | Native OIDC | Better long-term fit if clients still work cleanly |
| Calibre-Web | Ryzen | Local (for now) | Lower value than other OIDC targets |
| SiYuan | Ryzen | Local | Current access-code model is simple and predictable |
| Mealie | Ryzen | Native OIDC | Good candidate for central user login |
| Linkwarden | Ryzen | Native OIDC | Strong fit for central sign-in |
| Dozzle | Ryzen | Local | Optional internal debugging tool; keep it on a trusted LAN |
| ntfy | NAS | Local | Alert delivery must work when Authentik is down |
| Syncthing | Ryzen | Local | GUI is secondary; sync protocol is the real service |

---

## Current example auth-mode values

Auth mode is configured per service in `group_vars/all.yml`. The example values in this branch are:

```yaml
adguard_auth_mode: forwardauth
portainer_auth_mode: forwardauth
homepage_auth_mode: forwardauth
truenas_auth_mode: local
proxmox_auth_mode: local
vaultwarden_auth_mode: local
jellyfin_auth_mode: local
immich_auth_mode: oidc
paperless_auth_mode: oidc
stirling_pdf_auth_mode: forwardauth
it_tools_auth_mode: forwardauth
excalidraw_auth_mode: forwardauth
grafana_auth_mode: forwardauth
navidrome_auth_mode: local
audiobookshelf_auth_mode: local
calibre_web_auth_mode: local
siyuan_auth_mode: local
mealie_auth_mode: local
syncthing_auth_mode: local
linkwarden_auth_mode: local
ntfy_auth_mode: local
dozzle_auth_mode: local
dozzle_enabled: false
```

Default for all services is `local`. Services move to `forwardauth` or `oidc` deliberately, never by accident.

The target model in this document is broader than the current rollout, but Wave 1 and Wave 2 are already implemented in the reference deployment.

Benefits of per-service mode:
- No accidental lockout from a single global flag
- Clear documentation of intended auth per service
- Easier future rollout and safer rollback
- Current branch behavior stays stable until you intentionally change a service

---

## Break-glass requirements

These services must keep a direct recovery path even if Authentik is broken:

- Authentik
- TrueNAS
- Proxmox
- Vaultwarden
- Jellyfin

Break-glass principles:
- Do not remove the local admin path
- Do not depend on ForwardAuth for every recovery route
- Keep documented steps for temporarily disabling ForwardAuth on critical apps (see [INCIDENT_RESPONSE](../operations/INCIDENT_RESPONSE.md))

---

## Resolved questions

- **Mealie**: will go straight to OIDC when ready. ForwardAuth adds no value here since Mealie has native OIDC support. Currently local - no rush.
- **Audiobookshelf**: stays local until mobile app OIDC flows are verified working. The Android/iOS clients need testing before flipping the switch.
- **Navidrome**: stays local. Subsonic clients (DSub, play:Sub) do not support OIDC or ForwardAuth. Central auth would break the primary use case.
- **Calibre-Web**: stays local. Low value target for central auth, simple setup, rarely accessed by others.

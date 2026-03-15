# Design Philosophy

How I think about this platform. Not a spec, not a sales pitch - just the reasoning behind the decisions.

For the system layout itself, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## One rule

> If recovery is harder than purity, purity loses.

This shapes everything below. SSO is great until it locks you out of your own infrastructure. Ansible is great until a one-liner fix becomes a 20-minute commit cycle. Automation is great until the bootstrap step it replaced was a 30-second manual click.

I optimize for recovery speed and operational clarity, not architectural dogma.

---

## Decision Log

Every service and pattern in this stack exists for a reason. Not "I saw it on YouTube", but actual trade-off thinking.

| Decision | Reasoning |
|---|---|
| **AdGuard Home** | Internal DNS. Clean names, one place to manage. I don't memorize `10.0.0.10:1234`. |
| **Traefik + Cloudflare DNS-01** | Valid certs on LAN without opening inbound ports. No self-signed pain. |
| **Authentik over Authelia** | One identity source for users, groups, policies. Easier to reason about access. |
| **Vaultwarden self-hosted** | My vault, my backup policy. |
| **Portainer** | Phone-grade admin when I'm away from a real terminal. Complements Ansible, doesn't replace it. |
| **Homepage** | One dashboard for the whole household. Wife test passes. |
| **Break-glass local admins** | SSO outage shouldn't mean lockout. Recovery beats purity. |
| **TrueNAS SCALE on N100** | 24/7 low-power host with native container support. |
| **Jellyfin on N100** | Intel Quick Sync. Cheap transcoding, 24/7, low power. |
| **Container RAM limits on NAS** | ZFS ARC doesn't care about your app spike. Caps enforced, verified via `docker inspect`. |
| **Immich + Paperless on Ryzen** | AI/OCR and databases want real compute. NAS stays stable. |
| **DB and cache on NVMe** | 1Gbit is not a database link. |
| **`latest` tags during bootstrap** | Ship fast, validate, then pin. Not the other way around. |
| **Per-service auth modes** | No single global toggle. Each service gets the auth mechanism that fits its usage pattern. See [AUTH_MODEL](docs/identity/AUTH_MODEL.md). |

---

## Trade-offs and Mitigations

Things I consciously accept. Not a threats list, just a list of known costs with mitigations.

| Trade-off | Benefit | Cost | Mitigation |
|---|---|---|---|
| **SSO in the control plane** | One access policy, single front door | SSO down = locked out | Break-glass local admin; ForwardAuth toggleable per-service |
| **Internal DNS as critical infra** | Clean URLs, no port memorization | DNS down = "everything's broken" from a user's perspective | Fallback resolver on router; IP access still works |
| **DNS-01 for certs** | Valid LAN certs, no open ports | DNS API dependency, rate limits | Minimal-scope token, rotation, documented recovery steps |
| **Reverse proxy as choke point** | One TLS/routing layer | Bad config breaks multiple services at once | Config in code, quick rollback |
| **GUI tools (Portainer)** | Fast admin from phone | Drift risk if changes bypass Ansible | GUI is an ops console only. Changes get backported to code |
| **`latest` tags during bootstrap** | Faster initial rollout | An update can surprise you | Pin after stabilization; version bumps go through changelog |

---

## Network philosophy

Once you run a multi-node environment at home, network structure stops being optional.

I run OpenWrt - I value flexibility, regular updates, and day-2 features like VLANs. IP ranges are assigned by intent (infra, VMs, DHCP) so I never have to scan the network and guess what is what.

IoT devices live on a separate network with no access to the main LAN. The principle is simple: segment what you do not fully trust. IoT vendors are not exactly famous for security engineering, and I'd rather not have my *too smart* vacuum anywhere near Proxmox.

---

## On balance

This repo reflects what I run at home today, but it will evolve naturally over time. I like experimenting, and I already have more ideas than time (including a future OPNsense-based firewall setup).

At the same time, as of March 2026, I need to keep a healthy balance:

- I do similar work professionally at a much bigger scale
- I genuinely enjoy tinkering
- I do not want to burn out and lose that enjoyment

Even with AI (which I've been using and experimenting with since 2022) - and yes, I treat it as an exoskeleton / force multiplier - balance still matters.

---

## Who we are shows in how we design systems

At the end of the day, this is both a working platform and a reflection of how I think about infrastructure. Not the fanciest setup, not the most minimal - just one that works, recovers well, and doesn't require me to be awake at 2am to keep the lights on.

---

## Contact

If you got this far and you have questions, suggestions, found a bug, want to request something, or just want to talk like two geeks:

`<myname><mysurname>92@<email from 8.8.8.8 guys>`

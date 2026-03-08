# Platform Engineering at Home

<p align="center">
  <img src="docs/assets/readme-banner.png" alt="Platform Engineering at Home" />
</p>

[Architecture](ARCHITECTURE.md) | [Runbook](RUNBOOK.md) | [Quick Start](#quick-start)

A working homelab, not a demo. DNS, TLS, SSO, self-hosted media, photos, and documents, all automated end to end with Ansible. No inbound router exposure, no self-signed certs, no "just click through the warning". If something breaks at 2am and I'm not around, my wife can follow the runbook and fix it. That's the bar.

This repo is a design + ops artifact. If you want the why: [`ARCHITECTURE.md`](ARCHITECTURE.md). If you want the how-to-fix-at-2am: [`RUNBOOK.md`](RUNBOOK.md).

> Hostnames and IPs are example values. Real ones live in a private inventory.

---

## If you're here from LinkedIn

This is a working homelab, not a demo. Everything here runs at home daily.

- DNS, TLS, and SSO wired as one stack, not services glued together with hope
- Reproducible deploys: Ansible roles, Jinja2 templates, inventory-driven vars
- Core operations are codified. Unavoidable bootstrap steps are explicit and documented
- Day-2 operations documented in [`RUNBOOK.md`](RUNBOOK.md), not in someone's memory
- Design decisions and trade-offs: [`ARCHITECTURE.md`](ARCHITECTURE.md)

If you're here to build your own open-source homestack, jump straight to the Quick Start section.

---

## Stack

| Service | What it does |
|---|---|
| AdGuard Home | Internal DNS, clean URLs, no port memorization |
| Traefik | Ingress + TLS via Cloudflare DNS-01 |
| Authentik | SSO, one login gate for everything |
| Vaultwarden | Self-hosted password vault |
| Portainer | Container admin when I'm not at a real terminal |
| Jellyfin | Self-hosted media server |
| Homepage | Dashboard, one place for the whole household |
| Immich | Self-hosted Google Photos replacement |
| Paperless-ngx | Self-hosted document archive |

---

Full traffic flow and node layout: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Quick Start

```bash
ansible-galaxy collection install -r requirements.yml

# Dry run first - always
ansible-playbook -i inventory.ini deploy_n100.yml --check --diff
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --check --diff

# Full deploy
ansible-playbook -i inventory.ini deploy_n100.yml             # NAS: core + media
ansible-playbook -i inventory.ini deploy_docker_nodes.yml     # Ryzen: prod apps

# Single service
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
ansible-playbook -i inventory.ini deploy_n100.yml --tags authentik
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags immich

# Post-deploy verification
ansible-playbook -i inventory.ini smoke_test.yml
```

Secrets: copy `secrets.yml.example` to `secrets.yml`, fill in, encrypt with ansible-vault. Never plaintext, never in git.

> All deploy commands require `--ask-vault-pass` or `--vault-password-file ~/.vault_pass` if `secrets.yml` is encrypted.

---

## Repo Layout

```
roles/          # core_services / media_stack / prod_apps / common / ssh_hardening / docker_host
group_vars/     # all.yml / n100.yml / docker_nodes.yml
deploy_n100.yml           # NAS: core + media
deploy_docker_nodes.yml   # Ryzen: prod apps
smoke_test.yml            # post-deploy health check
docs/assets/              # README banner / cover images
ARCHITECTURE.md           # the why
RUNBOOK.md                # the how-to-fix-at-2am
```

---

## Read This Before Deploy

Things that look trivial until they ruin your evening:

- **AdGuard first-run wizard:** fresh installs need one-time bootstrap on `:3000` before the UI is normal. See runbook.
- **Traefik `acme.json`:** must exist, `0600`, handled carefully. `state: touch` with preserved timestamps to avoid false `changed`.
- **Authentik outpost config:** if SSO feels "almost working", the answer is usually in outpost or worker logs.

Full failure modes and incident playbooks: [`RUNBOOK.md`](RUNBOOK.md).

---

## Docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md): design decisions, trade-offs, node roles, storage layout
- [`RUNBOOK.md`](RUNBOOK.md): operational commands, incident playbooks, smoke checklist
- [`smoke_test.yml`](smoke_test.yml): post-deploy health verification
- [`secrets.yml.example`](secrets.yml.example): required vault variables and placeholders

# Cloudflare DNS-01 Setup

How to get TLS certificates on a LAN without opening any ports to the internet.

---

## Why DNS-01

Traefik needs valid TLS certs for `*.your-domain.example`. The standard HTTP-01 challenge requires port 80 open to the internet. DNS-01 proves domain ownership by creating a TXT record in Cloudflare DNS - no inbound traffic needed.

---

## Prerequisites

- A registered domain you control
- Domain DNS managed by Cloudflare (nameservers pointed to Cloudflare)
- A Cloudflare account (free tier is fine)

---

## Step 1: Create a Cloudflare API token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use the "Edit zone DNS" template, or create a custom token with:

| Permission | Access |
|---|---|
| Zone / Zone / Read | Required - Traefik needs to find your zone |
| Zone / DNS / Edit | Required - Traefik creates TXT records for challenges |

4. Zone Resources: select "Include / Specific zone / your-domain.com"
5. Do NOT use the Global API Key - it has full account access

Copy the token. You will only see it once.

---

## Step 2: Add the token to secrets.yml

```bash
ansible-vault edit secrets.yml
```

Add or update:

```yaml
cloudflare_token: "your-token-here"
cert_email: "your-email@example.com"
```

The `cert_email` is used for Let's Encrypt registration. It receives expiry warnings if renewal fails.

---

## Step 3: Verify

The Traefik role validates the token exists before deploying:

```yaml
# roles/core_services/tasks/validate.yml
- name: "Validate | Required secrets are defined (Cloudflare)"
  assert:
    that:
      - cloudflare_token is defined
      - cloudflare_token | length > 0
```

After deploying Traefik:

```bash
# Check that acme.json has certificates
ssh admin@10.0.0.10
docker exec traefik cat /acme.json | python3 -m json.tool | grep -c "certificate"
```

If the count is > 0, DNS-01 is working.

---

## How it works in this repo

Traefik config (`roles/core_services/templates/traefik/traefik.yml.j2`):

```yaml
certificatesResolvers:
  myresolver:
    acme:
      email: "{{ cert_email }}"
      storage: "/acme.json"
      dnsChallenge:
        provider: cloudflare
```

Note: the resolver is named `myresolver`, not `cloudflare`. Traefik routes reference it as `myresolver@file` or via Docker labels with `traefik.http.routers.*.tls.certresolver=myresolver`.

The token is passed as an environment variable in the Traefik compose file:

```yaml
environment:
  - CF_DNS_API_TOKEN={{ cloudflare_token }}
```

Traefik automatically renews certs before expiry. No cron needed.

---

## Troubleshooting

**"acme.json is empty after deploy"**

- Check Traefik logs: `docker logs traefik 2>&1 | grep -i acme`
- Common cause: token permissions too narrow (missing Zone/Read)
- Common cause: domain not managed by Cloudflare (nameservers not pointed)

**"certificate expired" warnings in browser**

- Traefik renews 30 days before expiry. If renewal failed, check logs.
- Verify the token is still valid in Cloudflare dashboard.

**"DNS propagation timeout"**

- DNS-01 needs the TXT record to propagate. Usually takes 30-120 seconds.
- If Cloudflare DNS is the authoritative nameserver, propagation is near-instant.

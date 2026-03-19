# Deploy Commands

Canonical reference for all deployment commands. One source of truth.

---

## Prerequisites

```bash
ansible-galaxy collection install -r requirements.yml
```

---

## Full deploy

```bash
# Dry run first - always
ansible-playbook -i inventory.ini deploy_n100.yml --check --diff
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --check --diff

# Full deploy
ansible-playbook -i inventory.ini deploy_n100.yml             # NAS: core + media
ansible-playbook -i inventory.ini deploy_docker_nodes.yml     # Ryzen: prod apps + tools + libraries + knowledge + collaboration

# Post-deploy verification
ansible-playbook -i inventory.ini smoke_test.yml
```

---

## Single service (NAS)

```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags traefik
ansible-playbook -i inventory.ini deploy_n100.yml --tags adguard
ansible-playbook -i inventory.ini deploy_n100.yml --tags authentik
ansible-playbook -i inventory.ini deploy_n100.yml --tags vaultwarden
ansible-playbook -i inventory.ini deploy_n100.yml --tags portainer
ansible-playbook -i inventory.ini deploy_n100.yml --tags media

# Entire core role
ansible-playbook -i inventory.ini deploy_n100.yml --tags core
```

---

## Single service (Ryzen)

```bash
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags immich
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags paperless
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags backups
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags utility_tools
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags navidrome
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags books_stack
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags audiobookshelf
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags calibre_web
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags siyuan
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags excalidraw
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags mealie
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags linkwarden
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags syncthing
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags monitoring
```

---

## SSH hardening

```bash
ansible-playbook -i inventory.ini deploy_n100.yml --tags hardening
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags hardening
```

---

## Monitoring

```bash
# Monitoring is already enabled in the repo.
# Only make sure vault_grafana_admin_password exists in secrets.yml.
# NAS disk health also depends on smartctl_exporter on the NAS.

ansible-playbook -i inventory.ini deploy_n100.yml --tags monitoring
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --tags monitoring
```

---

## Vault

```bash
ansible-vault encrypt secrets.yml
ansible-vault edit secrets.yml
ansible-playbook -i inventory.ini deploy_n100.yml --ask-vault-pass
ansible-playbook -i inventory.ini deploy_n100.yml --vault-password-file ~/.vault_pass
```

> All deploy commands require `--ask-vault-pass` or `--vault-password-file ~/.vault_pass` if `secrets.yml` is encrypted.

---

## Diagnostics

```bash
ansible n100 -m ping
ansible docker_nodes -m ping
ansible-playbook -i inventory.ini deploy_n100.yml --list-tasks
ansible-playbook -i inventory.ini deploy_n100.yml --list-tags
ansible-playbook -i inventory.ini deploy_n100.yml --list-hosts
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --list-tags
```

---

## Lint / Syntax

```bash
# Optional local tools (not installed by requirements.yml)
python3 -m pip install --user ansible-lint yamllint

ansible-playbook -i inventory.ini deploy_n100.yml --syntax-check
ansible-playbook -i inventory.ini deploy_docker_nodes.yml --syntax-check
ansible-lint deploy_n100.yml
ansible-lint deploy_docker_nodes.yml
yamllint .
```

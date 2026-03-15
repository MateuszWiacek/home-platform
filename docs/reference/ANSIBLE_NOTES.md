# Ansible Notes

Patterns, gotchas, and conventions used in this repo. Reference for "why does this look like that" moments.

---

## `import_tasks` vs `include_tasks`

- `import_tasks`: static, tags work at import level, easier to debug
- `include_tasks`: dynamic, useful with loops/conditions, tags must be repeated inside

This repo uses `import_tasks` by default for clarity.

---

## `notify` + handlers

- Handler runs once at end of play, even if notified multiple times
- Handler only fires on `changed`, not `ok`
- All handlers in this repo use shell-based `docker compose up -d --remove-orphans` pattern for consistency

---

## `failed_when` + `changed_when`

Useful for shell commands with non-standard exit semantics (e.g., `docker network create` errors if network already exists):

```yaml
register: result
failed_when:
  - result.rc != 0
  - "'already exists' not in result.stderr"
changed_when: result.rc == 0
```

---

## `become: true` vs `ansible_become: true`

Both work. This repo uses `become: true` consistently. Don't mix them.

---

## `--check --diff` behavior

`--check --diff` compares rendered templates from local temp paths (e.g., `~/.ansible/tmp/...`) to remote files. This is expected behavior - the temp paths in diff output are normal and do not indicate a problem.

---

## Adding a new service

The pattern for adding a new service to this repo:

1. Create a role under `roles/<service_name>/` with tasks, handlers, defaults, and templates
2. Add service variables to `group_vars/all.yml` (domain, ports, auth mode)
3. Add secrets to `secrets.yml` and `secrets.yml.example`
4. Add the role to the appropriate playbook (`deploy_n100.yml` or `deploy_docker_nodes.yml`) with tags
5. If the service runs on Ryzen, add a file-provider route in `roles/core_services/templates/traefik/dynamic_conf.yml.j2`
6. Add DNS entry in AdGuard Home (or rely on the `*.homelab.local` wildcard rewrite)
7. Add the endpoint to the smoke test
8. Deploy with `--check --diff` first, then apply

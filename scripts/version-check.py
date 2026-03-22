#!/usr/bin/env python3
"""
Version Drift Checker for 9lives Homelab
=========================================
Compares pinned service versions in group_vars against latest
GitHub releases. Detects coupled version drift and optionally
sends a summary to ntfy.

Usage:
    ./scripts/version-check.py                    # full report
    ./scripts/version-check.py --quiet            # only if updates exist
    ./scripts/version-check.py --notify           # also push to ntfy
    ./scripts/version-check.py --host nas         # only NAS services
    ./scripts/version-check.py --only grafana,loki  # specific services only
    ./scripts/version-check.py --write            # update group_vars with latest versions
    ./scripts/version-check.py --write --dry-run  # show what would change
    ./scripts/version-check.py --json             # machine-readable output
    ./scripts/version-check.py --cache /tmp/vc.json  # save/reuse GitHub responses
    GITHUB_TOKEN=ghp_... ./scripts/version-check.py  # higher API rate limit

Requires: PyYAML (pip install pyyaml)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML is required.\n"
        "  pip install pyyaml\n"
        "  (Already installed if you have Ansible.)"
    )

# -- Paths ---------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "version-check.yml"

# -- ANSI colours --------------------------------------------------
NO_COLOR = os.environ.get("NO_COLOR") is not None
GREEN  = "" if NO_COLOR else "\033[32m"
YELLOW = "" if NO_COLOR else "\033[33m"
RED    = "" if NO_COLOR else "\033[31m"
CYAN   = "" if NO_COLOR else "\033[36m"
DIM    = "" if NO_COLOR else "\033[2m"
BOLD   = "" if NO_COLOR else "\033[1m"
RESET  = "" if NO_COLOR else "\033[0m"

# -- GitHub API ----------------------------------------------------
GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 15
MAX_WORKERS = 8

# -- Host mapping --------------------------------------------------
# Maps group_vars filenames to host identifiers.  Used by --host
# to pick the correct value when a variable is defined in multiple files.
DEFAULT_HOST_MAP: dict[str, str] = {
    "all.yml": "both",
    "n100.yml": "nas",
    "docker_nodes.yml": "ryzen",
}


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Load the version-check YAML config."""
    with open(path) as f:
        return yaml.safe_load(f)


def parse_group_vars_config(
    raw: list,
) -> list[tuple[str, str]]:
    """
    Parse the group_vars section of the config.

    Supports two formats:
        # Simple (host inferred from DEFAULT_HOST_MAP)
        group_vars:
          - group_vars/all.yml

        # Explicit host mapping
        group_vars:
          - path: group_vars/all.yml
            host: both

    Returns:
        [(relpath, host), ...]
    """
    result: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            filename = Path(entry).name
            host = DEFAULT_HOST_MAP.get(filename, "both")
            result.append((entry, host))
        elif isinstance(entry, dict):
            if "path" not in entry:
                print(f"{YELLOW}  warning: group_vars entry missing 'path' "
                      f"key: {entry}, skipping{RESET}", file=sys.stderr)
                continue
            result.append((entry["path"], entry.get("host", "both")))
    return result


# Type alias: {variable: {filepath: value}}
VersionMap = dict[str, dict[Path, str]]


@dataclass
class CheckResult:
    """Result of checking a single service against its upstream release."""

    name: str
    status: str            # "up_to_date", "update", "error", "skip"
    variable: str
    current: str
    extract: str | None = None
    latest: str = ""
    url: str = ""
    note: str = ""
    message: str = ""

    def to_json_dict(self) -> dict:
        """Build a status-appropriate dict for JSON output."""
        d: dict = {
            "name": self.name,
            "status": self.status,
            "variable": self.variable,
            "current": self.current,
        }
        if self.status == "update":
            d["latest"]      = self.latest
            d["release_url"] = self.url
            d["note"]        = self.note
            d["writable"]    = self.extract is None
        elif self.status == "up_to_date":
            d["latest"] = self.latest
        elif self.status == "error":
            d["error"] = self.message
        elif self.status == "skip":
            d["reason"] = self.message
        return d


def load_current_versions(
    gv_entries: list[tuple[str, str]],
) -> tuple[VersionMap, dict[Path, str]]:
    """
    Read group_vars and collect every *_version variable.

    Returns:
        version_map:  {variable: {filepath: value}} - per-file values
        file_hosts:   {filepath: host} - host mapping for each file

    Tracks every file a variable appears in, with its actual value
    in that file.  This means promtail_version can be "3.5.0" in
    n100.yml and "3.5.0" in docker_nodes.yml independently.
    """
    version_map: VersionMap = {}
    file_hosts: dict[Path, str] = {}

    for relpath, host in gv_entries:
        fullpath = REPO_ROOT / relpath
        if not fullpath.exists():
            print(f"{YELLOW}  warning: {relpath} not found, skipping{RESET}",
                  file=sys.stderr)
            continue
        file_hosts[fullpath] = host
        with open(fullpath) as f:
            data = yaml.safe_load(f) or {}
        for key, value in data.items():
            if key.endswith("_version"):
                version_map.setdefault(key, {})[fullpath] = str(value)

    return version_map, file_hosts


def resolve_version(
    variable: str,
    version_map: VersionMap,
    host_filter: str | None,
    file_hosts: dict[Path, str],
) -> str:
    """
    Pick the correct current version for a variable.

    When --host is set, prefer a host-specific file (e.g. n100.yml
    for "nas") over a shared file (all.yml / "both").  This mirrors
    Ansible variable precedence where host/group-specific vars
    override global ones.

    Without --host, fall back to last-defined (dict insertion order).
    """
    file_values = version_map.get(variable, {})
    if not file_values:
        return ""

    if host_filter:
        # Two passes: first look for an exact host match (e.g. n100.yml
        # for --host nas), then fall back to shared files (all.yml).
        # This ensures host-specific overrides win over globals.
        exact_match = None
        shared_match = None
        for fpath, value in file_values.items():
            fhost = file_hosts.get(fpath, "both")
            if fhost == host_filter:
                exact_match = value
            elif fhost == "both":
                shared_match = value
        if exact_match is not None:
            return exact_match
        if shared_match is not None:
            return shared_match

    # Default: last defined wins (dict preserves insertion order)
    return list(file_values.values())[-1]


def normalize_version(raw: str, extract_pattern: str | None = None) -> str:
    """
    Make a version string comparable.

    1. Apply optional extract regex (e.g. pull '10.11.6' from
       '10.11.6ubu2404-ls20').
    2. Strip common prefixes: 'v', 'version/'.
    """
    v = str(raw).strip()

    if extract_pattern:
        m = re.search(extract_pattern, v)
        if m:
            v = m.group(1) if m.lastindex else m.group(0)

    for prefix in ("version/", "v"):
        if v.lower().startswith(prefix):
            v = v[len(prefix):]
    return v


def match_version_style(current: str, latest_tag: str) -> str:
    """
    Adapt the latest GitHub tag to match the current version's style.

    Examples:
        current='v3.6.8',    latest='v3.6.11'         -> 'v3.6.11'   (keep v)
        current='11.6.0',    latest='v12.4.1'          -> '12.4.1'    (strip v)
        current='2025.12.3', latest='version/2026.2.1' -> '2026.2.1'  (strip version/)
        current='latest',    latest='v2.11.0'           -> 'v2.11.0'  (use tag as-is)
    """
    tag = latest_tag

    if tag.startswith("version/"):
        tag = tag[len("version/"):]

    current_has_v = current.startswith("v")
    tag_has_v     = tag.startswith("v")

    if current_has_v and not tag_has_v:
        tag = f"v{tag}"
    elif not current_has_v and tag_has_v and current != "latest":
        tag = tag[1:]

    return tag


# -----------------------------------------------------------------
# GitHub API + cache
# -----------------------------------------------------------------

def fetch_latest_release(repo: str, token: str | None = None) -> dict:
    """
    Query GitHub Releases API for the latest stable (non-prerelease)
    release of *repo* (owner/name).
    """
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
            return {
                "tag": data.get("tag_name", ""),
                "url": data.get("html_url", ""),
                "name": data.get("name", ""),
                "published": data.get("published_at", ""),
                "prerelease": data.get("prerelease", False),
            }
    except HTTPError as e:
        if e.code == 404:
            return {"error": "no releases found"}
        if e.code == 403:
            remaining = e.headers.get("X-RateLimit-Remaining", "?")
            reset_ts  = e.headers.get("X-RateLimit-Reset", "")
            reset_in  = ""
            if reset_ts:
                try:
                    reset_in = f" (resets in {int(reset_ts) - int(time.time())}s)"
                except ValueError:
                    pass
            return {"error": f"rate limited (remaining: {remaining}{reset_in})"}
        return {"error": f"HTTP {e.code}"}
    except (URLError, TimeoutError, OSError) as exc:
        return {"error": f"network error: {exc}"}


def load_cache(cache_path: Path) -> dict[str, dict]:
    """Load cached GitHub release responses from a JSON file."""
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path) as f:
            data = json.load(f)
        return data.get("releases", {})
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"{YELLOW}  warning: cache file corrupt ({exc}), ignoring{RESET}",
              file=sys.stderr)
        return {}


def save_cache(cache_path: Path, releases: dict[str, dict]) -> None:
    """Save GitHub release responses to a JSON file."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "releases": releases,
    }
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)


def fetch_releases_parallel(
    tasks: list[tuple[str, str]],
    token: str | None,
    cache_path: Path | None = None,
) -> dict[str, dict]:
    """
    Fetch latest releases for multiple repos in parallel.

    Args:
        tasks: [(service_name, github_repo), ...]
        token: optional GitHub API token
        cache_path: optional path to cache file

    When cache_path is set and the file exists, loads from cache
    instead of hitting the API.  After fetching, saves results
    to the cache file for future runs.

    Returns:
        {service_name: release_dict}
    """
    results: dict[str, dict] = {}

    # Deduplicate repos (e.g. loki + promtail share grafana/loki)
    repo_to_names: dict[str, list[str]] = {}
    for name, repo in tasks:
        repo_to_names.setdefault(repo, []).append(name)

    # Try cache first
    cached: dict[str, dict] = {}
    if cache_path:
        cached = load_cache(cache_path)

    if cached:
        # Use cached responses
        for repo, names in repo_to_names.items():
            release = cached.get(repo, {"error": "not in cache"})
            for name in names:
                results[name] = release
        return results

    # Fetch from GitHub in parallel
    repo_releases: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_repo = {
            pool.submit(fetch_latest_release, repo, token): repo
            for repo in repo_to_names
        }
        for future in as_completed(future_to_repo):
            repo = future_to_repo[future]
            try:
                release = future.result()
            except Exception as exc:
                release = {"error": str(exc)}
            repo_releases[repo] = release
            for name in repo_to_names[repo]:
                results[name] = release

    # Save to cache
    if cache_path:
        save_cache(cache_path, repo_releases)

    return results


# -----------------------------------------------------------------
# Ntfy
# -----------------------------------------------------------------

def send_ntfy(cfg: dict, message: str, title: str) -> bool:
    """
    POST a notification to ntfy. Returns True on success.

    Supports authentication via config:
      ntfy:
        url: "https://ntfy.homelab.local"
        topic: "homelab-updates"
        token: "tk_..."           # optional: ntfy access token
        user: "admin"             # optional: basic auth
        password: "secret"        # optional: basic auth

    The NTFY_TOKEN env var overrides config token.
    """
    url = f"{cfg['url'].rstrip('/')}/{cfg['topic']}"
    headers: dict[str, str] = {
        "Title": title,
        "Priority": "3",
        "Tags": "package",
        "Content-Type": "text/plain; charset=utf-8",
    }

    # Auth: env var token > config token > basic auth > anonymous
    token = os.environ.get("NTFY_TOKEN") or cfg.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif cfg.get("user") and cfg.get("password"):
        creds = base64.b64encode(
            f"{cfg['user']}:{cfg['password']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"

    req = Request(url, data=message.encode("utf-8"),
                  headers=headers, method="POST")
    try:
        urlopen(req, timeout=REQUEST_TIMEOUT)
        return True
    except (URLError, HTTPError, OSError) as exc:
        print(f"{RED}  ntfy send failed: {exc}{RESET}", file=sys.stderr)
        return False


# -----------------------------------------------------------------
# Core checks
# -----------------------------------------------------------------

def check_coupled_drift(
    services: dict,
    version_map: VersionMap,
    host_filter: str | None,
    file_hosts: dict[Path, str],
) -> list[str]:
    """
    Return warnings for coupled services that are pinned to
    different versions (e.g. Loki 3.4.0 + Promtail 3.5.0).
    """
    warnings: list[str] = []
    checked: set[tuple[str, str]] = set()

    for name, svc in services.items():
        for partner in svc.get("coupled_with", []):
            pair = tuple(sorted((name, partner)))
            if pair in checked:
                continue
            checked.add(pair)

            partner_svc = services.get(partner)
            if not partner_svc:
                continue

            v1 = normalize_version(
                resolve_version(svc["variable"], version_map,
                                host_filter, file_hosts),
                svc.get("extract"),
            )
            v2 = normalize_version(
                resolve_version(partner_svc["variable"], version_map,
                                host_filter, file_hosts),
                partner_svc.get("extract"),
            )
            if v1 and v2 and v1 != v2:
                warnings.append(
                    f"{name} ({v1}) != {partner} ({v2}) "
                    f"- should be same version"
                )
    return warnings


def filter_services(
    services: dict,
    host_filter: str | None,
    only_filter: list[str] | None,
) -> dict:
    """Return a filtered subset of services based on --host and --only."""
    filtered = {}
    for name, svc in services.items():
        if host_filter and svc.get("host", "both") not in (host_filter, "both"):
            continue
        if only_filter and name not in only_filter:
            continue
        filtered[name] = svc
    return filtered


def run_checks(
    services: dict,
    version_map: VersionMap,
    file_hosts: dict[Path, str],
    host_filter: str | None,
    token: str | None,
    cache_path: Path | None = None,
) -> tuple[list[CheckResult], int, int]:
    """
    Query GitHub for every service (in parallel) and return
    (results_list, updates_count, error_count).
    """
    results: list[CheckResult] = []
    updates = 0
    errors  = 0

    # Resolve current versions and split skipped from checkable
    to_check: dict[str, tuple[dict, str]] = {}
    for name, svc in services.items():
        variable = svc["variable"]
        current  = resolve_version(variable, version_map,
                                   host_filter, file_hosts)
        if not current or current == "latest":
            results.append(CheckResult(
                name=name, status="skip", variable=variable,
                current=current or "", extract=svc.get("extract"),
                message="no pinned version",
            ))
        else:
            to_check[name] = (svc, current)

    # Fetch all releases in parallel (or from cache)
    fetch_tasks = [(name, svc["github"]) for name, (svc, _) in to_check.items()]
    releases = fetch_releases_parallel(fetch_tasks, token, cache_path)

    # Compare versions (preserve config ordering)
    for name, (svc, current) in to_check.items():
        extract = svc.get("extract")
        release = releases.get(name, {"error": "no result"})

        if "error" in release:
            results.append(CheckResult(
                name=name, status="error", variable=svc["variable"],
                current=current, extract=extract,
                message=release["error"],
            ))
            errors += 1
            continue

        latest_tag   = release["tag"]
        current_norm = normalize_version(current, extract)
        latest_norm  = normalize_version(latest_tag, extract)

        if current_norm == latest_norm:
            results.append(CheckResult(
                name=name, status="up_to_date", variable=svc["variable"],
                current=current, latest=latest_tag, extract=extract,
            ))
        else:
            results.append(CheckResult(
                name=name, status="update", variable=svc["variable"],
                current=current, latest=latest_tag, extract=extract,
                url=release.get("url", ""), note=svc.get("note", ""),
            ))
            updates += 1

    return results, updates, errors


# -----------------------------------------------------------------
# Write mode
# -----------------------------------------------------------------

def write_versions(
    results: list[CheckResult],
    version_map: VersionMap,
    dry_run: bool,
) -> int:
    """
    Update group_vars files in place with latest versions.

    Uses line-level regex replacement to preserve comments, ordering,
    and formatting.  Does NOT use PyYAML to rewrite the file.

    Skips services with 'extract' patterns (LinuxServer compound tags)
    because the upstream tag does not match the Docker image tag.

    When a variable appears in multiple files (e.g. promtail_version
    in both n100.yml and docker_nodes.yml), each file's actual value
    is used for the regex match, so even diverged values are updated
    correctly.

    Returns the number of variables updated.
    """
    # Collect changes grouped by file
    # {filepath: [(variable, old_value, new_value), ...]}
    changes_by_file: dict[Path, list[tuple[str, str, str]]] = {}

    for r in results:
        if r.status != "update":
            continue

        # Skip LinuxServer / compound tag images - we cannot generate
        # the correct Docker tag from the upstream GitHub release.
        if r.extract:
            continue

        file_values = version_map.get(r.variable, {})
        if not file_values:
            continue

        # Schedule the change in EVERY file, using that file's actual value
        for fpath, file_value in file_values.items():
            new_value = match_version_style(file_value, r.latest)
            if file_value == new_value:
                continue
            changes_by_file.setdefault(fpath, []).append(
                (r.variable, file_value, new_value)
            )

    if not changes_by_file:
        print(f"\n  {DIM}No writable updates (LinuxServer images skipped).{RESET}")
        return 0

    total_written = 0

    print(f"\n{BOLD}  {'[DRY RUN] ' if dry_run else ''}Writing versions{RESET}")
    print(f"{'─' * 62}\n")

    for filepath, changes in sorted(changes_by_file.items()):
        relpath = filepath.relative_to(REPO_ROOT)
        print(f"  {CYAN}{relpath}{RESET}")

        content = filepath.read_text()

        for variable, old_value, new_value in changes:
            # Match: variable_name: "value", variable_name: 'value',
            # or variable_name: value (unquoted)
            pattern = re.compile(
                rf"""^({re.escape(variable)}:\s*)['"]?{re.escape(old_value)}['"]?\s*$""",
                re.MULTILINE,
            )
            match = pattern.search(content)
            if not match:
                print(f"    {RED}!!  {variable}: pattern not found, skipping{RESET}")
                continue

            # Detect quoting style: double, single, or bare
            value_part = match.group(0).split(":", 1)[1]
            if '"' in value_part:
                quote = '"'
            elif "'" in value_part:
                quote = "'"
            else:
                quote = ""

            replacement = f"{match.group(1)}{quote}{new_value}{quote}"

            content = pattern.sub(replacement, content, count=1)
            total_written += 1
            print(f"    {YELLOW}{variable}: \"{old_value}\" -> \"{new_value}\"{RESET}")

        if not dry_run:
            filepath.write_text(content)

    print(f"\n{'─' * 62}")
    if dry_run:
        print(f"  {CYAN}Dry run - no files modified. "
              f"Remove --dry-run to apply.{RESET}")
    else:
        print(f"  {GREEN}{total_written} variable(s) updated.{RESET}")
    print()

    return total_written


# -----------------------------------------------------------------
# Output
# -----------------------------------------------------------------

def print_report(
    results: list[CheckResult],
    coupled_warnings: list[str],
    updates: int,
    errors: int,
) -> None:
    """Pretty-print the drift report to stdout."""
    total = len(results)
    up_to_date = total - updates - errors - sum(
        1 for r in results if r.status == "skip"
    )

    print(f"\n{BOLD}  Version Drift Report{RESET}")
    print(f"{'─' * 62}\n")

    if coupled_warnings:
        print(f"  {RED}{BOLD}Coupled Version Drift:{RESET}")
        for w in coupled_warnings:
            print(f"  {RED}  * {w}{RESET}")
        print()

    for r in results:
        label = r.name.ljust(24)
        if r.status == "up_to_date":
            cur = r.current.ljust(18)
            print(f"  {GREEN}OK  {label}{cur}up to date{RESET}")

        elif r.status == "update":
            note = f"  ({r.note})" if r.note else ""
            cur = r.current.ljust(18)
            print(
                f"  {YELLOW}UP  {label}{cur}"
                f"-> {r.latest}{note}{RESET}"
            )
            if r.url:
                print(f"  {DIM}      {r.url}{RESET}")

        elif r.status == "skip":
            print(f"  {DIM}--  {label}{r.message}{RESET}")

        elif r.status == "error":
            print(f"  {RED}!!  {label}{r.message}{RESET}")

    print(f"\n{'─' * 62}")
    parts = []
    if updates:
        parts.append(f"{YELLOW}{updates} updates{RESET}")
    if errors:
        parts.append(f"{RED}{errors} errors{RESET}")
    parts.append(f"{GREEN}{up_to_date} up to date{RESET}")
    print(f"  {' | '.join(parts)}")
    print()


def print_json(
    results: list[CheckResult],
    coupled_warnings: list[str],
    updates: int,
    errors: int,
) -> None:
    """Print machine-readable JSON output to stdout."""
    output = {
        "summary": {
            "updates": updates,
            "errors": errors,
            "up_to_date": sum(1 for r in results if r.status == "up_to_date"),
            "skipped": sum(1 for r in results if r.status == "skip"),
        },
        "coupled_warnings": coupled_warnings,
        "services": [r.to_json_dict() for r in results],
    }

    json.dump(output, sys.stdout, indent=2)
    print()


def build_ntfy_message(
    results: list[CheckResult],
    coupled_warnings: list[str],
    updates: int,
    errors: int,
) -> tuple[str, str]:
    """
    Build a plain-text message and title for ntfy push notification.

    Returns:
        (title, message) - title reflects the actual situation
        (updates, errors, drift), not just update count.
    """
    lines: list[str] = []

    if coupled_warnings:
        lines.append("COUPLED DRIFT:")
        lines.extend(f"  * {w}" for w in coupled_warnings)
        lines.append("")

    if updates:
        lines.append(f"{updates} update(s) available:")
        for r in results:
            if r.status == "update":
                lines.append(f"  * {r.name}: {r.current} -> {r.latest}")
        lines.append("")

    if errors:
        error_results = [r for r in results if r.status == "error"]
        lines.append(f"{errors} check(s) failed:")
        for r in error_results:
            lines.append(f"  * {r.name}: {r.message or 'unknown error'}")
        lines.append("")

    title_parts: list[str] = []
    if updates:
        title_parts.append(f"{updates} update(s)")
    if errors:
        title_parts.append(f"{errors} error(s)")
    if coupled_warnings:
        title_parts.append("coupled drift")
    title = f"Homelab: {', '.join(title_parts)}"

    return title, "\n".join(lines)


# -----------------------------------------------------------------
# CLI
# -----------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Check for version drift in homelab services.",
    )
    p.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="Path to version-check.yml (default: config/version-check.yml)",
    )
    p.add_argument(
        "--notify", action="store_true",
        help="Send results via ntfy (when updates, drift, or errors exist)",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress output when everything is up to date",
    )
    p.add_argument(
        "--host", choices=["nas", "ryzen"],
        help="Only check services on a specific host",
    )
    p.add_argument(
        "--only",
        help="Comma-separated list of service names to check (e.g. grafana,loki)",
    )
    p.add_argument(
        "--write", action="store_true",
        help="Update group_vars files with latest versions",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="With --write: show what would change without modifying files",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output results as JSON (for scripting)",
    )
    p.add_argument(
        "--cache", type=Path, default=None, metavar="PATH",
        help="Cache GitHub responses to a JSON file (reuse on next run)",
    )
    return p.parse_args()


def main() -> None:
    args   = parse_args()
    config = load_config(args.config)

    services  = config.get("services", {})
    ntfy_cfg  = config.get("ntfy", {})
    gv_raw    = config.get("group_vars", [])
    token     = os.environ.get("GITHUB_TOKEN")

    # Parse group_vars config (supports both simple and explicit formats)
    gv_entries = parse_group_vars_config(gv_raw)

    # Parse --only filter
    only_filter = None
    if args.only:
        only_filter = [s.strip() for s in args.only.split(",")]
        unknown = [s for s in only_filter if s not in services]
        if unknown:
            print(f"{RED}Unknown service(s): {', '.join(unknown)}{RESET}",
                  file=sys.stderr)
            print(f"{DIM}Available: {', '.join(services.keys())}{RESET}",
                  file=sys.stderr)
            sys.exit(2)

    # Apply filters
    services = filter_services(services, args.host, only_filter)

    # Load current pinned versions (per-file) and host mapping
    version_map, file_hosts = load_current_versions(gv_entries)

    # Detect coupled drift
    coupled_warnings = check_coupled_drift(
        services, version_map, args.host, file_hosts,
    )

    # Query GitHub for each service (parallel, with optional cache)
    results, updates, errors = run_checks(
        services, version_map, file_hosts, args.host, token, args.cache,
    )

    # Output
    anything_notable = updates > 0 or errors > 0 or coupled_warnings

    if args.json_output:
        print_json(results, coupled_warnings, updates, errors)
    elif not args.quiet or anything_notable:
        print_report(results, coupled_warnings, updates, errors)

    # Write mode
    if args.write:
        write_versions(results, version_map, dry_run=args.dry_run)

    # Push notification
    if args.notify and ntfy_cfg and anything_notable:
        title, msg = build_ntfy_message(
            results, coupled_warnings, updates, errors,
        )
        ok = send_ntfy(ntfy_cfg, msg, title)
        if ok and not args.json_output:
            print(f"  {GREEN}Notification sent to ntfy.{RESET}")
        elif not ok:
            print(f"  {RED}Failed to send ntfy notification.{RESET}",
                  file=sys.stderr)

    # Exit code: 0 = all good, 1 = updates/drift/errors exist
    sys.exit(0 if not anything_notable else 1)


if __name__ == "__main__":
    main()

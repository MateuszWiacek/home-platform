"""
Unit tests for scripts/version-check.py

Run:
    python -m pytest tests/test_version_check.py -v
    python -m pytest tests/test_version_check.py -v -k normalize
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# -- Load the script as a module (it has a hyphen in the filename) --
# Register in sys.modules BEFORE exec so dataclasses can resolve
# type annotations via sys.modules[cls.__module__] (Python 3.9 compat).
_spec = importlib.util.spec_from_file_location(
    "version_check",
    Path(__file__).resolve().parent.parent / "scripts" / "version-check.py",
)
vc = importlib.util.module_from_spec(_spec)
sys.modules["version_check"] = vc
_spec.loader.exec_module(vc)


# =================================================================
# normalize_version
# =================================================================

class TestNormalizeVersion:
    def test_strips_v_prefix(self):
        assert vc.normalize_version("v3.6.8") == "3.6.8"

    def test_strips_version_prefix(self):
        assert vc.normalize_version("version/2026.2.1") == "2026.2.1"

    def test_no_prefix(self):
        assert vc.normalize_version("11.6.0") == "11.6.0"

    def test_extract_pattern(self):
        assert vc.normalize_version(
            "10.11.6ubu2404-ls20", r"([\d.]+)"
        ) == "10.11.6"

    def test_extract_pattern_with_v(self):
        assert vc.normalize_version(
            "v2.0.15-ls211", r"([\d.]+)"
        ) == "2.0.15"

    def test_empty_string(self):
        assert vc.normalize_version("") == ""

    def test_latest(self):
        assert vc.normalize_version("latest") == "latest"


# =================================================================
# match_version_style
# =================================================================

class TestMatchVersionStyle:
    def test_keep_v_prefix(self):
        assert vc.match_version_style("v3.6.8", "v3.6.11") == "v3.6.11"

    def test_strip_v_when_current_has_none(self):
        assert vc.match_version_style("11.6.0", "v12.4.1") == "12.4.1"

    def test_add_v_when_current_has_it(self):
        assert vc.match_version_style("v1.0.0", "1.2.0") == "v1.2.0"

    def test_strip_version_prefix(self):
        assert vc.match_version_style("2025.12.3", "version/2026.2.1") == "2026.2.1"

    def test_latest_uses_tag_as_is(self):
        assert vc.match_version_style("latest", "v2.11.0") == "v2.11.0"


# =================================================================
# parse_group_vars_config
# =================================================================

class TestParseGroupVarsConfig:
    def test_simple_format(self):
        result = vc.parse_group_vars_config([
            "group_vars/all.yml",
            "group_vars/n100.yml",
            "group_vars/docker_nodes.yml",
        ])
        assert result == [
            ("group_vars/all.yml", "both"),
            ("group_vars/n100.yml", "nas"),
            ("group_vars/docker_nodes.yml", "ryzen"),
        ]

    def test_explicit_format(self):
        result = vc.parse_group_vars_config([
            {"path": "group_vars/custom.yml", "host": "nas"},
        ])
        assert result == [("group_vars/custom.yml", "nas")]

    def test_mixed_format(self):
        result = vc.parse_group_vars_config([
            "group_vars/all.yml",
            {"path": "group_vars/special.yml", "host": "ryzen"},
        ])
        assert len(result) == 2
        assert result[0] == ("group_vars/all.yml", "both")
        assert result[1] == ("group_vars/special.yml", "ryzen")

    def test_unknown_filename_defaults_to_both(self):
        result = vc.parse_group_vars_config(["group_vars/unknown.yml"])
        assert result == [("group_vars/unknown.yml", "both")]

    def test_dict_missing_path_key_is_skipped(self):
        result = vc.parse_group_vars_config([
            {"host": "nas"},  # missing "path" key
            "group_vars/all.yml",
        ])
        assert len(result) == 1
        assert result[0] == ("group_vars/all.yml", "both")


# =================================================================
# load_current_versions
# =================================================================

class TestLoadCurrentVersions:
    def test_per_file_tracking(self, tmp_path):
        nas = tmp_path / "n100.yml"
        ryzen = tmp_path / "docker_nodes.yml"
        nas.write_text("promtail_version: '3.4.0'\nntfy_version: 'v2.11.0'\n")
        ryzen.write_text("promtail_version: '3.5.0'\ngrafana_version: '11.6.0'\n")

        entries = [
            (str(nas), "nas"),
            (str(ryzen), "ryzen"),
        ]
        # Patch REPO_ROOT so relative paths work
        with patch.object(vc, "REPO_ROOT", tmp_path):
            vmap, fhosts = vc.load_current_versions([
                (str(nas.relative_to(tmp_path)), "nas"),
                (str(ryzen.relative_to(tmp_path)), "ryzen"),
            ])

        # promtail tracked in both files with their actual values
        assert nas in vmap["promtail_version"]
        assert ryzen in vmap["promtail_version"]
        assert vmap["promtail_version"][nas] == "3.4.0"
        assert vmap["promtail_version"][ryzen] == "3.5.0"

        # ntfy only in NAS
        assert nas in vmap["ntfy_version"]
        assert ryzen not in vmap["ntfy_version"]

        # host mapping
        assert fhosts[nas] == "nas"
        assert fhosts[ryzen] == "ryzen"


# =================================================================
# resolve_version
# =================================================================

class TestResolveVersion:
    @pytest.fixture()
    def setup(self, tmp_path):
        nas = tmp_path / "n100.yml"
        ryzen = tmp_path / "docker_nodes.yml"
        version_map = {
            "promtail_version": {
                nas: "3.4.0",
                ryzen: "3.5.0",
            },
            "traefik_version": {
                nas: "v3.6.8",
            },
        }
        file_hosts = {nas: "nas", ryzen: "ryzen"}
        return version_map, file_hosts

    def test_no_filter_last_wins(self, setup):
        vmap, fhosts = setup
        # No host filter - last value (ryzen) wins
        v = vc.resolve_version("promtail_version", vmap, None, fhosts)
        assert v == "3.5.0"

    def test_host_nas(self, setup):
        vmap, fhosts = setup
        v = vc.resolve_version("promtail_version", vmap, "nas", fhosts)
        assert v == "3.4.0"

    def test_host_ryzen(self, setup):
        vmap, fhosts = setup
        v = vc.resolve_version("promtail_version", vmap, "ryzen", fhosts)
        assert v == "3.5.0"

    def test_single_file_variable(self, setup):
        vmap, fhosts = setup
        v = vc.resolve_version("traefik_version", vmap, "nas", fhosts)
        assert v == "v3.6.8"

    def test_missing_variable(self, setup):
        vmap, fhosts = setup
        v = vc.resolve_version("nonexistent_version", vmap, None, fhosts)
        assert v == ""

    def test_host_specific_overrides_shared(self, tmp_path):
        """--host nas should prefer n100.yml over all.yml."""
        all_yml = tmp_path / "all.yml"
        nas_yml = tmp_path / "n100.yml"
        # all.yml loaded first (insertion order), nas second
        vmap = {"promtail_version": {all_yml: "3.4.0", nas_yml: "3.5.0"}}
        fhosts = {all_yml: "both", nas_yml: "nas"}
        v = vc.resolve_version("promtail_version", vmap, "nas", fhosts)
        assert v == "3.5.0"  # nas-specific wins, not all.yml's "both"

    def test_falls_back_to_shared_when_no_exact_match(self, tmp_path):
        """--host nas falls back to all.yml if no nas-specific file."""
        all_yml = tmp_path / "all.yml"
        vmap = {"some_version": {all_yml: "1.0.0"}}
        fhosts = {all_yml: "both"}
        v = vc.resolve_version("some_version", vmap, "nas", fhosts)
        assert v == "1.0.0"


# =================================================================
# check_coupled_drift
# =================================================================

class TestCheckCoupledDrift:
    def test_no_drift(self, tmp_path):
        nas = tmp_path / "n100.yml"
        services = {
            "loki": {"variable": "loki_version", "coupled_with": ["promtail"]},
            "promtail": {"variable": "promtail_version", "coupled_with": ["loki"]},
        }
        vmap = {
            "loki_version": {nas: "3.5.0"},
            "promtail_version": {nas: "3.5.0"},
        }
        fhosts = {nas: "nas"}
        warnings = vc.check_coupled_drift(services, vmap, None, fhosts)
        assert warnings == []

    def test_drift_detected(self, tmp_path):
        nas = tmp_path / "n100.yml"
        services = {
            "loki": {"variable": "loki_version", "coupled_with": ["promtail"]},
            "promtail": {"variable": "promtail_version", "coupled_with": ["loki"]},
        }
        vmap = {
            "loki_version": {nas: "3.4.0"},
            "promtail_version": {nas: "3.5.0"},
        }
        fhosts = {nas: "nas"}
        warnings = vc.check_coupled_drift(services, vmap, None, fhosts)
        assert len(warnings) == 1
        assert "3.4.0" in warnings[0]
        assert "3.5.0" in warnings[0]


# =================================================================
# filter_services
# =================================================================

class TestFilterServices:
    SERVICES = {
        "traefik": {"host": "nas", "variable": "traefik_version"},
        "grafana": {"host": "ryzen", "variable": "grafana_version"},
        "promtail": {"host": "both", "variable": "promtail_version"},
    }

    def test_no_filter(self):
        result = vc.filter_services(self.SERVICES, None, None)
        assert len(result) == 3

    def test_host_nas(self):
        result = vc.filter_services(self.SERVICES, "nas", None)
        assert set(result.keys()) == {"traefik", "promtail"}

    def test_host_ryzen(self):
        result = vc.filter_services(self.SERVICES, "ryzen", None)
        assert set(result.keys()) == {"grafana", "promtail"}

    def test_only_filter(self):
        result = vc.filter_services(self.SERVICES, None, ["grafana"])
        assert set(result.keys()) == {"grafana"}

    def test_host_and_only(self):
        result = vc.filter_services(self.SERVICES, "nas", ["promtail"])
        assert set(result.keys()) == {"promtail"}


# =================================================================
# write_versions (per-file old_value)
# =================================================================

class TestWriteVersions:
    def test_updates_both_files_with_different_values(self, tmp_path):
        nas = tmp_path / "n100.yml"
        ryzen = tmp_path / "docker_nodes.yml"
        nas.write_text('promtail_version: "3.4.0"\n')
        ryzen.write_text('promtail_version: "3.5.0"\n')

        version_map = {
            "promtail_version": {
                nas: "3.4.0",
                ryzen: "3.5.0",
            },
        }

        results = [vc.CheckResult(
            name="promtail", status="update",
            current="3.5.0", latest="v3.6.7",
            variable="promtail_version",
        )]

        with patch.object(vc, "REPO_ROOT", tmp_path):
            count = vc.write_versions(results, version_map, dry_run=False)

        assert count == 2
        assert '"3.6.7"' in nas.read_text()
        assert '"3.6.7"' in ryzen.read_text()

    def test_dry_run_does_not_modify(self, tmp_path):
        f = tmp_path / "test.yml"
        f.write_text('grafana_version: "11.6.0"\n')

        version_map = {"grafana_version": {f: "11.6.0"}}
        results = [vc.CheckResult(
            name="grafana", status="update",
            current="11.6.0", latest="v12.4.1",
            variable="grafana_version",
        )]

        with patch.object(vc, "REPO_ROOT", tmp_path):
            count = vc.write_versions(results, version_map, dry_run=True)

        assert count == 1
        assert '"11.6.0"' in f.read_text()  # unchanged

    def test_skips_extract_services(self, tmp_path):
        f = tmp_path / "test.yml"
        f.write_text('jellyfin_version: "10.11.6ubu2404-ls20"\n')

        version_map = {"jellyfin_version": {f: "10.11.6ubu2404-ls20"}}
        results = [vc.CheckResult(
            name="jellyfin", status="update",
            current="10.11.6ubu2404-ls20", latest="v10.12.0",
            variable="jellyfin_version", extract=r"([\d.]+)",
        )]

        with patch.object(vc, "REPO_ROOT", tmp_path):
            count = vc.write_versions(results, version_map, dry_run=False)

        assert count == 0
        assert "10.11.6ubu2404-ls20" in f.read_text()  # unchanged

    def test_preserves_unquoted_style(self, tmp_path):
        f = tmp_path / "test.yml"
        f.write_text("node_exporter_version: v1.9.0\n")

        version_map = {"node_exporter_version": {f: "v1.9.0"}}
        results = [vc.CheckResult(
            name="node_exporter", status="update",
            current="v1.9.0", latest="v1.10.2",
            variable="node_exporter_version",
        )]

        with patch.object(vc, "REPO_ROOT", tmp_path):
            vc.write_versions(results, version_map, dry_run=False)

        content = f.read_text()
        assert "v1.10.2" in content
        assert '"' not in content  # stayed unquoted

    def test_preserves_single_quote_style(self, tmp_path):
        f = tmp_path / "test.yml"
        f.write_text("promtail_version: '3.5.0'\n")

        version_map = {"promtail_version": {f: "3.5.0"}}
        results = [vc.CheckResult(
            name="promtail", status="update",
            current="3.5.0", latest="v3.6.7",
            variable="promtail_version",
        )]

        with patch.object(vc, "REPO_ROOT", tmp_path):
            vc.write_versions(results, version_map, dry_run=False)

        content = f.read_text()
        assert "'3.6.7'" in content
        assert '"' not in content  # stayed single-quoted


# =================================================================
# build_ntfy_message
# =================================================================

class TestBuildNtfyMessage:
    def _result(self, **kwargs) -> vc.CheckResult:
        """Shorthand to build a CheckResult with defaults."""
        defaults = {"variable": "test_version", "current": ""}
        return vc.CheckResult(**{**defaults, **kwargs})

    def test_updates_only(self):
        results = [
            self._result(name="grafana", status="update",
                         current="11.6.0", latest="v12.4.1"),
        ]
        title, msg = vc.build_ntfy_message(results, [], updates=1, errors=0)
        assert "1 update(s)" in title
        assert "error" not in title
        assert "grafana" in msg

    def test_errors_only(self):
        results = [
            self._result(name="grafana", status="error",
                         current="11.6.0", message="rate limited"),
        ]
        title, msg = vc.build_ntfy_message(results, [], updates=0, errors=1)
        assert "1 error(s)" in title
        assert "update" not in title
        assert "rate limited" in msg

    def test_mixed(self):
        results = [
            self._result(name="grafana", status="update",
                         current="11.6.0", latest="v12.4.1"),
            self._result(name="loki", status="error",
                         current="3.5.0", message="network error"),
        ]
        title, msg = vc.build_ntfy_message(
            results, ["loki (3.4.0) != promtail (3.5.0)"],
            updates=1, errors=1,
        )
        assert "1 update(s)" in title
        assert "1 error(s)" in title
        assert "coupled drift" in title
        assert "COUPLED DRIFT" in msg

    def test_empty_when_nothing(self):
        title, msg = vc.build_ntfy_message([], [], updates=0, errors=0)
        assert title == "Homelab: "
        assert msg == ""


# =================================================================
# Cache
# =================================================================

# =================================================================
# CheckResult.to_json_dict
# =================================================================

class TestCheckResultJson:
    def test_update_result(self):
        r = vc.CheckResult(
            name="grafana", status="update", variable="grafana_version",
            current="11.6.0", latest="v12.4.1", url="https://example.com",
            note="check changelog",
        )
        d = r.to_json_dict()
        assert d["name"] == "grafana"
        assert d["latest"] == "v12.4.1"
        assert d["release_url"] == "https://example.com"
        assert d["writable"] is True

    def test_update_with_extract_not_writable(self):
        r = vc.CheckResult(
            name="jellyfin", status="update", variable="jellyfin_version",
            current="10.11.6", latest="v10.12.0", extract=r"([\d.]+)",
        )
        d = r.to_json_dict()
        assert d["writable"] is False

    def test_error_result(self):
        r = vc.CheckResult(
            name="loki", status="error", variable="loki_version",
            current="3.5.0", message="rate limited",
        )
        d = r.to_json_dict()
        assert d["error"] == "rate limited"
        assert "latest" not in d

    def test_skip_result(self):
        r = vc.CheckResult(
            name="excalidraw", status="skip", variable="excalidraw_version",
            current="latest", message="no pinned version",
        )
        d = r.to_json_dict()
        assert d["reason"] == "no pinned version"
        assert "latest" not in d


# =================================================================
# Cache
# =================================================================

class TestCache:
    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        releases = {
            "grafana/loki": {"tag": "v3.6.7", "url": "https://example.com"},
        }
        vc.save_cache(cache_file, releases)
        loaded = vc.load_cache(cache_file)
        assert loaded == releases

    def test_load_missing_file(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        assert vc.load_cache(cache_file) == {}

    def test_load_corrupt_file(self, tmp_path):
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("not json")
        assert vc.load_cache(cache_file) == {}

    def test_fetch_uses_cache_when_available(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        releases = {
            "grafana/loki": {"tag": "v3.6.7"},
        }
        vc.save_cache(cache_file, releases)

        tasks = [("loki", "grafana/loki"), ("promtail", "grafana/loki")]
        results = vc.fetch_releases_parallel(tasks, token=None, cache_path=cache_file)

        # Both should get the cached result, no API calls made
        assert results["loki"]["tag"] == "v3.6.7"
        assert results["promtail"]["tag"] == "v3.6.7"

#!/usr/bin/env python3
"""Produce the public / portfolio copy of this repo from the private source.

The private repo is the source of truth. This tool exports a clean tree from a
git ref, strips operational identifiers, drops private-only stacks, and then
*proves* the result carries no known-sensitive token before anything is written.

Usage:
    # Dry run + leak gate (use in CI on the public repo, or before publishing):
    scripts/sanitize-for-publication.py --check

    # Render the sanitized tree into a checked-out public repo working copy:
    scripts/sanitize-for-publication.py --dest ../home-platform

By default it publishes from `main`; override with --ref. Exits non-zero if the
verification denylist matches anything in the output: that is the leak gate.

Binary files (images, GIFs) are copied verbatim and NOT scanned. Screenshots and
recordings must be checked by eye for real identifiers before they are committed
to the private repo; the run summary lists every binary file it shipped.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "publication-filter.yml"


def load_config(path: Path) -> dict:
    if not path.is_file():
        sys.exit(
            f"error: filter config not found at {path}.\n"
            "This is private tooling: the rule config (which carries the real "
            "value mappings) is intentionally not published, so the script "
            "cannot run from the public copy. Run it from the private repo, or "
            "pass --config pointing at your own rules."
        )
    with path.open() as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("substitutions", [])
    cfg.setdefault("exclude_paths", [])
    cfg.setdefault("delete_lines", [])
    cfg.setdefault("delete_blocks", [])
    cfg.setdefault("verify_absent", [])
    return cfg


def export_ref(ref: str, dest: Path) -> None:
    """Extract a clean tree of `ref` (committed files only) into dest."""
    try:
        archive = subprocess.run(
            ["git", "archive", "--format=tar", ref],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError:
        sys.exit(f"error: '{ref}' is not a valid git ref in {REPO_ROOT}")
    with tempfile.TemporaryFile() as tmp:
        tmp.write(archive)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tar:
            tar.extractall(dest)


def is_excluded(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip("/*") + "/*"):
            return True
        # support "dir/**" matching the dir itself and everything under it
        base = pat[:-3] if pat.endswith("/**") else pat
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return None  # binary; leave untouched


def apply_substitutions(text: str, subs: list[dict]) -> tuple[str, int]:
    total = 0
    for sub in subs:
        find, replace = sub["find"], sub["replace"]
        count = text.count(find)
        if count:
            text = text.replace(find, replace)
            total += count
    return text, total


def apply_deletions(rel: str, text: str, rules: list[dict]) -> tuple[str, int]:
    removed = 0
    matchers = [re.compile(r["match"]) for r in rules if r["file"] == rel]
    if not matchers:
        return text, 0
    kept = []
    for line in text.splitlines(keepends=True):
        if any(m.search(line) for m in matchers):
            removed += 1
            continue
        kept.append(line)
    return "".join(kept), removed


_JINJA_IF = re.compile(r"{%-?\s*if\b")
_JINJA_ENDIF = re.compile(r"{%-?\s*endif\s*-?%}")


def apply_block_deletions(rel: str, text: str, rules: list[dict]) -> tuple[str, int]:
    """Remove `{% if <open> %}` ... `{% endif %}` blocks, nesting-aware."""
    openers = [re.compile(r["open"]) for r in rules if r["file"] == rel]
    if not openers:
        return text, 0
    removed = 0
    out: list[str] = []
    depth = 0  # >0 means we are inside a block being deleted
    for line in text.splitlines(keepends=True):
        if depth == 0:
            if _JINJA_IF.search(line) and any(o.search(line) for o in openers):
                depth = 1
                removed += 1
                continue
            out.append(line)
        else:
            if _JINJA_IF.search(line):
                depth += 1
            elif _JINJA_ENDIF.search(line):
                depth -= 1
            removed += 1
    return "".join(out), removed


def strip_trailing_blank_lines(text: str) -> str:
    """Drop trailing blank/whitespace-only lines; keep exactly one final newline."""
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return ("\n".join(lines) + "\n") if lines else ""


def verify(tree: Path, patterns: list[str]) -> list[str]:
    """Return a list of leak findings ('file:line: token'); empty means clean."""
    compiled = [(p, re.compile(p)) for p in patterns]
    findings: list[str] = []
    for path in sorted(tree.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(tree).as_posix()
        for raw, rx in compiled:
            if rx.search(rel):
                findings.append(f"{rel}: path matches /{raw}/")
        text = read_text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for raw, rx in compiled:
                if rx.search(line):
                    findings.append(f"{rel}:{lineno}: matches /{raw}/  -> {line.strip()[:80]}")
    return findings


def sync_into(staging: Path, dest: Path) -> None:
    """Mirror staging into dest, preserving dest/.git."""
    # A normal clone has .git as a directory; a worktree has it as a file that
    # points at the real gitdir. Accept both so --dest can be either.
    if dest.exists() and any(dest.iterdir()) and not (dest / ".git").exists():
        sys.exit(
            f"error: {dest} is non-empty and is not a git working copy. Refusing "
            "to overwrite. Point --dest at your public repo (clone or worktree)."
        )
    dest.mkdir(parents=True, exist_ok=True)
    for child in dest.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for item in staging.iterdir():
        target = dest / item.name
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="main", help="git ref to publish from (default: main)")
    ap.add_argument("--dest", type=Path, help="public repo working copy to render into")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--check", action="store_true", help="dry run: stage + verify only, write nothing")
    args = ap.parse_args()

    if not args.check and not args.dest:
        ap.error("provide --dest to render, or --check for a dry run")

    cfg = load_config(args.config)

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw"
        staged = Path(tmp) / "staged"
        raw.mkdir()
        staged.mkdir()
        export_ref(args.ref, raw)

        copied = excluded = subs_total = lines_removed = 0
        binary_files: list[str] = []
        for path in sorted(raw.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(raw).as_posix()
            if is_excluded(rel, cfg["exclude_paths"]):
                excluded += 1
                continue
            out = staged / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            text = read_text(path)
            if text is None:
                shutil.copy2(path, out)  # binary: copied verbatim, NOT scanned
                binary_files.append(rel)
            else:
                text, n = apply_substitutions(text, cfg["substitutions"])
                text, d = apply_deletions(rel, text, cfg["delete_lines"])
                text, b = apply_block_deletions(rel, text, cfg["delete_blocks"])
                if d + b:
                    text = strip_trailing_blank_lines(text)
                subs_total += n
                lines_removed += d + b
                out.write_text(text, encoding="utf-8")
                out.chmod(path.stat().st_mode & 0o777)
            copied += 1

        print(f"source ref      : {args.ref}")
        print(f"files published : {copied}")
        print(f"files excluded  : {excluded}")
        print(f"substitutions   : {subs_total}")
        print(f"orphan lines cut: {lines_removed}")
        if binary_files:
            print(f"binary (UNSCANNED, review by eye): {len(binary_files)}")
            for rel in binary_files:
                print(f"  {rel}")

        findings = verify(staged, cfg["verify_absent"])
        if findings:
            print(f"\nLEAK GATE FAILED: {len(findings)} finding(s):", file=sys.stderr)
            for f in findings[:50]:
                print(f"  {f}", file=sys.stderr)
            return 1
        print("leak gate       : PASS (no sensitive tokens in output)")

        if args.check:
            print("\n--check: nothing written.")
            return 0

        sync_into(staged, args.dest)
        print(f"\nrendered into   : {args.dest}")
        print("Review `git status` / `git diff` there, then commit when satisfied.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

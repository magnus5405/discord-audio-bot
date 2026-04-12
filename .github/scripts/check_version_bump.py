#!/usr/bin/env python3
"""Fail unless PR branch bumps semver vs base and pyproject matches src/__init__.py."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    from packaging.version import Version
except ImportError:
    print("packaging is required (pip install packaging)", file=sys.stderr)
    sys.exit(1)


def _run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _read_file_at_rev(path: str, rev: str) -> str:
    return subprocess.check_output(["git", "show", f"{rev}:{path}"], text=True)


def _parse_pyproject_version(content: str) -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', content)
    if not m:
        raise ValueError("Could not find version = \"...\" in pyproject.toml")
    return m.group(1).strip()


def _parse_init_version(content: str) -> str:
    m = re.search(r'(?m)^__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        raise ValueError("Could not find __version__ in src/__init__.py")
    return m.group(1).strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base_sha", help="Base branch commit (e.g. github.event.pull_request.base.sha)")
    p.add_argument("head_sha", help="PR merge commit SHA (e.g. github.sha on pull_request)")
    args = p.parse_args()

    _ = Path(_run_git(["rev-parse", "--show-toplevel"]))
    try:
        base_ver_py = _parse_pyproject_version(_read_file_at_rev("pyproject.toml", args.base_sha))
        head_ver_py = _parse_pyproject_version(_read_file_at_rev("pyproject.toml", args.head_sha))
        base_ver_init = _parse_init_version(_read_file_at_rev("src/__init__.py", args.base_sha))
        head_ver_init = _parse_init_version(_read_file_at_rev("src/__init__.py", args.head_sha))
    except subprocess.CalledProcessError as e:
        print(f"git show failed: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    if head_ver_py != head_ver_init:
        print(
            f"Version mismatch on PR head: pyproject.toml says {head_ver_py!r}, "
            f"src/__init__.py says {head_ver_init!r}.",
            file=sys.stderr,
        )
        return 1

    vb, vh = Version(base_ver_py), Version(head_ver_py)
    if vh <= vb:
        print(
            f"Version must increase for PRs into latest: base {vb} -> head {vh} "
            f"(pyproject.toml / __init__.py were {base_ver_py} on base).",
            file=sys.stderr,
        )
        return 1

    if base_ver_py != base_ver_init:
        print(
            f"Warning: base branch has mismatched versions "
            f"(pyproject {base_ver_py!r} vs __init__ {base_ver_init!r}); "
            f"still requiring head bump vs pyproject base {base_ver_py}.",
            file=sys.stderr,
        )

    print(f"OK: version bump {vb} -> {vh} (pyproject and __init__ agree on head).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

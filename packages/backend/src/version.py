"""Version and build information for Ancroo Backend."""

import re
import subprocess
from functools import lru_cache
from pathlib import Path

_SRC_DIR = Path(__file__).parent


def _read_build_file(name: str) -> str | None:
    """Read a build-time file from the src directory (written during Docker build)."""
    path = _SRC_DIR / name
    if path.is_file():
        content = path.read_text().strip()
        if content:
            return content
    return None


def _git_describe() -> tuple[str, str]:
    """Derive version and commit from git tags.

    Uses ``git describe --tags --always --match 'v*'`` to determine the
    current version based on the nearest release tag.

    Returns:
        ``(version, commit)`` tuple.  *version* is e.g. ``"1.2.3"`` (on a
        tag), ``"1.2.3-dev.5"`` (5 commits after a tag), or the short
        commit hash when no ``v*`` tags exist.
    """
    try:
        describe = subprocess.run(
            ["git", "describe", "--tags", "--always", "--match", "v*"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if describe.returncode != 0:
            return ("dev", "dev")

        raw = describe.stdout.strip()

        commit_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = (
            commit_result.stdout.strip()
            if commit_result.returncode == 0
            else "dev"
        )

        # Exactly on a tag: "v1.2.3"
        exact = re.match(r"^v(\d+\.\d+\.\d+)$", raw)
        if exact:
            return (exact.group(1), commit)

        # After a tag: "v1.2.3-5-gabcdef"
        dev = re.match(r"^v(\d+\.\d+\.\d+)-(\d+)-g[0-9a-f]+$", raw)
        if dev:
            return (f"{dev.group(1)}-dev.{dev.group(2)}", commit)

        # No v* tags: just a commit hash
        return (raw, raw)

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ("dev", "dev")


def _get_version() -> str:
    """Get the application version.

    Priority: BUILD_VERSION file (Docker) > git describe > fallback.
    """
    build_version = _read_build_file("BUILD_VERSION")
    if build_version:
        return build_version
    version, _ = _git_describe()
    return version


def _get_commit() -> str:
    """Get the commit hash.

    Priority: BUILD_COMMIT file (Docker) > git describe > fallback.
    """
    build_commit = _read_build_file("BUILD_COMMIT")
    if build_commit:
        return build_commit
    _, commit = _git_describe()
    return commit


@lru_cache
def get_version_info() -> dict[str, str]:
    """Get cached version and build information."""
    return {
        "name": "Ancroo",
        "description": "AI Workflow Runner — Backend",
        "version": _get_version(),
        "commit": _get_commit(),
        "author": "Stefan Schmidbauer",
        "license": "AGPL-3.0",
        "repository": "https://github.com/Stefan-Schmidbauer/ancroo-backend",
    }

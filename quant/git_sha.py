"""Capture the git SHA + dirty-tree state for reproducible backtest runs.

Policy:
  - Clean tree → return the 40-char SHA (or short-SHA if `short=True`).
  - Dirty tree + `allow_dirty=False` (default) → raise, forcing the caller to
    commit / stash before a named run. Prevents "why don't these numbers match"
    debugging pain later.
  - Dirty tree + `allow_dirty=True` → return `<sha>-dirty-<unix_ts>` so the
    run is stamped distinctly and cannot silently dedup with a clean run.
  - Not a git repo / no git on PATH → return the string literal `"unknown"`.

In Modal deploy mode, the container image bakes `MODAL_GIT_SHA` via
`Image.env(...)`; the per-combo function echoes that back so the orchestrator
can verify image-cache consistency.
"""
from __future__ import annotations

import os
import subprocess
import time


class DirtyTreeError(RuntimeError):
    """Raised when the working tree has uncommitted changes and --allow-dirty
    was not set. The message lists the offending files so the operator can
    decide whether to commit / stash / override."""


def _run(args: list[str]) -> str:
    return subprocess.check_output(
        args, text=True, stderr=subprocess.DEVNULL
    ).strip()


def capture_git_sha(allow_dirty: bool = False, short: bool = False) -> str:
    """Return the current git SHA, refusing on dirty tree unless allowed."""
    # Preferred sources, in order:
    #   MODAL_GIT_SHA     — baked into Modal image at deploy time
    #   RAILWAY_GIT_COMMIT_SHA — injected by Railway at build time
    #   GIT_COMMIT_SHA    — generic override
    for env_var in ("MODAL_GIT_SHA", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA"):
        env_sha = os.environ.get(env_var, "").strip()
        if env_sha:
            return env_sha[:12] if short else env_sha

    try:
        sha = _run(["git", "rev-parse", "HEAD"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"

    if short:
        sha = sha[:12]

    try:
        dirty_output = _run(["git", "status", "--porcelain"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        dirty_output = ""

    if not dirty_output:
        return sha

    # Ephemeral deploy environments (Railway, Docker) aren't git checkouts —
    # treat that case the same as "no git" to avoid spurious dirty errors.
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("MODAL_IS_REMOTE"):
        return sha

    if not allow_dirty:
        first_files = "\n  ".join(dirty_output.splitlines()[:10])
        raise DirtyTreeError(
            "Working tree has uncommitted changes. Commit, stash, or pass "
            "--allow-dirty (run will be stamped -dirty and won't dedup).\n"
            f"Dirty files:\n  {first_files}"
        )

    return f"{sha}-dirty-{int(time.time())}"


__all__ = ["capture_git_sha", "DirtyTreeError"]

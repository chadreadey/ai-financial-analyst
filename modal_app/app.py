"""Modal app + image + secrets + volumes.

Session 1 scope: dev-mode only (local source mounted into the image).
Deploy mode (`git clone @MODAL_GIT_SHA` + env pin) is deferred to Session 1b.

One app hosts all CPCV + smoke + future sweep functions; per-function
resource overrides live in their respective modules.
"""
from __future__ import annotations

import os
import modal

APP_NAME = "ai-financial-analyst"
PANELS_VOLUME_NAME = "cpcv-panels"
SECRETS_NAME = "ai-financial-analyst-secrets"

MODE = os.environ.get("MODAL_MODE", "dev").lower()


def _build_image() -> modal.Image:
    """Build the Modal image. Dev mode mounts local source; deploy mode pins
    to a git SHA. Session 1 ships dev only."""
    base = (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("git")
        .pip_install_from_requirements("requirements.txt")
    )

    if MODE == "dev":
        return base.add_local_python_source(
            "quant",
            "price_provider",
            "fmp_client",
            "finnhub_client",
            copy=False,
        )

    if MODE == "deploy":
        git_sha = os.environ.get("MODAL_GIT_SHA", "").strip()
        if not git_sha:
            raise RuntimeError(
                "MODAL_MODE=deploy requires MODAL_GIT_SHA (40-char commit hash)."
            )
        repo_url = os.environ.get(
            "MODAL_REPO_URL",
            "https://github.com/chadreadey/ai-financial-analyst.git",
        )
        return (
            base.run_commands(
                f"git clone {repo_url} /root/app",
                f"git -C /root/app checkout {git_sha}",
            )
            .env({"MODAL_GIT_SHA": git_sha, "PYTHONPATH": "/root/app"})
        )

    raise ValueError(f"Unknown MODAL_MODE={MODE!r}; expected 'dev' or 'deploy'.")


image = _build_image()
secrets = [modal.Secret.from_name(SECRETS_NAME)]
panels_volume = modal.Volume.from_name(PANELS_VOLUME_NAME, create_if_missing=True)

app = modal.App(APP_NAME, image=image)


__all__ = [
    "APP_NAME",
    "PANELS_VOLUME_NAME",
    "SECRETS_NAME",
    "MODE",
    "app",
    "image",
    "secrets",
    "panels_volume",
]

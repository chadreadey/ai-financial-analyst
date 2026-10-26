"""Admin-key authentication for lab (write / paid-compute) endpoints."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from config import settings


def require_admin(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    """Dependency: validates X-API-Key against INTERNAL_API_KEY.

    Raises 403 (not 401) to avoid leaking that the endpoint exists and
    requires auth. Raises 500 if the key is not configured so misconfigured
    deployments fail loudly. The header is optional so a missing header
    yields 403 rather than a 422 validation error.
    """
    configured = settings.internal_api_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: INTERNAL_API_KEY not set.",
        )
    if not x_api_key or not hmac.compare_digest(configured, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden.",
        )


def is_admin(request: Request) -> bool:
    """True when the request carries the valid admin key. Never raises."""
    configured = settings.internal_api_key
    provided = request.headers.get("x-api-key")
    if not configured or not provided:
        return False
    return hmac.compare_digest(configured, provided)

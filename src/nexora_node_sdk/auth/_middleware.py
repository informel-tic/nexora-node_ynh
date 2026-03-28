"""HTTP middlewares: Bearer token auth, security headers, and CSRF protection.

Part of the nexora_node_sdk.auth package.  All symbols here are re-exported
from nexora_node_sdk.auth.__init__ for backward compatibility.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from ._token import get_api_token
from ._scopes import (
    resolve_actor_role_for_token,
    _load_token_tenant_scopes,
    _enforce_token_tenant_scope,
    build_tenant_scope_claim,
)
from ._rate_limit import _check_rate_limit, _record_auth_failure

# ── Auth middleware ────────────────────────────────────────────────────

# Paths that don't require auth
_PUBLIC_PATHS = {"/api/health", "/health", "/console", "/console/"}

# Static file prefixes
_STATIC_PREFIXES = ("/console/",)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer token for API endpoints.

    WS4-T06 additions:
    - Rate-limits repeated auth failures per client IP
    - Returns generic error to avoid information leakage
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths and static assets
        if path in _PUBLIC_PATHS or path == "/":
            return await call_next(request)
        for prefix in _STATIC_PREFIXES:
            if path.startswith(prefix) and not path.startswith("/console/api"):
                return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # Rate-limit check.
        if _check_rate_limit(client_ip):
            return JSONResponse(
                status_code=429, content={"detail": "Too many authentication attempts."}
            )

        provided_token: str | None = None
        # Check Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:].strip()
            if secrets.compare_digest(provided, get_api_token()):
                provided_token = provided

        # Also accept X-Nexora-Token header
        token_header = request.headers.get("X-Nexora-Token", "").strip()
        if (
            provided_token is None
            and token_header
            and secrets.compare_digest(token_header, get_api_token())
        ):
            provided_token = token_header

        if provided_token is not None:
            trusted_actor_role = resolve_actor_role_for_token(provided_token)
            request.state.nexora_actor_role = trusted_actor_role
            requested_tenant = request.headers.get("X-Nexora-Tenant-Id")
            configured_scopes = _load_token_tenant_scopes()
            if (
                configured_scopes
                and provided_token in configured_scopes
                and not requested_tenant
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Scoped token access requires X-Nexora-Tenant-Id header."
                    },
                )
            if not _enforce_token_tenant_scope(provided_token, requested_tenant):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"Token is not authorized for tenant scope '{requested_tenant}'."
                        )
                    },
                )
            if requested_tenant and configured_scopes:
                provided_claim = request.headers.get(
                    "X-Nexora-Tenant-Claim", ""
                ).strip()
                expected_claim = build_tenant_scope_claim(
                    provided_token, requested_tenant
                )
                if not provided_claim or not hmac.compare_digest(
                    provided_claim, expected_claim
                ):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Missing or invalid X-Nexora-Tenant-Claim for scoped tenant access."
                        },
                    )
            return await call_next(request)

        _record_auth_failure(client_ip)
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Authentication required. Use 'Authorization: Bearer <token>' or 'X-Nexora-Token: <token>'."
            },
        )


# ── Security headers middleware ──────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """WS4-T06: Inject security-hardening response headers on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response


# ── CSRF protection middleware ────────────────────────────────────────

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests (POST/PUT/DELETE/PATCH) that don't
    come from the same origin.

    WS4-T06: Strengthened to always require X-Nexora-Action and validate
    both Origin and Referer when present.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        # Require X-Nexora-Action header on all mutating requests
        if not request.headers.get("X-Nexora-Action"):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Missing X-Nexora-Action header on mutating request."
                },
            )

        # Verify Origin or Referer (at least one must be present)
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        host = request.headers.get("Host", "")

        if not origin and not referer:
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing Origin/Referer on mutating request."},
            )

        if origin:
            origin_host = (
                origin.replace("https://", "").replace("http://", "").split("/")[0]
            )
            if origin_host != host:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request rejected."},
                )
        if referer:
            referer_host = (
                referer.replace("https://", "").replace("http://", "").split("/")[0]
            )
            if referer_host != host:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request rejected."},
                )

        return await call_next(request)

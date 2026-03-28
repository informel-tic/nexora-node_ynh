"""Authentication and CSRF protection for Nexora API endpoints.

Includes per-node token management, CSRF protection middleware, and
WS4-T04 SecretStore for scoped secret isolation by node/service/operator.

Refactored in v2.1 from a 1038-line monolithic module into dedicated submodules:
  · _token        — Token I/O, rotation, session helpers
  · _scopes       — Tenant & actor scope resolution, role validators
  · _rate_limit   — Auth failure rate limiting (file-backed persistence)
  · _middleware   — HTTP middlewares (TokenAuth, SecurityHeaders, CSRF)
  · _secret_store — SecretStore class + VALID_SCOPES/SCOPE_PERMISSIONS

All symbols below are re-exported at this package level for full backward
compatibility with the 20+ import sites that use ``from nexora_node_sdk.auth import X``
or ``import nexora_node_sdk.auth as auth``.

Mutable globals used by tests live in the submodules:
  · auth._token._api_token          — cached API token (None when uncached)
  · auth._rate_limit._AUTH_FAILURES  — per-IP auth failure timestamps
"""

from __future__ import annotations

# ── Make submodules accessible as attributes (auth._token, etc.) ──────
from . import _token, _scopes, _rate_limit, _middleware, _secret_store  # noqa: F401

# ── Token management ──────────────────────────────────────────────────
from ._token import (
    _DEFAULT_TOKEN_PATH_CANDIDATES,
    _token_path_candidates,
    _token_scope_path_candidates,
    _token_role_path_candidates,
    _load_or_generate_token,
    _resolve_primary_token_path,
    _token_meta_path,
    _read_token_meta,
    _write_token_meta,
    rotate_api_token,
    _maybe_auto_rotate_token,
    get_api_token,
    generate_session_token,
    validate_session_age,
)

# ── Tenant scopes & actor roles ───────────────────────────────────────
from ._scopes import (
    NODE_TOKEN_SCOPES,
    _load_token_tenant_scopes,
    _enforce_token_tenant_scope,
    _load_token_actor_roles,
    resolve_actor_role_for_token,
    build_tenant_scope_claim,
    validate_actor_role,
    validate_operator_surface_role,
    validate_scope,
    issue_node_secret,
)

# ── Rate limiting ─────────────────────────────────────────────────────
from ._rate_limit import (
    _AUTH_FAILURES,
    _MAX_AUTH_FAILURES,
    _AUTH_WINDOW_SECONDS,
    _auth_runtime_file,
    _check_rate_limit,
    _record_auth_failure,
)

# ── HTTP middlewares ───────────────────────────────────────────────────
from ._middleware import (
    _PUBLIC_PATHS,
    _STATIC_PREFIXES,
    _SAFE_METHODS,
    TokenAuthMiddleware,
    SecurityHeadersMiddleware,
    CSRFProtectionMiddleware,
)

# ── SecretStore ───────────────────────────────────────────────────────
from ._secret_store import (
    VALID_SCOPES,
    SCOPE_PERMISSIONS,
    SecretStore,
)

__all__ = [
    # token
    "_DEFAULT_TOKEN_PATH_CANDIDATES",
    "_token_path_candidates",
    "_token_scope_path_candidates",
    "_token_role_path_candidates",
    "_load_or_generate_token",
    "_resolve_primary_token_path",
    "_token_meta_path",
    "_read_token_meta",
    "_write_token_meta",
    "rotate_api_token",
    "_maybe_auto_rotate_token",
    "get_api_token",
    "generate_session_token",
    "validate_session_age",
    # scopes
    "NODE_TOKEN_SCOPES",
    "_load_token_tenant_scopes",
    "_enforce_token_tenant_scope",
    "_load_token_actor_roles",
    "resolve_actor_role_for_token",
    "build_tenant_scope_claim",
    "validate_actor_role",
    "validate_operator_surface_role",
    "validate_scope",
    "issue_node_secret",
    # rate_limit
    "_AUTH_FAILURES",
    "_MAX_AUTH_FAILURES",
    "_AUTH_WINDOW_SECONDS",
    "_auth_runtime_file",
    "_check_rate_limit",
    "_record_auth_failure",
    # middleware
    "_PUBLIC_PATHS",
    "_STATIC_PREFIXES",
    "_SAFE_METHODS",
    "TokenAuthMiddleware",
    "SecurityHeadersMiddleware",
    "CSRFProtectionMiddleware",
    # secret_store
    "VALID_SCOPES",
    "SCOPE_PERMISSIONS",
    "SecretStore",
]

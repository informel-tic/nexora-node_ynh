"""Shared authentication primitives usable by both SaaS and node runtimes."""

from __future__ import annotations

from .auth._middleware import TokenAuthMiddleware
from .auth._rate_limit import (
    _AUTH_FAILURES,
    _AUTH_WINDOW_SECONDS,
    _MAX_AUTH_FAILURES,
    _check_rate_limit,
    _record_auth_failure,
)
from .auth._token import (
    generate_session_token,
    get_api_token,
    validate_session_age,
)

__all__ = [
    "_AUTH_FAILURES",
    "_AUTH_WINDOW_SECONDS",
    "_MAX_AUTH_FAILURES",
    "_check_rate_limit",
    "_record_auth_failure",
    "generate_session_token",
    "get_api_token",
    "TokenAuthMiddleware",
    "validate_session_age",
]
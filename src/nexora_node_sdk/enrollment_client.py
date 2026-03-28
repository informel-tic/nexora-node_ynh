"""Node-side enrollment client helpers.

This module provides the attestation response builder used by the node
agent during the enrollment challenge-response flow. It does NOT include
token issuance or consumption — those are SaaS control-plane concerns.
"""

from __future__ import annotations

import hashlib


def build_attestation_response(*, challenge: str, node_id: str, token_id: str) -> str:
    """Build the deterministic challenge-response proof sent by the node."""

    material = f"{challenge}:{node_id}:{token_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()

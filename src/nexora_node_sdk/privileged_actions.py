"""Privileged execution plans for actions that must run outside the sandboxed node-agent."""

from __future__ import annotations

from typing import Any


_PRIVILEGED_ACTIONS = {
    "hooks/install": {
        "executor": "control-plane",
        "summary": "Install or refresh privileged Nexora hooks on the target host.",
        "command": ["/opt/nexora/bin/nexora-privileged", "hooks", "install"],
        "rollback_hint": "restore the previous hook bundle or remove the generated hooks manually",
    },
    "automation/install": {
        "executor": "control-plane",
        "summary": "Install the automation profile from a privileged operator context.",
        "command": [
            "/opt/nexora/bin/nexora-privileged",
            "automation",
            "install",
            "--profile",
            "standard",
        ],
        "rollback_hint": "remove the generated cron file or restore the previous automation profile",
    },
}


def build_privileged_execution_plan(
    action: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the canonical privileged execution plan for a blocked node action."""

    payload = dict(_PRIVILEGED_ACTIONS.get(action, {}))
    payload["action"] = action
    payload["params"] = params or {}
    payload["requires_privileged_runtime"] = True
    return payload

"""Node-agent FastAPI application wiring for Nexora."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import uvicorn
from fastapi import Body, FastAPI

from nexora_core.auth_common import TokenAuthMiddleware
from nexora_core.enrollment import build_attestation_response
from nexora_core.logging_config import setup_logging
from nexora_core.node_actions import execute_node_action
from nexora_core.operator_actions import summarize_agent_capabilities
from nexora_core.runtime_context import build_service
from nexora_core.version import NEXORA_VERSION

service = build_service(__file__, os.environ.get("NEXORA_STATE_PATH"))
ACTION_METRICS = {"requests_total": 0, "mutations_total": 0}
MAX_PAYLOAD_BYTES = 131072


def build_application() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Nexora Node Agent", version=NEXORA_VERSION)
    app.add_middleware(TokenAuthMiddleware)

    register_read_routes(app)
    register_enrollment_routes(app)
    register_action_routes(app)
    return app


def register_read_routes(app: FastAPI) -> None:
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "nexora-node-agent",
            "version": NEXORA_VERSION,
            "compatibility": service.compatibility_report()["assessment"],
        }

    def inventory() -> dict[str, object]:
        return service.local_inventory()

    def inventory_section(section: str) -> dict[str, object]:
        return service.inventory_slice(section)

    def summary() -> dict[str, object]:
        payload = service.local_node_summary().model_dump()
        payload["capabilities"] = summarize_agent_capabilities()
        payload["exposure_model"] = {
            "reverse_proxy_required": True,
            "bind": "127.0.0.1",
        }
        return payload

    def identity() -> dict[str, object]:
        return service.identity()

    def compatibility() -> dict[str, object]:
        return service.compatibility_report()

    def metrics() -> dict[str, int]:
        return {
            "requests_total": ACTION_METRICS["requests_total"],
            "mutations_total": ACTION_METRICS["mutations_total"],
            "payload_limit_bytes": MAX_PAYLOAD_BYTES,
        }

    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/inventory", inventory, methods=["GET"])
    app.add_api_route("/inventory/{section}", inventory_section, methods=["GET"])
    app.add_api_route("/summary", summary, methods=["GET"])
    app.add_api_route("/identity", identity, methods=["GET"])
    app.add_api_route("/compatibility", compatibility, methods=["GET"])
    app.add_api_route("/metrics", metrics, methods=["GET"])


def register_enrollment_routes(app: FastAPI) -> None:
    def enroll(token: str, challenge: str) -> dict[str, object]:
        identity = service.identity()
        _mark_mutation()
        return {
            "success": True,
            "token": token,
            "challenge": challenge,
            "node_id": identity["node_id"],
            "hostname": os.uname().nodename,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def attest(token: str, challenge: str) -> dict[str, object]:
        identity = service.identity()
        _mark_mutation()
        return {
            "success": True,
            "node_id": identity["node_id"],
            "token_id": identity.get("token_id"),
            "challenge_response": build_attestation_response(
                challenge=challenge,
                node_id=identity["node_id"],
                token_id=identity.get("token_id") or "",
            ),
            "agent_version": NEXORA_VERSION,
            "yunohost_version": service.compatibility_report()["assessment"].get(
                "yunohost_version"
            ),
            "debian_version": "12",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def rotate_credentials() -> dict[str, object]:
        identity = service.identity()
        _mark_mutation()
        return {
            "success": True,
            "changed": True,
            "node_id": identity["node_id"],
            "rollback_hint": "re-issue previous credential bundle if peers are not updated",
        }

    def revoke() -> dict[str, object]:
        identity = service.identity()
        _mark_mutation()
        return {
            "success": True,
            "changed": True,
            "node_id": identity["node_id"],
            "rollback_hint": "request a fresh enrollment token before re-enabling remote management",
        }

    app.add_api_route("/enroll", enroll, methods=["POST"])
    app.add_api_route("/attest", attest, methods=["POST"])
    app.add_api_route("/rotate-credentials", rotate_credentials, methods=["POST"])
    app.add_api_route("/revoke", revoke, methods=["POST"])


def register_action_routes(app: FastAPI) -> None:
    action_routes = {
        "/branding/apply": "branding/apply",
        "/permissions/sync": "permissions/sync",
        "/inventory/refresh": "inventory/refresh",
        "/pra/snapshot": "pra/snapshot",
        "/maintenance/enable": "maintenance/enable",
        "/maintenance/disable": "maintenance/disable",
        "/docker/compose/apply": "docker/compose/apply",
        "/healthcheck/run": "healthcheck/run",
    }
    for path, action_name in action_routes.items():
        app.add_api_route(
            path,
            _build_action_route(action_name),
            methods=["POST"],
            name=action_name.replace("/", "-"),
        )


def _mark_mutation() -> None:
    ACTION_METRICS["requests_total"] += 1
    ACTION_METRICS["mutations_total"] += 1


def _build_action_route(action_name: str):
    def route(
        dry_run: bool = False,
        payload: dict[str, object] | None = Body(default=None),
    ) -> dict[str, object]:
        _mark_mutation()
        result = execute_node_action(
            service, action_name, dry_run=dry_run, params=dict(payload or {})
        )
        if "trace_id" not in result:
            result["trace_id"] = f"trace-{int(datetime.now(timezone.utc).timestamp())}"
        return result

    return route


app = build_application()


def main() -> None:
    host = os.environ.get("NEXORA_NODE_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("NEXORA_NODE_AGENT_PORT", "38121"))
    uvicorn.run(app, host=host, port=port, reload=False)

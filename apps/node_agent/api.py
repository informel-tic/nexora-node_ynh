"""Node-agent FastAPI application wiring for Nexora.

The node agent is a PASSIVE RECEIVER: the SaaS control plane deploys features.
The node agent alone CANNOT install overlay features — every overlay mutation
requires a valid HMAC signature from the SaaS (X-Nexora-SaaS-Signature header).

On uninstall (YunoHost remove), a full rollback restores pure YunoHost state.
If a subscriber manually deletes overlay files, the tamper detection system
logs the event and features become unavailable.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Query

from nexora_node_sdk.auth import TokenAuthMiddleware
from nexora_node_sdk.enrollment_client import build_attestation_response
from nexora_node_sdk.logging_config import setup_logging
from nexora_node_sdk.node_actions import execute_node_action
from nexora_node_sdk.operator_actions import summarize_agent_capabilities
from nexora_node_sdk.overlay import (
    deploy_overlay_service,
    docker_is_installed,
    full_overlay_rollback,
    install_docker_engine,
    install_overlay_cron,
    install_overlay_nginx_snippet,
    install_overlay_systemd,
    list_overlay_services,
    load_manifest,
    overlay_status,
    OVERLAY_MANIFEST_PATH,
    remove_overlay_cron,
    remove_overlay_nginx_snippet,
    remove_overlay_service,
    remove_overlay_systemd,
    save_manifest,
    stop_all_overlay_containers,
    uninstall_docker_engine,
)
from nexora_node_sdk.overlay_guard import (
    check_overlay_file_integrity,
    find_expired_components,
    get_tamper_events,
    guard_status,
    is_enrolled,
    renew_all_leases,
    save_manifest_signature,
    store_saas_secret,
    verify_manifest_integrity,
    verify_saas_command,
)
from nexora_node_sdk.runtime_context import build_service
from nexora_node_sdk.version import NEXORA_VERSION

service = build_service(__file__, os.environ.get("NEXORA_STATE_PATH"))
ACTION_METRICS = {"requests_total": 0, "mutations_total": 0}
MAX_PAYLOAD_BYTES = 131072


def _resign_manifest() -> None:
    """Re-sign the overlay manifest after any mutation."""
    try:
        if OVERLAY_MANIFEST_PATH.exists():
            content = OVERLAY_MANIFEST_PATH.read_text(encoding="utf-8")
            save_manifest_signature(content)
    except Exception:
        pass


def build_application() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Nexora Node Agent", version=NEXORA_VERSION)
    app.add_middleware(TokenAuthMiddleware)

    register_read_routes(app)
    register_enrollment_routes(app)
    register_action_routes(app)
    register_overlay_routes(app)
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
        rollback = full_overlay_rollback()
        return {
            "success": True,
            "changed": True,
            "node_id": identity["node_id"],
            "overlay_rollback": rollback,
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


def _require_saas_origin(
    action: str,
    payload: dict[str, Any] | None,
    x_nexora_saas_signature: str | None,
    x_nexora_saas_timestamp: str | None,
) -> None:
    """Verify the request is signed by the SaaS control plane.

    The node agent alone CANNOT install overlay features.
    """
    if not x_nexora_saas_signature or not x_nexora_saas_timestamp:
        raise HTTPException(
            status_code=403,
            detail="Overlay mutations require SaaS control-plane authorization. "
                   "Missing X-Nexora-SaaS-Signature or X-Nexora-SaaS-Timestamp header.",
        )
    valid, reason = verify_saas_command(
        action=action,
        timestamp=x_nexora_saas_timestamp,
        signature=x_nexora_saas_signature,
        payload=payload,
    )
    if not valid:
        raise HTTPException(
            status_code=403,
            detail=f"SaaS command verification failed: {reason}",
        )


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


# ---------------------------------------------------------------------------
# Overlay routes — SaaS-authorized overlay management
# ---------------------------------------------------------------------------

def register_overlay_routes(app: FastAPI) -> None:
    """Routes for managing the Nexora overlay on subscriber nodes.

    SECURITY MODEL:
    - READ endpoints: accessible to any authenticated caller (local admin or SaaS)
    - MUTATION endpoints: require HMAC signature from SaaS control plane
    - Rollback: does NOT require SaaS signature (must work during uninstall)
    - Heartbeat: SaaS renews feature leases to keep components active
    """

    # ── READ / STATUS ─────────────────────────────────────────────

    def get_overlay_status() -> dict[str, object]:
        return overlay_status()

    def get_overlay_services() -> list[dict[str, object]]:
        return list_overlay_services()

    def get_docker_status() -> dict[str, object]:
        return {"docker_available": docker_is_installed(), "overlay": overlay_status()}

    def get_guard_status() -> dict[str, object]:
        return guard_status()

    def get_integrity_check() -> dict[str, object]:
        manifest = load_manifest()
        manifest_valid, manifest_reason = verify_manifest_integrity()
        file_check = check_overlay_file_integrity(manifest)
        expired = find_expired_components(manifest)
        return {
            "manifest_integrity": {"valid": manifest_valid, "reason": manifest_reason},
            "file_integrity": file_check,
            "expired_leases": [{"kind": c["kind"], "name": c["name"]} for c in expired],
        }

    def get_tamper_log(limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, object]]:
        return get_tamper_events(limit=limit)

    # ── SaaS-ONLY MUTATIONS ───────────────────────────────────────

    def post_docker_install(
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("docker/install", None, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = install_docker_engine()
        _resign_manifest()
        return result

    def post_docker_uninstall(
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("docker/uninstall", None, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = uninstall_docker_engine()
        _resign_manifest()
        return result

    def post_deploy_service(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("service/deploy", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = deploy_overlay_service(
            name=payload["name"],
            compose_content=payload["compose"],
            nginx_snippet=payload.get("nginx_snippet"),
        )
        _resign_manifest()
        return result

    def post_remove_service(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("service/remove", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = remove_overlay_service(payload["name"])
        _resign_manifest()
        return result

    def post_stop_all_services(
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("service/stop-all", None, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        return stop_all_overlay_containers()

    def post_install_nginx(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("nginx/install", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = install_overlay_nginx_snippet(payload["name"], payload["content"], payload["domain"])
        _resign_manifest()
        return result

    def post_remove_nginx(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("nginx/remove", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = remove_overlay_nginx_snippet(payload["name"])
        _resign_manifest()
        return result

    def post_install_cron(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("cron/install", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = install_overlay_cron(payload["name"], payload["schedule"], payload["command"])
        _resign_manifest()
        return result

    def post_remove_cron(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("cron/remove", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = remove_overlay_cron(payload["name"])
        _resign_manifest()
        return result

    def post_install_systemd(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("systemd/install", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = install_overlay_systemd(payload["name"], payload["unit_content"])
        _resign_manifest()
        return result

    def post_remove_systemd(
        payload: dict[str, Any] = Body(...),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("systemd/remove", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        _mark_mutation()
        result = remove_overlay_systemd(payload["name"])
        _resign_manifest()
        return result

    # ── HEARTBEAT ─────────────────────────────────────────────────

    def post_heartbeat(
        payload: dict[str, Any] = Body(default={}),
        x_nexora_saas_signature: str | None = Header(default=None),
        x_nexora_saas_timestamp: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_saas_origin("overlay/heartbeat", payload, x_nexora_saas_signature, x_nexora_saas_timestamp)
        lease_seconds = payload.get("lease_seconds", 86400)
        manifest = load_manifest()
        manifest = renew_all_leases(manifest, lease_seconds=lease_seconds)
        save_manifest(manifest)
        _resign_manifest()
        return {
            "leases_renewed": len(manifest.get("components", [])),
            "lease_seconds": lease_seconds,
        }

    # ── SECRET EXCHANGE ───────────────────────────────────────────

    def post_establish_secret(payload: dict[str, Any] = Body(...)) -> dict[str, object]:
        secret = payload.get("saas_secret")
        if not secret or len(secret) < 32:
            raise HTTPException(status_code=400, detail="Secret must be >= 32 characters")
        store_saas_secret(secret)
        _mark_mutation()
        return {"secret_established": True, "enrolled": is_enrolled()}

    # ── ROLLBACK (no SaaS signature — must work during uninstall)

    def post_rollback() -> dict[str, object]:
        _mark_mutation()
        return full_overlay_rollback()

    # ── Register routes ───────────────────────────────────────────

    app.add_api_route("/overlay/status", get_overlay_status, methods=["GET"], name="overlay-status")
    app.add_api_route("/overlay/services", get_overlay_services, methods=["GET"], name="overlay-services")
    app.add_api_route("/overlay/docker/status", get_docker_status, methods=["GET"], name="overlay-docker-status")
    app.add_api_route("/overlay/guard", get_guard_status, methods=["GET"], name="overlay-guard")
    app.add_api_route("/overlay/integrity", get_integrity_check, methods=["GET"], name="overlay-integrity")
    app.add_api_route("/overlay/tamper-log", get_tamper_log, methods=["GET"], name="overlay-tamper-log")

    app.add_api_route("/overlay/docker/install", post_docker_install, methods=["POST"], name="overlay-docker-install")
    app.add_api_route("/overlay/docker/uninstall", post_docker_uninstall, methods=["POST"], name="overlay-docker-uninstall")
    app.add_api_route("/overlay/service/deploy", post_deploy_service, methods=["POST"], name="overlay-service-deploy")
    app.add_api_route("/overlay/service/remove", post_remove_service, methods=["POST"], name="overlay-service-remove")
    app.add_api_route("/overlay/service/stop-all", post_stop_all_services, methods=["POST"], name="overlay-service-stop-all")
    app.add_api_route("/overlay/nginx/install", post_install_nginx, methods=["POST"], name="overlay-nginx-install")
    app.add_api_route("/overlay/nginx/remove", post_remove_nginx, methods=["POST"], name="overlay-nginx-remove")
    app.add_api_route("/overlay/cron/install", post_install_cron, methods=["POST"], name="overlay-cron-install")
    app.add_api_route("/overlay/cron/remove", post_remove_cron, methods=["POST"], name="overlay-cron-remove")
    app.add_api_route("/overlay/systemd/install", post_install_systemd, methods=["POST"], name="overlay-systemd-install")
    app.add_api_route("/overlay/systemd/remove", post_remove_systemd, methods=["POST"], name="overlay-systemd-remove")
    app.add_api_route("/overlay/heartbeat", post_heartbeat, methods=["POST"], name="overlay-heartbeat")
    app.add_api_route("/overlay/establish-secret", post_establish_secret, methods=["POST"], name="overlay-establish-secret")
    app.add_api_route("/overlay/rollback", post_rollback, methods=["POST"], name="overlay-rollback")


app = build_application()


def main() -> None:
    host = os.environ.get("NEXORA_NODE_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("NEXORA_NODE_AGENT_PORT", "38121"))
    uvicorn.run(app, host=host, port=port, reload=False)

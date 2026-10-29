"""Isolated, scoped mobile admission; does not accept fleet-owner bearer secrets.

The mobile heartbeat can register telemetry only after a mobile QR exchange.
This code deliberately does not share the legacy node bearer authorization path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from services.portal.fleet_accounts import FleetAccountStore


def enroll_mobile_device(store: FleetAccountStore, body: dict[str, Any]) -> tuple[dict, HTTPStatus]:
    node_id = body.get("node_id")
    enrollment = body.get("enrollment_token")
    if not isinstance(node_id, str) or not isinstance(enrollment, str):
        return {"error": "node_id and enrollment_token are required"}, HTTPStatus.BAD_REQUEST
    # Do not let a QR enrollment take over a node already registered by
    # another service / owner, even if it does not have a mobile DB record.
    from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
    from services.gateway.server import OWNER_ACCOUNT_STORE
    if node_id in NODE_TELEMETRY_REGISTRY or OWNER_ACCOUNT_STORE.owner_for_provider_node(node_id):
        return {"error": "node identity is already enrolled"}, HTTPStatus.CONFLICT
    secret = store.consume_mobile_enrollment(enrollment, node_id)
    if not secret:
        return {"error": "mobile QR is invalid, used or expired"}, HTTPStatus.UNAUTHORIZED
    return {
        "status": "paired",
        "node_id": node_id,
        "device_token": secret,
        "gateway": "https://mesh.inetconnector.com",
        # Never expose or copy master owner_key in a mobile enrollment response.
    }, HTTPStatus.CREATED


def mobile_heartbeat(
    store: FleetAccountStore, body: dict[str, Any], auth_header: str,
) -> tuple[dict, HTTPStatus]:
    """Confirm one independently authenticated mobile node heartbeat."""
    node_id = body.get("node_id")
    nonce = body.get("nonce")
    timestamp = body.get("timestamp")
    if not isinstance(node_id, str) or not isinstance(nonce, str) or type(timestamp) is not int:
        return {"error": "invalid mobile heartbeat"}, HTTPStatus.BAD_REQUEST
    if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
        return {"error": "device credential required"}, HTTPStatus.UNAUTHORIZED
    if any(key in body for key in ("owner_key", "auth_token", "enrollment_token", "previous_node_id")):
        return {"error": "legacy fleet secrets and aliases are forbidden"}, HTTPStatus.BAD_REQUEST

    from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY, save_node_telemetry_registry
    from services.gateway.server import OWNER_ACCOUNT_STORE, _NODE_HEARTBEAT_LOCK, owner_id_for_key
    from services.billing.owner_accounts import OwnerAccountStoreError

    with _NODE_HEARTBEAT_LOCK:
        existing = NODE_TELEMETRY_REGISTRY.get(node_id)
        if existing and not existing.get("mobile_device"):
            return {"error": "node identity already used by a legacy worker"}, HTTPStatus.CONFLICT

        account = store.authenticate_mobile_heartbeat(
            node_id, auth_header[len("Bearer "):].strip(), nonce, timestamp,
        )
        if account is None:
            return {"error": "invalid, revoked or replayed mobile device credential"}, HTTPStatus.UNAUTHORIZED

        owner_id = owner_id_for_key(account.owner_key)
        if not owner_id:
            return {"error": "fleet owner unavailable"}, HTTPStatus.FORBIDDEN
        bound_id = OWNER_ACCOUNT_STORE.owner_for_provider_node(node_id)
        if bound_id and bound_id != owner_id:
            return {"error": "node belongs to another fleet"}, HTTPStatus.FORBIDDEN
        if existing and existing.get("owner_id") != owner_id:
            return {"error": "mobile node fleet mismatch"}, HTTPStatus.FORBIDDEN
        try:
            OWNER_ACCOUNT_STORE.ensure_owner(owner_id)
            OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, node_id)
        except OwnerAccountStoreError:
            return {"error": "mobile node owner binding denied"}, HTTPStatus.FORBIDDEN

        raw_inv = body.get("inventory")
        inventory = raw_inv if isinstance(raw_inv, dict) else {}
        raw_tel = body.get("telemetry")
        telemetry = raw_tel if isinstance(raw_tel, dict) else {}
        # Never trust a client's claim of financial earnings or inferred
        # inference capability for accounting. Actual metering lives elsewhere.
        NODE_TELEMETRY_REGISTRY[node_id] = {
            "node_id": node_id,
            "owner_id": owner_id,
            "auth_token": "",
            "mobile_device": True,
            "inventory": {
                "host_architecture": "android_arm64",
                "battery_level": inventory.get("battery_level"),
                "is_charging": inventory.get("is_charging"),
                "total_gpus": 0,
                "total_vram_bytes": 0,
                "gpus": [],
            },
            "telemetry": {
                "is_compute_permitted": telemetry.get("is_compute_permitted") is True,
                "local_compute_tflops": 0,
                "tokens_processed": 0,
                "earnings_cm": 0,
            },
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
    return {"status": "ok", "node_id": node_id, "mobile_device": True}, HTTPStatus.OK

def revoke_mobile_device(
    store: FleetAccountStore, account_id: str, node_id: str,
) -> tuple[dict, HTTPStatus]:
    """Explicit authenticated per-owner mobile revocation, never a fleet-wide delete."""
    if not isinstance(node_id, str) or not node_id.startswith("android-"):
        return {"error": "invalid mobile device"}, HTTPStatus.BAD_REQUEST
    if not store.revoke_mobile_device(account_id, node_id):
        return {"error": "mobile device is absent or already revoked"}, HTTPStatus.NOT_FOUND

    from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY, save_node_telemetry_registry
    from services.gateway.server import OWNER_ACCOUNT_STORE, _NODE_HEARTBEAT_LOCK
    with _NODE_HEARTBEAT_LOCK:
        existing = NODE_TELEMETRY_REGISTRY.get(node_id)
        if existing and existing.get("mobile_device"):
            owner_id = str(existing.get("owner_id", ""))
            NODE_TELEMETRY_REGISTRY.pop(node_id, None)
            if owner_id:
                OWNER_ACCOUNT_STORE.unbind_provider_node(owner_id, node_id)
            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
    return {"status": "revoked", "node_id": node_id}, HTTPStatus.OK

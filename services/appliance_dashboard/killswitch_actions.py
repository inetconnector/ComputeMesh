"""Emergency Kill Switch and Lease Guard Request Handlers."""
from __future__ import annotations

import hmac
from http import HTTPStatus
import json
import logging
import os
from typing import Any

log = logging.getLogger("computemesh.appliance.killswitch")


class KillswitchHandler:
    """Handles /api/killswitch/status, trigger, and renew endpoints."""

    @staticmethod
    def handle_get(handler: Any, req_path: str) -> bool:
        if req_path == "/api/killswitch/status":
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(handler._current_node_id())
            handler._send_json(guard.get_status())
            return True
        return False

    @staticmethod
    def handle_post(handler: Any, req_path: str, post_body: bytes) -> bool:
        if req_path == "/api/killswitch/trigger":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                data = {}
            reason = str(data.get("reason") or "Appliance Operator Emergency Stop")
            req_scope = str(data.get("scope") or "node").lower().strip()
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(handler._current_node_id())

            # Check if global cluster kill is requested
            if req_scope in ("global", "cluster", "platform"):
                master_key_header = handler.headers.get("X-Master-Killswitch-Key", "").strip()
                master_env_key = os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "").strip()
                is_master = bool(master_env_key and master_key_header and hmac.compare_digest(master_key_header, master_env_key))
                if not is_master:
                    # Isolate local node and block global kill without master secret
                    guard.trip_node(handler._current_node_id(), reason=reason)
                    try:
                        from services.appliance_dashboard.tunnel_relay import CLOUD_TUNNEL_RELAY
                        CLOUD_TUNNEL_RELAY.stop()
                    except Exception:
                        pass
                    handler._send_json({
                        "status": "node_tripped_only",
                        "scope": "node",
                        "node_id": handler._current_node_id(),
                        "message": "Berechtigungs-Schutz aktiv: Nur der Inhaber des Stripe-Accounts / inetconnector Plattformbetreiber darf den globalen Cluster-Not-Aus auslösen. Dein lokaler Knoten wurde erfolgreich isoliert und gestoppt.",
                        "guard": guard.get_status(node_id=handler._current_node_id()),
                    }, HTTPStatus.FORBIDDEN)
                    return True

                guard.trip(reason=reason, is_master=True)
            else:
                guard.trip_node(handler._current_node_id(), reason=reason)

            # Instantly sever mTLS cloud tunnel relay for this node
            try:
                from services.appliance_dashboard.tunnel_relay import CLOUD_TUNNEL_RELAY
                CLOUD_TUNNEL_RELAY.stop()
            except Exception:
                pass

            handler._send_json({
                "status": "tripped",
                "scope": req_scope if req_scope in ("global", "cluster") else "node",
                "node_id": handler._current_node_id(),
                "message": f"Not-Aus erfolgreich ausgeführt ({reason})",
                "guard": guard.get_status(node_id=handler._current_node_id()),
            })
            return True

        if req_path == "/api/killswitch/renew":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                data = {}
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(handler._current_node_id())
            if "lease_id" in data:
                try:
                    guard.update_lease(data)
                    handler._send_json({"status": "renewed", "guard": guard.get_status()})
                    return True
                except Exception as exc:
                    handler._send_json({"status": "error", "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return True
            handler._send_json({"status": "active", "guard": guard.get_status()})
            return True

        return False

"""HTTP endpoints for safe GPU fan policy inspection and application."""
from __future__ import annotations

from http import HTTPStatus
import json
import os
from typing import Any

from tools.appliance.appliance_config import ApplianceConfig, save_system_config
from tools.appliance.fan_control import apply_fan_policy, fan_status


class FanControlHandler:
    @staticmethod
    def handle_get(handler: Any, req_path: str) -> bool:
        if req_path != "/api/fan/status":
            return False
        if not handler._verify_action_auth():
            handler._send_unauthorized()
            return True
        handler._send_json(fan_status(handler.inventory, handler.config))
        return True

    @staticmethod
    def handle_post(handler: Any, req_path: str, post_body: bytes) -> bool:
        if req_path != "/api/fan/apply":
            return False
        try:
            data = json.loads(post_body.decode("utf-8"))
            mode = str(data.get("mode", "safe_auto")).strip().lower()
            if mode == "auto" and os.environ.get("COMPUTEMESH_ALLOW_ZERO_RPM", "") != "1":
                mode = "safe_auto"
            target = int(data.get("target_percent", 60))
            result = apply_fan_policy(handler.inventory, mode, target)

            # Keep the safe driver mode when this particular Windows driver
            # exposes only automatic control; never persist an unapplied manual
            # request as if it were active.
            current = handler.config.to_dict()
            current["fan_control_mode"] = mode if result["applied"] else "safe_auto"
            current["fan_target_percent"] = target
            updated = ApplianceConfig(**current)
            save_system_config(updated)
            handler.__class__.config = updated
            status = HTTPStatus.OK if result["applied"] else HTTPStatus.CONFLICT
            handler._send_json({"status": "ok" if result["applied"] else "unsupported", **result}, status)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            handler._send_json({"status": "error", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            handler._send_json({"status": "error", "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return True

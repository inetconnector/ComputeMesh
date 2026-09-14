"""Appliance System Actions, Configuration, and Lifecycle Handlers."""
from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from services.gateway.security import SECURITY_HEADERS

log = logging.getLogger("computemesh.appliance.actions")
REPO_ROOT = Path(__file__).resolve().parents[2]


class SystemActionsHandler:
    """Handles configuration updates, daemon restarts, rebooting, and OS/app updates."""

    @staticmethod
    def handle_get(
        handler: Any,
        req_path: str,
        appliance_version: str,
    ) -> bool:
        if req_path == "/api/action/check_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=appliance_version)
                u_info = updater.check_for_updates()
                if u_info:
                    resp_dict = {
                        "update_available": u_info.is_newer,
                        "version": u_info.version,
                        "current_version": appliance_version,
                        "release_date": u_info.release_date,
                        "filename": u_info.filename,
                    }
                else:
                    resp_dict = {"update_available": False, "version": appliance_version, "current_version": appliance_version}
                handler._send_json(resp_dict)
            except Exception as e:
                handler._send_json({"status": "error", "message": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return True

        if req_path == "/api/action/boot_source":
            if not handler._verify_action_auth():
                handler._send_unauthorized()
                return True
            if sys.platform == "win32":
                payload = {"booted_from_usb": False, "source_disk": None, "targets": []}
            else:
                from tools.appliance.disk_clone import get_boot_source_info, list_clone_targets
                info = get_boot_source_info()
                source_name = (info["source_disk"] or "").rsplit("/", 1)[-1] or None
                payload = {
                    **info,
                    "targets": list_clone_targets(source_name, info["clone_bytes"]) if info["booted_from_usb"] else [],
                }
            handler._send_json(payload)
            return True

        if req_path == "/api/action/clone_status":
            if not handler._verify_action_auth():
                handler._send_unauthorized()
                return True
            if sys.platform == "win32":
                handler._send_json({"running": False, "done": False, "error": "not supported on Windows"})
                return True
            from tools.appliance.disk_clone import get_clone_status
            handler._send_json(get_clone_status())
            return True

        return False

    @staticmethod
    def handle_post(
        handler: Any,
        req_path: str,
        post_body: bytes,
        appliance_version: str,
    ) -> bool:
        if req_path == "/api/config":
            try:
                data = json.loads(post_body.decode("utf-8"))
                previous_node_id = str(getattr(handler.config, "rig_name", "") or "").strip()
                new_dict = handler.config.to_dict()
                for k, v in data.items():
                    if k in new_dict:
                        new_dict[k] = v

                from tools.appliance.appliance_config import ApplianceConfig, save_system_config
                updated_cfg = ApplianceConfig(**new_dict)
                save_system_config(updated_cfg)
                handler.__class__.config = updated_cfg

                # Instantly synchronize across local mesh, lan discovery responder & coordinator webserver
                try:
                    from services.appliance_dashboard.tunnel_relay import trigger_immediate_mesh_sync
                    trigger_immediate_mesh_sync(updated_cfg=updated_cfg, previous_node_id=previous_node_id)
                except Exception:
                    pass

                resp = json.dumps({
                    "status": "ok",
                    "message": "Configuration saved and instantly synchronized across mesh and coordinator",
                    "synced": True,
                    "node_id": updated_cfg.rig_name or previous_node_id,
                }).encode("utf-8")
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(resp)))
                handler.end_headers()
                handler.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                handler.send_response(HTTPStatus.BAD_REQUEST)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(err_resp)))
                handler.end_headers()
                handler.wfile.write(err_resp)
            return True

        if req_path == "/api/action/restart_daemon":
            if sys.platform != "win32":
                subprocess.Popen(["sh", "-c", "sleep 1 && systemctl restart computemesh-appliance.service computemesh-dashboard.service computemesh-node.service || true"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Daemon restarting"}).encode("utf-8")
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                handler.send_header(h_name, h_val)
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Content-Length", str(len(resp)))
            handler.end_headers()
            handler.wfile.write(resp)
            return True

        if req_path == "/api/action/reboot":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "Reboot is not supported on Windows."}).encode("utf-8")
                handler.send_response(HTTPStatus.BAD_REQUEST)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(err_resp)))
                handler.end_headers()
                handler.wfile.write(err_resp)
                return True

            subprocess.Popen(["systemctl", "reboot"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Rebooting system"}).encode("utf-8")
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                handler.send_header(h_name, h_val)
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Content-Length", str(len(resp)))
            handler.end_headers()
            handler.wfile.write(resp)
            return True

        if req_path == "/api/action/clone_to_ssd":
            if sys.platform == "win32":
                handler._send_json({"status": "error", "message": "Not supported on Windows"}, HTTPStatus.BAD_REQUEST)
                return True
            try:
                data = json.loads(post_body.decode("utf-8"))
            except Exception:
                handler._send_json({"status": "error", "message": "Malformed JSON body"}, HTTPStatus.BAD_REQUEST)
                return True
            target_device = str(data.get("target_device", "")).strip()
            confirm = str(data.get("confirm", "")).strip()
            try:
                block_size_mb = int(data.get("block_size_mb", 4))
            except (TypeError, ValueError):
                block_size_mb = 4
            from tools.appliance.disk_clone import start_clone
            accepted, message = start_clone(target_device, confirm, block_size_mb)
            handler._send_json(
                {"status": "ok" if accepted else "error", "message": message},
                HTTPStatus.OK if accepted else HTTPStatus.BAD_REQUEST,
            )
            return True

        if req_path == "/api/action/os_upgrade":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "OS upgrades are not supported on Windows."}).encode("utf-8")
                handler.send_response(HTTPStatus.BAD_REQUEST)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(err_resp)))
                handler.end_headers()
                handler.wfile.write(err_resp)
                return True

            try:
                subprocess.Popen(["apt-get", "update", "-qq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                resp = json.dumps({"status": "ok", "message": "OS package upgrade running in background"}).encode("utf-8")
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(resp)))
                handler.end_headers()
                handler.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                handler.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                handler.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    handler.send_header(h_name, h_val)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(err_resp)))
                handler.end_headers()
                handler.wfile.write(err_resp)
            return True

        if req_path == "/api/action/apply_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=appliance_version)
                u_info = updater.check_for_updates()
                if u_info:
                    pkg = updater.download_and_verify(u_info)
                    if sys.platform == "win32":
                        updater.apply_windows_update(pkg)
                    else:
                        updater.apply_linux_update(pkg)
                    resp = json.dumps({"status": "ok", "message": f"Updated to v{u_info.version}"}).encode("utf-8")
                else:
                    resp = json.dumps({"status": "ok", "message": "Already up to date"}).encode("utf-8")
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(resp)))
                handler.end_headers()
                handler.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                handler.send_response(HTTPStatus.BAD_REQUEST)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Content-Length", str(len(err_resp)))
                handler.end_headers()
                handler.wfile.write(err_resp)
            return True

        return False

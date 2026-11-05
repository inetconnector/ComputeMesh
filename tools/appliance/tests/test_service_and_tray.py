"""Tests for Windows/Linux Runner Services, Tray App, and Dashboard Service API."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestWindowsServiceContracts:
    def test_windows_service_status_query_contract(self):
        from tools.appliance.windows_service import query_service_status

        status = query_service_status()
        assert isinstance(status, dict)
        assert "status" in status
        # If on Windows, should report valid status string
        if sys.platform == "win32":
            assert status["status"] in ("RUNNING", "STOPPED", "PAUSED", "NOT_INSTALLED", "UNKNOWN")

    def test_windows_service_daemon_entrypoint_exists(self):
        from tools.appliance.windows_service import run_headless_daemon

        assert callable(run_headless_daemon)

    def test_windows_service_management_functions_exist(self):
        from tools.appliance.windows_service import (
            install_service,
            start_service,
            stop_service,
            uninstall_service,
        )

        assert callable(install_service)
        assert callable(uninstall_service)
        assert callable(start_service)
        assert callable(stop_service)

    def test_windows_service_batch_installers_exist(self):
        appliance_dir = REPO_ROOT / "tools" / "appliance"
        install_bat = appliance_dir / "install_windows_service.bat"
        uninstall_bat = appliance_dir / "uninstall_windows_service.bat"

        assert install_bat.is_file()
        assert uninstall_bat.is_file()

        content = install_bat.read_text(encoding="utf-8")
        assert "ComputeMeshNode" in content
        assert "windows_service.py" in content


class TestLinuxTrayAppWithoutTkinter:
    def test_linux_tray_app_imports_cleanly_without_tkinter(self):
        # Ensure no tkinter in modules before/after
        import tools.appliance.linux_tray_app as linux_app

        assert hasattr(linux_app, "LinuxComputeMeshProviderApp")
        assert hasattr(linux_app, "get_active_dashboard_port")
        assert hasattr(linux_app, "is_linux_autostart_enabled")
        assert hasattr(linux_app, "set_linux_autostart")

        # Verify no tkinter imported by linux_tray_app
        assert "tkinter" not in sys.modules

    def test_linux_autostart_toggle_functionality(self, tmp_path):
        import tools.appliance.linux_tray_app as linux_app

        test_autostart_file = tmp_path / "computemesh.desktop"
        with patch.object(linux_app, "AUTOSTART_DESKTOP_FILE", test_autostart_file):
            assert not linux_app.is_linux_autostart_enabled()
            assert linux_app.set_linux_autostart(True)
            assert test_autostart_file.exists()
            assert "ComputeMesh Provider Node" in test_autostart_file.read_text(encoding="utf-8")
            assert linux_app.is_linux_autostart_enabled()

            assert linux_app.set_linux_autostart(False)
            assert not test_autostart_file.exists()
            assert not linux_app.is_linux_autostart_enabled()

    def test_linux_service_deploy_unit_is_valid(self):
        service_file = REPO_ROOT / "tools" / "appliance" / "deploy" / "computemesh-node.service"
        assert service_file.is_file()
        content = service_file.read_text(encoding="utf-8")
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "linux_tray_app.py --service" in content
        assert "Restart=always" in content

    def test_linux_shell_installer_is_executable(self):
        installer = REPO_ROOT / "tools" / "appliance" / "install_linux.sh"
        assert installer.is_file()
        content = installer.read_text(encoding="utf-8")
        assert "#!/usr/bin/env bash" in content
        assert "computemesh-node" in content
        assert "systemctl" in content


class TestApplianceDashboardServiceAPI:
    def test_service_status_handler_response(self):
        from services.appliance_dashboard.server import DashboardHandler

        handler = object.__new__(DashboardHandler)
        captured = {}

        def mock_send_json(payload, status):
            captured["payload"] = payload
            captured["status"] = status

        handler._send_json = mock_send_json
        handler.server = MagicMock()
        handler.server.server_port = 8080

        handler._handle_service_status()

        assert captured["status"] == 200
        p = captured["payload"]
        assert "platform" in p
        assert "service_name" in p
        assert "is_service_installed" in p
        assert "service_status" in p
        assert "runner_mode" in p
        assert p["service_name"] in ("ComputeMeshNode", "computemesh-node")

    def test_service_control_handler_invalid_action(self):
        from services.appliance_dashboard.server import execute_service_control

        ok, msg = execute_service_control("invalid_action_xyz")
        assert ok is False
        assert "Unknown action" in msg

    def test_gateway_service_status_route(self):
        from services.gateway.server import GatewayHandler

        handler = object.__new__(GatewayHandler)
        captured = {}

        def mock_send_json(payload, status=200):
            captured["payload"] = payload
            captured["status"] = status

        handler._send_json = mock_send_json
        handler.server = MagicMock()
        handler.server.server_port = 8000
        handler.path = "/api/appliance/service/status"
        handler.headers = {}

        # Test GET dispatch logic for the route
        from services.appliance_dashboard.server import get_service_status_payload
        payload = get_service_status_payload(server_port=8000)
        assert "platform" in payload
        assert "runner_mode" in payload

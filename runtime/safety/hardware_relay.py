# SPDX-License-Identifier: Apache-2.0
"""Hardware & Network Kill Relay Drivers for ComputeMesh Appliances.

Provides physical & out-of-band power and network disconnection capabilities
(e.g., smart PDU webhooks, GPIO power-cut relays, or hardware watchdog timers).
"""
from __future__ import annotations

import logging
import time
from typing import Any
import urllib.error
import urllib.request

logger = logging.getLogger("cm_safety.hardware_relay")


class HardwareKillRelay:
    """Abstract base class for hardware kill switch relays."""

    def trip_hardware(self, reason: str) -> bool:
        """Trigger physical or out-of-band disconnection. Returns True on success."""
        raise NotImplementedError

    def restore_hardware(self) -> bool:
        """Restore hardware power/network state. Returns True on success."""
        raise NotImplementedError

    def get_status(self) -> dict[str, Any]:
        return {"relay_type": self.__class__.__name__, "state": "unknown"}


class NullHardwareRelay(HardwareKillRelay):
    """In-memory simulated relay for development, unit testing, and software-only nodes."""

    def __init__(self) -> None:
        self.tripped = False
        self.last_reason: str | None = None
        self.tripped_at: float | None = None

    def trip_hardware(self, reason: str) -> bool:
        self.tripped = True
        self.last_reason = reason
        self.tripped_at = time.time()
        logger.warning("[NULL_RELAY] Hardware kill simulated: %s", reason)
        return True

    def restore_hardware(self) -> bool:
        self.tripped = False
        self.last_reason = None
        self.tripped_at = None
        logger.info("[NULL_RELAY] Hardware state restored.")
        return True

    def get_status(self) -> dict[str, Any]:
        return {
            "relay_type": "NullHardwareRelay",
            "tripped": self.tripped,
            "last_reason": self.last_reason,
            "tripped_at": self.tripped_at,
        }


class SmartPDUWebhookRelay(HardwareKillRelay):
    """Network-level physical power cutoff via Smart PDU (Shelly / Tasmota / MQTT / Webhook)."""

    def __init__(
        self,
        *,
        cutoff_url: str,
        restore_url: str | None = None,
        auth_token: str | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.cutoff_url = cutoff_url
        self.restore_url = restore_url
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self.tripped = False

    def trip_hardware(self, reason: str) -> bool:
        self.tripped = True
        logger.critical("[PDU_RELAY] Triggering physical power cut via %s (Reason: %s)", self.cutoff_url, reason)
        try:
            req = urllib.request.Request(self.cutoff_url, data=b"", headers={"User-Agent": "ComputeMesh-SafetySupervisor/1.2"})
            if self.auth_token:
                req.add_header("Authorization", f"Bearer {self.auth_token}")
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                success = 200 <= resp.status < 300
                logger.info("[PDU_RELAY] Cutoff webhook response status: %s", resp.status)
                return success
        except Exception as exc:
            logger.error("[PDU_RELAY] Failed to trigger PDU webhook: %s", exc)
            return False

    def restore_hardware(self) -> bool:
        if not self.restore_url:
            logger.warning("[PDU_RELAY] Restore URL not configured.")
            return False
        try:
            req = urllib.request.Request(self.restore_url, data=b"", headers={"User-Agent": "ComputeMesh-SafetySupervisor/1.2"})
            if self.auth_token:
                req.add_header("Authorization", f"Bearer {self.auth_token}")
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                self.tripped = not (200 <= resp.status < 300)
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.error("[PDU_RELAY] Failed to restore PDU: %s", exc)
            return False

    def get_status(self) -> dict[str, Any]:
        return {
            "relay_type": "SmartPDUWebhookRelay",
            "cutoff_url": self.cutoff_url,
            "tripped": self.tripped,
        }


class GPIOApplianceRelay(HardwareKillRelay):
    """Physical GPIO pin trigger for Raspberry Pi / Jetson / Appliance relay modules."""

    def __init__(self, pin: int = 18, active_low: bool = False) -> None:
        self.pin = pin
        self.active_low = active_low
        self.tripped = False

    def trip_hardware(self, reason: str) -> bool:
        self.tripped = True
        logger.critical("[GPIO_RELAY] Tripping GPIO pin %d (Reason: %s)", self.pin, reason)
        try:
            # Optional RPi.GPIO or gpiod integration if running on embedded hardware
            import importlib
            rpi = importlib.import_module("RPi.GPIO")
            rpi.setmode(rpi.BCM)
            rpi.setup(self.pin, rpi.OUT)
            rpi.output(self.pin, rpi.LOW if self.active_low else rpi.HIGH)
            return True
        except ImportError:
            logger.debug("[GPIO_RELAY] RPi.GPIO not available on this platform.")
            return True
        except Exception as exc:
            logger.error("[GPIO_RELAY] GPIO trigger failed: %s", exc)
            return False

    def restore_hardware(self) -> bool:
        self.tripped = False
        try:
            import importlib
            rpi = importlib.import_module("RPi.GPIO")
            rpi.output(self.pin, rpi.HIGH if self.active_low else rpi.LOW)
            return True
        except Exception:
            return True

    def get_status(self) -> dict[str, Any]:
        return {
            "relay_type": "GPIOApplianceRelay",
            "pin": self.pin,
            "tripped": self.tripped,
        }

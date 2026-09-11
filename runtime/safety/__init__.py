# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Runtime Safety & Kill Switch Subsystem."""
from __future__ import annotations

from .dead_mans_switch import (
    AuthorizationLeaseExpiredError,
    DeadMansLeaseGuard,
    EmergencyKillTrippedError,
    ExecutionLease,
    InvalidLeaseSignatureError,
    KillSwitchError,
    MasterAuthorizationRequiredError,
    get_lease_guard,
    set_global_lease_guard,
)
from .hardware_relay import (
    GPIOApplianceRelay,
    HardwareKillRelay,
    NullHardwareRelay,
    SmartPDUWebhookRelay,
)
from .supervisor import SafetySupervisor
from .tripline_monitor import TriplineMonitor

__all__ = [
    "AuthorizationLeaseExpiredError",
    "DeadMansLeaseGuard",
    "EmergencyKillTrippedError",
    "ExecutionLease",
    "GPIOApplianceRelay",
    "HardwareKillRelay",
    "InvalidLeaseSignatureError",
    "KillSwitchError",
    "MasterAuthorizationRequiredError",
    "NullHardwareRelay",
    "SafetySupervisor",
    "SmartPDUWebhookRelay",
    "TriplineMonitor",
    "get_lease_guard",
    "set_global_lease_guard",
]

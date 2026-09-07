# SPDX-License-Identifier: Apache-2.0
"""
Safe System Inspection Tools for Verified Fleet Owners.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from typing import Any, Dict


def execute_system_info() -> Dict[str, Any]:
    return {
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

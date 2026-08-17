"""Diagnostic system information gathering for support bundles

This module never runs automatically and its output is never persisted to
disk by itself; it is only assembled on demand when a user chooses to
include it in a downloaded log bundle (see ``icoapi.routers.log_routes``).
"""

import locale
import os
import platform
import socket
import sys
import time
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Any, Dict

import psutil

from icoapi.utils.logging_setup import LOG_PATH

# Components whose installed version is relevant when debugging this app
TRACKED_PACKAGES = [
    "icoapi",
    "icotronic",
    "icostate",
    "icolyzer",
]


def _package_versions() -> Dict[str, str]:
    """Get installed versions of the packages this app depends on"""

    versions = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = pkg_version(name)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def _disk_usage() -> Dict[str, Any]:
    """Get disk usage for the drive the logs/app data are stored on"""

    try:
        usage = psutil.disk_usage(os.path.dirname(LOG_PATH))
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "percent_used": usage.percent,
        }
    except OSError:
        return {}


def get_system_info() -> Dict[str, Any]:
    """Collect diagnostic information about the host system

    This is intentionally limited to hardware/OS/runtime facts that are
    useful for reproducing environment-specific bugs (e.g. "only happens
    on Windows 11 with 2 CPU cores" or "out of disk space"). It does not
    collect user data, file contents, network addresses, or environment
    variables.
    """

    virtual_memory = psutil.virtual_memory()
    swap_memory = psutil.swap_memory()

    return {
        "generated_at": datetime.now().isoformat(),
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "frozen_executable": getattr(sys, "frozen", False),
        },
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "usage_percent": psutil.cpu_percent(interval=0.1),
        },
        "memory": {
            "total_bytes": virtual_memory.total,
            "available_bytes": virtual_memory.available,
            "percent_used": virtual_memory.percent,
            "swap_total_bytes": swap_memory.total,
            "swap_used_bytes": swap_memory.used,
        },
        "disk": _disk_usage(),
        "network": {
            "hostname": socket.gethostname(),
            "interface_names": sorted(psutil.net_if_addrs().keys()),
        },
        "locale": {
            "default_locale": locale.getlocale()[0],
            "timezone": time.tzname,
        },
        "uptime_seconds": time.time() - psutil.boot_time(),
        "package_versions": _package_versions(),
    }

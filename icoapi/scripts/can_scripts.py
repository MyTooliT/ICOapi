"""Scripts for finding CAN networks"""

import asyncio
import logging
from os import getenv
from sys import platform
from typing import Any

import can
from icotronic.config import settings

from icoapi.models.models import CANNetwork

logger = logging.getLogger(__name__)


class NoCANNetworkError(Exception):
    """No CAN network is available"""


class UnknownCANNetworkError(Exception):
    """The requested CAN network was not found"""


def is_can_autoconnect() -> bool:
    """Check if the API should connect to a CAN network on startup"""

    return getenv("ICOAPI_CAN_AUTOCONNECT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_default_can_configuration() -> dict[str, Any]:
    """Get the CAN configuration ICOtronic uses for the current platform"""

    if platform == "linux":
        return dict(settings.can.linux)
    if platform == "darwin":
        return dict(settings.can.mac)
    return dict(settings.can.windows)


def get_default_can_network() -> CANNetwork:
    """Get the CAN network ICOtronic uses by default"""

    configuration = get_default_can_configuration()
    return CANNetwork(
        interface=configuration["interface"],
        channel=configuration["channel"],
        bitrate=configuration.get("bitrate"),
    )


def get_discovery_interfaces() -> list[str]:
    """Get the CAN interfaces that can be searched on the current platform"""

    # SocketCAN is only available on Linux
    return ["socketcan", "pcan"] if platform == "linux" else ["pcan"]


def _discover() -> list[CANNetwork]:
    """Find available CAN networks (blocking)"""

    default = get_default_can_network()
    configurations = []
    for interface in get_discovery_interfaces():
        try:
            found = can.detect_available_configs(interfaces=[interface])
        except Exception as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.warning(
                "Cannot search for CAN networks using interface <%s>: %s",
                interface,
                error,
            )
            continue
        if not found and interface == "pcan" and platform == "darwin":
            logger.warning(
                "No PCAN network found. On macOS the PCBUSB library is"
                " required to detect PCAN adapters"
            )
        configurations.extend(found)

    networks = []
    for configuration in configurations:
        network = CANNetwork(
            interface=str(configuration["interface"]),
            channel=str(configuration["channel"]),
            bitrate=default.bitrate,
        )
        if network not in networks:
            networks.append(network)
    return networks


async def discover_can_networks() -> list[CANNetwork]:
    """Find available CAN networks

    The interfaces ``socketcan`` (Linux only) and ``pcan`` are searched. Finding no network is no error and returns an empty
    list.
    """

    return await asyncio.to_thread(_discover)


def select_can_network(networks: list[CANNetwork]) -> CANNetwork:
    """Select the network to use, preferring the default channel

    Raises:

        NoCANNetworkError: If the list of networks is empty
    """

    if not networks:
        raise NoCANNetworkError("No CAN network found")

    default = get_default_can_network()
    for network in networks:
        if (network.interface, network.channel) == (
            default.interface,
            default.channel,
        ):
            return network
    return networks[0]

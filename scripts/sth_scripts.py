from time import time
from asyncio import sleep
from typing import List

from mytoolit.can import Network
from mytoolit.can.network import STHDeviceInfo

from ..models.models import STHRenameResponseModel
from ..scripts.stu_scripts import get_stu_devices
from ..scripts.errors import NoResponseError


async def get_sth_devices_from_network() -> List[STHDeviceInfo]:
    """Print a list of available sensor devices"""

    async with Network() as network:
        timeout = time() + 5
        sensor_devices: List[STHDeviceInfo] = []
        sensor_devices_before: List[STHDeviceInfo] = []

        # - First request for sensor devices will produce empty list
        # - Subsequent retries should provide all available sensor devices
        # - We wait until the number of sensor devices is larger than 1 and
        #   has not changed between one iteration or the timeout is reached
        while (
                len(sensor_devices) <= 0
                and time() < timeout
                or len(sensor_devices) != len(sensor_devices_before)
        ):
            sensor_devices_before = list(sensor_devices)
            sensor_devices = await network.get_sensor_devices()
            await sleep(0.5)

        return sensor_devices


async def connect_sth_device_by_mac(mac: str) -> None:
    """Connect a STH device by a given MAC address"""
    async with Network() as network:
        await network.connect_sensor_device(mac)
        print(await network.is_connected("STU 1"))


async def disconnect_sth_devices() -> None:
    """Disconnect a STH device by disabling STU bluetooth"""
    devices = await get_stu_devices()

    async with Network() as network:
        for device in devices:
            await network.deactivate_bluetooth(f"STU {device.device_number}")


async def rename_sth_device(mac_address: str, new_name: str) -> STHRenameResponseModel:
    """Rename a STH device based on its Node name"""
    async with Network() as network:
        node = "STH 1"
        await network.connect_sensor_device(mac_address)
        mac_address = await network.get_mac_address(node)
        old_name = await network.get_name(node)

        await network.set_name(new_name, node)
        name = await network.get_name(node)

        return STHRenameResponseModel(name=name, mac_address=mac_address.format(), old_name=old_name)


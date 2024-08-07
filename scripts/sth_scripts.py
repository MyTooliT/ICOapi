from time import time
from asyncio import sleep
from typing import List

from mytoolit.can import Network
from mytoolit.can.network import STHDeviceInfo


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

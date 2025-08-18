from time import time
from asyncio import sleep
from typing import List
import logging
from mytoolit.can.network import STHDeviceInfo
from mytoolit.can import Network
from mytoolit.can.adc import ADCConfiguration

from icoapi.models.models import STHRenameResponseModel, ADCValues
from icoapi.scripts.stu_scripts import STU_1_NAME

logger = logging.getLogger(__name__)

async def get_sth_devices_from_network(network: Network) -> List[STHDeviceInfo]:
    """Get a list of available sensor devices"""

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


async def connect_sth_device_by_mac(network: Network, mac_address: str) -> None:
    """Connect a STH device by a given MAC address"""
    await network.connect_sensor_device(mac_address)
    logger.info(f"STU 1 has connection: {await network.is_connected(STU_1_NAME)}")


async def disconnect_sth_devices(network: Network) -> None:
    """Disconnect a STH device by disabling STU bluetooth"""
    await network.deactivate_bluetooth(STU_1_NAME)
    logger.info("Disabled STU 1 bluetooth.")


async def rename_sth_device(network: Network, mac_address: str, new_name: str) -> STHRenameResponseModel:
    """Rename a STH device based on its Node name"""
    node = "STH 1"
    disconnect_after_end = False

    if not await network.is_connected(STU_1_NAME):
        disconnect_after_end = True
        await network.connect_sensor_device(mac_address)

    old_name = await network.get_name(node)

    await network.set_name(new_name, node)
    name = await network.get_name(node)

    if disconnect_after_end:
        await network.deactivate_bluetooth()

    return STHRenameResponseModel(name=name, mac_address=mac_address.format(), old_name=old_name)


async def read_sth_adc(network: Network) -> ADCConfiguration | None:
    if await network.is_connected():
        return await network.read_adc_configuration()
    return None


async def write_sth_adc(network: Network, config: ADCValues) -> None:
    if not await network.is_connected():
        raise TimeoutError
    adc = ADCConfiguration(
        reference_voltage=config.reference_voltage,
        prescaler=config.prescaler,
        acquisition_time=config.acquisition_time,
        oversampling_rate=config.oversampling_rate
    )
    await network.write_adc_configuration(**adc)

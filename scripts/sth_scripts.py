from time import time
from asyncio import sleep
from typing import List
from functools import partial

from mytoolit.can.network import STHDeviceInfo
from mytoolit.can import Network, NetworkError
from mytoolit.can.adc import ADCConfiguration
from mytoolit.measurement import convert_raw_to_g
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g

from models.models import STHRenameResponseModel, ADCValues
from scripts.stu_scripts import get_stu_devices
from scripts.errors import NoResponseError


async def get_sth_devices_from_network(network: Network) -> List[STHDeviceInfo]:
    """Print a list of available sensor devices"""

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


async def connect_sth_device_by_mac(network: Network, mac: str) -> None:
    """Connect a STH device by a given MAC address"""
    await network.connect_sensor_device(mac)
    print(await network.is_connected("STU 1"))


async def disconnect_sth_devices(network: Network) -> None:
    """Disconnect a STH device by disabling STU bluetooth"""
    devices = await get_stu_devices(network)

    for device in devices:
        await network.deactivate_bluetooth(f"STU {device.device_number}")


async def rename_sth_device(network: Network, mac_address: str, new_name: str) -> STHRenameResponseModel:
    """Rename a STH device based on its Node name"""
    node = "STH 1"

    if not await network.is_connected("STU 1"):
        await network.connect_sensor_device(mac_address)

    old_name = await network.get_name(node)

    await network.set_name(new_name, node)
    name = await network.get_name(node)

    return STHRenameResponseModel(name=name, mac_address=mac_address.format(), old_name=old_name)


async def stream_sth_measurement(mac_address: str) -> list:
    async with Network() as network:
        await network.connect_sensor_device(mac_address)
        sensor_range = await read_acceleration_sensor_range_in_g(network)
        conversion_to_g = partial(convert_raw_to_g, max_value=sensor_range)
        measurements = []
        try:
            async with network.open_data_stream(first=True, second=True, third=True) as stream:
                start_time = time()
                async for data in stream:
                    data.apply(conversion_to_g)
                    print(data.first)
                    #measurements.append(data.first)

                    if time() - start_time >= 10:
                        break
        except KeyboardInterrupt:
            pass

        return measurements


async def read_sth_adc(network: Network, mac_address: str) -> ADCConfiguration | NetworkError:
    if not await network.is_connected():
        return NetworkError()
    return await network.read_adc_configuration()


async def write_sth_adc(network: Network, mac_address: str, config: ADCValues) -> None | NetworkError:
    if not network.is_connected():
        return NetworkError()
    adc = ADCConfiguration(
        reference_voltage=config.reference_voltage,
        prescaler=config.prescaler,
        acquisition_time=config.acquisition_time,
        oversampling_rate=config.oversampling_rate
    )
    await network.write_adc_configuration(**adc)

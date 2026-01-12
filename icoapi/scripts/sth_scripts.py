"""Scripts for sensor nodes (e.g. STHs)"""

from typing import List
import logging
from icostate import ADCConfiguration, ICOsystem, SensorNodeInfo

from icoapi.models.models import STHRenameResponseModel, ADCValues

logger = logging.getLogger(__name__)


async def get_sth_devices_from_network(
    system: ICOsystem,
) -> List[SensorNodeInfo]:
    """Get a list of available sensor devices"""

    sensor_devices = await system.collect_sensor_nodes()

    return sensor_devices


async def connect_sth_device_by_mac(
    system: ICOsystem, mac_address: str
) -> None:
    """Connect a STH device by a given MAC address"""
    await system.connect_sensor_node_mac(mac_address)
    logger.info(
        "STU 1 has connection: %s", await system.is_sensor_node_connected()
    )


async def disconnect_sth_devices(system: ICOsystem) -> None:
    """Disconnect a STH device by disabling STU bluetooth"""
    await system.disconnect_sensor_node()
    logger.info("Disabled STU 1 bluetooth.")


async def rename_sth_device(
    system: ICOsystem, mac_address: str, new_name: str
) -> STHRenameResponseModel:
    """Rename a STH device based on its Node name"""

    old_name = await system.rename(mac_address=mac_address, new_name=new_name)

    return STHRenameResponseModel(
        name=new_name, mac_address=mac_address.format(), old_name=old_name
    )


async def read_sth_adc(system: ICOsystem) -> ADCConfiguration | None:
    """Read ADC configuration of sensor node"""
    if await system.is_sensor_node_connected():
        return await system.get_adc_configuration()
    return None


async def write_sth_adc(system: ICOsystem, config: ADCValues) -> None:
    """Write ADC configuration of sensor node"""

    if not await system.is_sensor_node_connected():
        raise TimeoutError
    adc = ADCConfiguration(
        reference_voltage=config.reference_voltage,
        prescaler=config.prescaler,
        acquisition_time=config.acquisition_time,
        oversampling_rate=config.oversampling_rate,
    )
    await system.set_adc_configuration(adc)

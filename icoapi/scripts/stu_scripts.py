"""Scripts for stationary transceiver unit (STU)"""

from icostate import ICOsystem
from icotronic.can.error import NoResponseError
from icoapi.models.models import STUDeviceResponseModel


async def get_stu(system: ICOsystem) -> list[STUDeviceResponseModel]:
    """Get connected STU"""

    eui = await system.get_stu_mac_address()
    dev = STUDeviceResponseModel(
        device_number=1, mac_address=eui.format(), name="STU 1"
    )

    return [dev]


async def reset_stu(system: ICOsystem) -> bool:
    """Reset STU"""

    try:
        if system.sensor_node_attributes is not None:
            # A reset is only possible without sensor node connection. The
            # client may not know about the connection (e.g. after a reload).
            await system.disconnect_sensor_node()
        await system.reset_stu()
        return True
    except NoResponseError:
        return False

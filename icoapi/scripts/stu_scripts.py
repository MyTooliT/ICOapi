"""Scripts for stationary transceiver unit (STU)"""

from icostate import ICOsystem
from icotronic.can.error import NoResponseError
from icoapi.models.models import STUDeviceResponseModel


async def get_stu(system: ICOsystem) -> list[STUDeviceResponseModel]:
    """Get connected STU"""

    eui = await system.get_stu_mac_address()
    dev = STUDeviceResponseModel(device_number=1, mac_address=eui.format(), name="STU 1")

    return [dev]


async def reset_stu(system: ICOsystem) -> bool:
    """Reset STU"""

    try:
        await system.reset_stu()
        return True
    except NoResponseError:
        return False

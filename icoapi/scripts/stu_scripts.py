from icostate import ICOsystem
from icotronic.can.error import NoResponseError
from icoapi.models.models import STUDeviceResponseModel


async def get_stu(system: ICOsystem) -> list[STUDeviceResponseModel]:
    mac_eui = await system.stu.get_mac_address()
    dev = STUDeviceResponseModel(device_number=1, mac_address=mac_eui.format(), name="STU 1")

    return [dev]


async def reset_stu(system: ICOsystem) -> bool:
    try:
        await system.reset_stu()
        return True
    except NoResponseError:
        return False

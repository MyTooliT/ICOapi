from mytoolit.can import Network, NoResponseError
from netaddr import EUI
from icoapi.models.models import STUDeviceResponseModel


STU_1_NAME = "STU 1"


async def get_stu(network: Network) -> list[STUDeviceResponseModel]:
    mac_eui = await network.get_mac_address(STU_1_NAME)
    dev = STUDeviceResponseModel(
        device_number=1,
        mac_address=mac_eui.format(),
        name=STU_1_NAME)

    return [dev]


async def reset_stu(network: Network) -> bool:
    try:
        await network.reset_node(STU_1_NAME)
        return True
    except NoResponseError:
        return False


async def enable_ota(network: Network) -> bool:
    try:
        await network.activate_bluetooth(STU_1_NAME)
        return True
    except NoResponseError:
        return False


async def disable_ota(network: Network) -> bool:
    try:
        await network.deactivate_bluetooth(STU_1_NAME)
        return True
    except NoResponseError:
        return False

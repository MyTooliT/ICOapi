from mytoolit.can import Network, NoResponseError
from netaddr import EUI
from models.models import STUDeviceResponseModel


async def get_stu_mac(network: Network, node: str = 'STU 1') -> EUI | None:
    try:
        return await network.get_mac_address(node)

    except NoResponseError:
        # NOTE: We simply pass here as the consequence for the user is
        #       the same is with no STU being found.
        return None


async def get_stu_devices(network: Network) -> list[STUDeviceResponseModel]:
    stop = False
    index = 1
    devices: list[STUDeviceResponseModel] = []

    while not stop:
        try:
            mac_eui = await get_stu_mac(network, f'STU {index}')
            if mac_eui is not None:
                if mac_eui.format() not in [device.mac_address for device in devices]:
                    dev = STUDeviceResponseModel(
                        device_number=index,
                        mac_address=mac_eui.format(),
                        name=f"STU {index}")
                    devices.append(dev)
                    continue

            stop = True
        except NoResponseError:
            stop = True

    return devices


async def reset_stu(network: Network, name: str) -> bool:
    try:
        await network.reset_node(name)
        return True
    except NoResponseError:
        return False


async def enable_ota(network: Network, name: str) -> bool:
    try:
        await network.activate_bluetooth(name)
        return True
    except NoResponseError:
        return False


async def disable_ota(network: Network, name: str) -> bool:
    try:
        await network.deactivate_bluetooth(name)
        return True
    except NoResponseError:
        return False

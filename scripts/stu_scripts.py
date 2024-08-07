from mytoolit.can import Network, NoResponseError
from netaddr import EUI
from ..models.models import STUDeviceResponseModel


async def get_stu_mac(node: str = 'STU 1') -> EUI | None:
    try:
        async with Network() as network:
            return await network.get_mac_address(node)

    except:
        # NOTE: We simply pass here as the consequence for the user is
        #       the same is with no STU being found.
        return None


async def get_stu_devices() -> list[STUDeviceResponseModel]:
    stop = False
    index = 1
    devices: list[STUDeviceResponseModel] = []

    while not stop:
        try:
            mac_eui = await get_stu_mac(f'STU {index}')
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


async def reset_stu(name: str) -> bool:
    try:
        async with Network() as network:
            await network.reset_node(name)
            return True
    except NoResponseError:
        return False


async def enable_ota(name: str) -> bool:
    try:
        async with Network() as network:
            await network.activate_bluetooth(name)
            return True
    except NoResponseError:
        return False


async def disable_ota(name: str) -> bool:
    try:
        async with Network() as network:
            await network.deactivate_bluetooth(name)
            return True
    except NoResponseError:
        return False

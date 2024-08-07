from fastapi import APIRouter, status, Response, Body
from typing import Annotated
from mytoolit.can.network import CANInitError
from ..models.models import STHDeviceResponseModel, STHRenameRequestModel, STHRenameResponseModel
from ..scripts.sth_scripts import get_sth_devices_from_network, connect_sth_device_by_mac, disconnect_sth_devices, rename_sth_device
from ..scripts.errors import ConnectionTimeoutError, NoResponseError, Error

router = APIRouter(
    prefix="/sth",
    tags=["devices"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_model=list[STHDeviceResponseModel],
    responses={
        200: {
            "content": "application/json",
            "description": "Return the STH Devices reachable"
        },
        204: {
            "content": "application/json",
            "description": "Indicates no STH Devices in reach"
        }
},)
async def sth(response: Response) -> list[STHDeviceResponseModel]:
    devices = await get_sth_devices_from_network()
    if len(devices) == 0:
        response.status_code = status.HTTP_204_NO_CONTENT

    return [STHDeviceResponseModel.from_network(device) for device in devices]


@router.put(
    '/connect',
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": "application/json",
            "description": "Connection was successful"
        },
        404: {
            "content": "application/json",
            "description": "Indicates no STH Devices in reach"
        }
    }
)
async def sth_connect(mac: Annotated[str, Body(embed=True)], response: Response) -> None | Error:
    try:
        await connect_sth_device_by_mac(mac)
    except TimeoutError:
        response.status_code = status.HTTP_404_NOT_FOUND
        return ConnectionTimeoutError()
    except CANInitError:
        response.status_code = status.HTTP_404_NOT_FOUND
        return NoResponseError()


@router.put(
    '/disconnect',
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": "application/json",
            "description": "Disconnection was successful"
        },
        404: {
            "content": "application/json",
            "description": "Indicates error in disconnection"
        }
    }
)
async def sth_disconnect(mac: Annotated[str, Body(embed=True)], response: Response) -> None | Error:
    # Note: since there is no disconnect method on the Network class, we just disable BT on the STU.
    await disconnect_sth_devices()


@router.put(
    '/rename',
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": "application/json",
            "description": "Rename was successful"
        },
        502: {
            "content": "application/json",
            "description": "Indicates error in rename"
        }
    }
)
async def sth_rename(device_info: STHRenameRequestModel, response: Response) -> STHRenameResponseModel | NoResponseError:
    try:
        return await rename_sth_device(device_info.device_number, device_info.new_name)
    except TimeoutError:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return NoResponseError()



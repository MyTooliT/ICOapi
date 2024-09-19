from fastapi import APIRouter, status, Response, Body, Path
from typing import Annotated
from mytoolit.can.network import CANInitError
from mytoolit.can.adc import ADCConfiguration
from ..models.models import STHDeviceResponseModel, STHRenameRequestModel, STHRenameResponseModel, ADCValues
from ..scripts.sth_scripts import get_sth_devices_from_network, connect_sth_device_by_mac, disconnect_sth_devices, rename_sth_device, read_sth_adc, write_sth_adc
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
        }
},)
async def sth() -> list[STHDeviceResponseModel]:
    devices = await get_sth_devices_from_network()
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
async def sth_disconnect(response: Response) -> None:
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
        return await rename_sth_device(device_info.mac_address, device_info.new_name)
    except TimeoutError:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return NoResponseError()


@router.get(
    "/read-adc/{mac}",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": "application/json",
            "description": "ADC reading was successful"
        },
        504: {
            "content": "application/json",
            "description": "ADC reading timed out"
        }
    }
)
async def read_adc(mac: Annotated[str, Path(title="MAC Address of the STH")], response: Response) -> ADCValues | ConnectionTimeoutError:
    print(mac)
    try:
        values = await read_sth_adc(mac)
        return ADCValues(**values)
    except Error:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return ConnectionTimeoutError()


@router.put(
    "/write-adc",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": "application/json",
            "description": "ADC writing was successful"
        },
        504: {
            "content": "application/json",
            "description": "ADC writing timed out"
        }
    }
)
async def write_adc(mac: Annotated[str, Body(embed=True)], config: ADCValues, response: Response) -> None | ConnectionTimeoutError:
    try:
        await write_sth_adc(mac, config)
    except Error:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return ConnectionTimeoutError()



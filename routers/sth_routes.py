from typing import Annotated

from fastapi import APIRouter, Body, Path, Response, status, Depends
from mytoolit.can.network import CANInitError, Network

from models.models import ADCValues, STHDeviceResponseModel, STHRenameRequestModel, STHRenameResponseModel
from models.globals import get_network
from scripts.errors import ConnectionTimeoutError, Error, CANResponseError
from scripts.sth_scripts import connect_sth_device_by_mac, disconnect_sth_devices, get_sth_devices_from_network, \
    read_sth_adc, rename_sth_device, write_sth_adc

router = APIRouter(
    prefix="/sth",
    tags=["Sensory Tool Holder (STH)"],
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
async def sth(network: Network = Depends(get_network)) -> list[STHDeviceResponseModel]:
    devices = await get_sth_devices_from_network(network)
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
async def sth_connect(
    mac: Annotated[str, Body(embed=True)],
    response: Response,
    network: Network = Depends(get_network)
) -> None | ConnectionTimeoutError | CANResponseError:
    try:
        await connect_sth_device_by_mac(network, mac)
    except TimeoutError:
        response.status_code = status.HTTP_404_NOT_FOUND
        return ConnectionTimeoutError()
    except CANInitError:
        response.status_code = status.HTTP_404_NOT_FOUND
        return CANResponseError()


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
async def sth_disconnect(network: Network = Depends(get_network)) -> None:
    # Note: since there is no disconnect method on the Network class, we just disable BT on the STU.
    await disconnect_sth_devices(network)


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
async def sth_rename(
    device_info: STHRenameRequestModel,
    response: Response,
    network: Network = Depends(get_network)
) -> STHRenameResponseModel | CANResponseError:
    try:
        return await rename_sth_device(network, device_info.mac_address, device_info.new_name)
    except TimeoutError:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return CANResponseError()


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
async def read_adc(
    mac: Annotated[str, Path(title="MAC Address of the STH")],
    response: Response,
    network: Network = Depends(get_network)
) -> ADCValues | ConnectionTimeoutError:
    try:
        values = await read_sth_adc(network, mac)
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
async def write_adc(
    mac: Annotated[str, Body(embed=True)],
    config: ADCValues,
    response: Response,
    network: Network = Depends(get_network)
) -> None | ConnectionTimeoutError:
    try:
        await write_sth_adc(network, mac, config)
    except Error:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return ConnectionTimeoutError()



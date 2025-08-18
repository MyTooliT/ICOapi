from typing import Annotated
from fastapi import APIRouter, Body, Depends
from mytoolit.can import NoResponseError
from mytoolit.can.network import Network
from icoapi.scripts.errors import HTTP_404_STH_UNREACHABLE_EXCEPTION, HTTP_404_STH_UNREACHABLE_SPEC, HTTP_502_CAN_NO_RESPONSE_SPEC, HTTP_502_CAN_NO_RESPONSE_EXCEPTION
from icoapi.models.models import ADCValues, STHDeviceResponseModel, STHRenameRequestModel, STHRenameResponseModel
from icoapi.models.globals import get_network
from icoapi.scripts.sth_scripts import connect_sth_device_by_mac, disconnect_sth_devices, get_sth_devices_from_network, \
    read_sth_adc, rename_sth_device, write_sth_adc

router = APIRouter(
    prefix="/sth",
    tags=["Sensory Tool Holder (STH)"],
)

@router.get(
    '',
    response_model=list[STHDeviceResponseModel],
    responses={
        200: {
            "description": "Return the STH Devices reachable",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "The (Bluetooth advertisement) name of the STH"},
                                "device_number": {"type": "integer", "description": "The device number of the STH"},
                                "mac_address": {"type": "string", "description": "The (Bluetooth) MAC address of the STH"},
                                "rssi": {"type": "integer", "description": "The RSSI of the STH"},
                            },
                            "required": ["name", "device_number", "mac_address", "rssi"],
                        }
                    },
                    "example": [
                        {
                            "name": "STH-1234",
                            "device_number": 1,
                            "mac_address": "01:23:45:67:89:AB",
                            "rssi": -40
                        },
                        {
                            "name": "STH-5678",
                            "device_number": 2,
                            "mac_address": "12:34:56:78:9A:BC",
                            "rssi": -42
                        }
                    ]
                }
            },
        },
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def sth(network: Network = Depends(get_network)) -> list[STHDeviceResponseModel]:
    """Get a list of available sensor devices"""
    try:
        devices = await get_sth_devices_from_network(network)
        return [STHDeviceResponseModel.from_network(device) for device in devices]
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION



@router.put(
    '/connect',
    responses={
        200: {
            "description": "Connection was successful."
        },
        404: HTTP_404_STH_UNREACHABLE_SPEC,
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def sth_connect(
        mac_address: Annotated[str, Body(embed=True)],
        network: Network = Depends(get_network)
) -> None:
    try:
        await connect_sth_device_by_mac(network, mac_address)
        return None
    except TimeoutError:
        raise HTTP_404_STH_UNREACHABLE_EXCEPTION
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION



@router.put(
    '/disconnect',
    responses={
        200: {
            "description": "Disconnect was successful."
        },
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def sth_disconnect(network: Network = Depends(get_network)) -> None:
    try:
        await disconnect_sth_devices(network)
        return None
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


@router.put(
    '/rename',
    responses={
        200: {
            "description": "Connection was successful."
        },
        404: HTTP_404_STH_UNREACHABLE_SPEC,
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def sth_rename(
    device_info: STHRenameRequestModel,
    network: Network = Depends(get_network)
) -> STHRenameResponseModel:
    try:
        return await rename_sth_device(network, device_info.mac_address, device_info.new_name)
    except TimeoutError:
        raise HTTP_404_STH_UNREACHABLE_EXCEPTION
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


@router.get(
    "/read-adc",
    responses={
        200: {
            "description": "Connection was successful.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "prescaler": {"type": "integer", "nullable": True, "description": "ADC prescaler"},
                            "acquisition_time": {"type": "integer", "nullable": True, "description": "ADC acquisition time"},
                            "oversampling_rate": {"type": "integer", "nullable": True, "description": "ADC oversampling rate"},
                            "reference_voltage": {"type": "number", "format": "float", "nullable": True, "description": "ADC reference voltage"}
                        },
                        "required": []
                    },
                    "example": {
                        "prescaler": 8,
                        "acquisition_time": 12,
                        "oversampling_rate": 256,
                        "reference_voltage": 2.5
                    }
                }
            }
        },
        404: HTTP_404_STH_UNREACHABLE_SPEC,
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def read_adc(network: Network = Depends(get_network)) -> ADCValues:
    try:
        values = await read_sth_adc(network)
        if values is not None:
            return ADCValues(**values)
        else:
            raise HTTP_404_STH_UNREACHABLE_EXCEPTION
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


@router.put("/write-adc", responses={
    200: {
        "description": "ADC configuration written successfully."
    },
    404: HTTP_404_STH_UNREACHABLE_SPEC,
    502: HTTP_502_CAN_NO_RESPONSE_SPEC
})
async def write_adc(
    config: ADCValues,
    network: Network = Depends(get_network)
) -> None:
    try:
        await write_sth_adc(network, config)
        return None
    except TimeoutError:
        raise HTTP_404_STH_UNREACHABLE_EXCEPTION
    except NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION



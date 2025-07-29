from typing import Annotated
from fastapi import APIRouter, HTTPException, status, Body, Depends
from fastapi.responses import Response
from mytoolit.can.network import Network
from icoapi.models.models import STUDeviceResponseModel
from icoapi.models.globals import MeasurementState, get_measurement_state, get_network
from icoapi.scripts.stu_scripts import reset_stu, enable_ota, disable_ota, get_stu
from icoapi.scripts.errors import CANResponseError
import mytoolit.can

router = APIRouter(
    prefix="/stu",
    tags=["Stationary Transceiver Unit (STU)"],
)


@router.get('')
async def stu(network: Network = Depends(get_network)) -> list[STUDeviceResponseModel]:
    return await get_stu(network)


@router.put(
    '/reset',
    responses={
        200: {
            "description": "Indicates the STU has been reset.",
        },
        502: {
            "description": "The STU could not be reset.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Error response from CAN network.",
                        "status_code": 502,
                    },
                    "schema": {
                        "type": "object",
                        "properties": {
                            "detail": {"type": "string"},
                            "status_code": {"type": "integer"},
                        },
                        "required": ["detail", "status_code"]
                    },
                }
            }
        }
    }
)
async def stu_reset(
    network: Network = Depends(get_network),
    measurement_state: MeasurementState = Depends(get_measurement_state),
) -> None:
    if await reset_stu(network):
        await measurement_state.reset()
        return None
    else:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Error response from CAN network.")


@router.put('/ota/enable', responses={
    200: {
        "description": "Indicates the OTA has been enabled.",
    },
    502: {
        "description": "The OTA could not be enabled.",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Error response from CAN network.",
                    "status_code": 502,
                },
                "schema": {
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string"},
                        "status_code": {"type": "integer"},
                    },
                    "required": ["detail", "status_code"]
                },
            }
        }
    }
})
async def stu_enable_ota(network: Network = Depends(get_network)) -> None:
    if await enable_ota(network):
        return None
    else:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Error response from CAN network.")


@router.put('/ota/disable', responses={
    200: {
        "description": "Indicates the OTA has been disabled.",
    },
    502: {
        "description": "The OTA could not be disabled.",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Error response from CAN network.",
                    "status_code": 502,
                },
                "schema": {
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string"},
                        "status_code": {"type": "integer"},
                    },
                    "required": ["detail", "status_code"]
                },
            }
        }
    }
})
async def stu_disable_ota(
    response: Response,
    network: Network = Depends(get_network)
) -> None | CANResponseError:
    if await disable_ota(network):
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return CANResponseError()


@router.get(
    '/connected',
    response_model=bool,
    responses={
        200: {
            "description": "Returns true if the STU is connected, false otherwise.",
            "content": {
                "application/json": {
                    "schema": {"type": "boolean"},
                    "example": True
                }
            }
        },
        502: {
            "description": "The STU could not be reached.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "detail": {"type": "string"},
                            "status_code": {"type": "integer"},
                        },
                        "required": ["detail", "status_code"]
                    },
                    "example": {
                        "detail": "Error response from CAN network.",
                        "status_code": 502,
                    },
                }
            }
        }
    }
)
async def stu_connected(network: Network = Depends(get_network)):
    try:
        return await network.is_connected()
    except mytoolit.can.network.NoResponseError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No response from CAN network.")
    except mytoolit.can.network.ErrorResponseError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Error response from CAN network.")
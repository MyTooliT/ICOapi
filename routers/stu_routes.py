from typing import Annotated
from fastapi import APIRouter, HTTPException, status, Body, Depends
from fastapi.responses import Response
from mytoolit.can.network import Network
from models.models import STUDeviceResponseModel
from models.globals import MeasurementState, get_measurement_state, get_network
from scripts.stu_scripts import get_stu_devices, reset_stu, enable_ota, disable_ota
from scripts.errors import CANResponseError
import mytoolit.can

router = APIRouter(
    prefix="/stu",
    tags=["Stationary Transceiver Unit (STH)"],
)


@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_model=list[STUDeviceResponseModel]
)
async def stu(network: Network = Depends(get_network)) -> list[STUDeviceResponseModel]:
    return await get_stu_devices(network)


@router.put(
    '/reset',
    response_model=None | CANResponseError,
    status_code=status.HTTP_502_BAD_GATEWAY
)
async def stu_reset(
    name: Annotated[str, Body(embed=True)],
    response: Response,
    network: Network = Depends(get_network),
    measurement_state: MeasurementState = Depends(get_measurement_state)
) -> None | CANResponseError:
    if await reset_stu(network, name):
        response.status_code = status.HTTP_204_NO_CONTENT
        await measurement_state.reset()
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return CANResponseError()


@router.put('/ota/enable')
async def stu_enable_ota(
    name: Annotated[str, Body(embed=True)],
    response: Response,
    network: Network = Depends(get_network)
) -> None | CANResponseError:
    if await enable_ota(network, name):
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return CANResponseError()


@router.put('/ota/disable')
async def stu_disable_ota(
    name: Annotated[str, Body(embed=True)],
    response: Response,
    network: Network = Depends(get_network)
) -> None | CANResponseError:
    if await disable_ota(network, name):
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return CANResponseError()


@router.post('/connected')
async def stu_connected(name: Annotated[str, Body(embed=True)], network: Network = Depends(get_network)):
    try:
        return await network.is_connected(name)
    except mytoolit.can.network.NoResponseError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No response from CAN network.")
    except mytoolit.can.network.ErrorResponseError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Error response from CAN network.")
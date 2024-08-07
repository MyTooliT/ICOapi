from typing import Annotated
from fastapi import APIRouter, status, Body
from fastapi.responses import Response
from ..models.models import STHDeviceResponseModel, STUDeviceResponseModel
from ..scripts.stu_scripts import get_stu_devices, reset_stu, enable_ota, disable_ota
from ..scripts.errors import NoResponseError

router = APIRouter(
    prefix="/stu",
    tags=["devices"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_model=list[STUDeviceResponseModel],
    responses={
        200: {
            "content": "application/json",
            "description": "Return the STU Devices connected to the system"
        },
        204: {
            "content": "application/json",
            "description": "Indicates no STU Devices connected to the system"
        }
    },
)
async def stu(response: Response) -> list[STUDeviceResponseModel]:
    return await get_stu_devices()


@router.put(
    '/reset',
    response_model=None | NoResponseError,
    status_code=status.HTTP_502_BAD_GATEWAY,
    responses={
        204: {
            "description": "Device was successfully reset."
        },
        502: {
            "content": "application/json",
            "description": "The CAN Network did not respond. This can either be because the Node is not connected, "
                           "or the Network is unresponsive."
        }
    },
)
async def stu_reset(name: Annotated[str, Body(embed=True)], response: Response) -> None | NoResponseError:
    if await reset_stu(name):
        response.status_code = status.HTTP_204_NO_CONTENT
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return NoResponseError()


@router.put('/ota/enable')
async def stu_enable_ota(name: Annotated[str, Body(embed=True)], response: Response) -> None | NoResponseError:
    if await enable_ota(name):
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return NoResponseError()


@router.put('/ota/disable')
async def stu_disable_ota(name: Annotated[str, Body(embed=True)], response: Response) -> None | NoResponseError:
    if await disable_ota(name):
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    else:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return NoResponseError()
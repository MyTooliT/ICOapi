from fastapi import APIRouter, Depends
from mytoolit.can.network import Network
from icoapi.models.models import STUDeviceResponseModel
from icoapi.models.globals import MeasurementState, get_measurement_state, get_network
from icoapi.scripts.stu_scripts import reset_stu, enable_ota, disable_ota, get_stu
from icoapi.scripts.errors import HTTP_502_CAN_NO_RESPONSE_EXCEPTION, HTTP_502_CAN_NO_RESPONSE_SPEC
import mytoolit.can

router = APIRouter(
    prefix="/stu",
    tags=["Stationary Transceiver Unit (STU)"],
)


@router.get('')
async def stu(network: Network = Depends(get_network)) -> list[STUDeviceResponseModel]:
    try:
        return await get_stu(network)
    except mytoolit.can.network.NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


@router.put(
    '/reset',
    responses={
        200: {
            "description": "Indicates the STU has been reset.",
        },
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
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
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


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
        502: HTTP_502_CAN_NO_RESPONSE_SPEC
    }
)
async def stu_connected(network: Network = Depends(get_network)):
    try:
        return await network.is_connected()
    except mytoolit.can.network.NoResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION
    except mytoolit.can.network.ErrorResponseError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION
    except AttributeError:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION
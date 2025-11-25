"""Routes for STU functionality"""

from fastapi import APIRouter, Depends
from icostate import ICOsystem
from icostate.error import IncorrectStateError
from icotronic.can.error import ErrorResponseError, NoResponseError

from icoapi.models.models import STUDeviceResponseModel
from icoapi.models.globals import (
    MeasurementState,
    get_measurement_state,
    get_system,
)
from icoapi.scripts.stu_scripts import reset_stu, get_stu
from icoapi.scripts.errors import (
    HTTP_400_INCORRECT_STATE_EXCEPTION,
    HTTP_502_CAN_NO_RESPONSE_EXCEPTION,
    HTTP_502_CAN_NO_RESPONSE_SPEC,
)

router = APIRouter(
    prefix="/stu",
    tags=["Stationary Transceiver Unit (STU)"],
)


@router.get("")
async def stu(
    system: ICOsystem = Depends(get_system),
) -> list[STUDeviceResponseModel]:
    """Get available STU"""

    try:
        return await get_stu(system)
    except NoResponseError as error:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION from error


@router.put(
    "/reset",
    responses={
        200: {
            "description": "Indicates the STU has been reset.",
        },
        502: HTTP_502_CAN_NO_RESPONSE_SPEC,
    },
)
async def stu_reset(
    system: ICOsystem = Depends(get_system),
    measurement_state: MeasurementState = Depends(get_measurement_state),
) -> None:
    """Reset STU"""

    try:
        if await reset_stu(system):
            await measurement_state.reset()
            return None
    except IncorrectStateError as error:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION from error

    raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION


@router.get(
    "/connected",
    response_model=bool,
    responses={
        200: {
            "description": (
                "Returns true if the STU is connected, false otherwise."
            ),
            "content": {
                "application/json": {
                    "schema": {"type": "boolean"},
                    "example": True,
                }
            },
        },
        502: HTTP_502_CAN_NO_RESPONSE_SPEC,
    },
)
async def stu_connected(system: ICOsystem = Depends(get_system)):
    """Check if the STU is connected to a sensor device"""

    try:
        return await system.is_sensor_node_connected()
    except (AttributeError, ErrorResponseError, NoResponseError) as error:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION from error

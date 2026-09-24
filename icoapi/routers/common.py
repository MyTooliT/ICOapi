"""Common endpoints"""

import logging
from typing import Annotated

from fastapi import APIRouter, status
from fastapi.params import Depends
from starlette.websockets import WebSocket, WebSocketDisconnect

from icoapi.models.globals import (
    GeneralMessenger,
    MeasurementState,
    ICOsystemSingleton,
    get_measurement_state,
    get_messenger,
    get_trident_feature,
)
from icoapi.models.models import Feature, SystemStateModel
from icoapi.scripts.file_handling import get_disk_space_in_gib

router = APIRouter(tags=["General"])

logger = logging.getLogger(__name__)


@router.get("/state", status_code=status.HTTP_200_OK)
def state(
    measurement_state: Annotated[
        MeasurementState, Depends(get_measurement_state)
    ],
    cloud: Annotated[Feature, Depends(get_trident_feature)],
) -> SystemStateModel:
    """Get system state"""

    return SystemStateModel(
        can_ready=ICOsystemSingleton.has_instance(),
        disk_capacity=get_disk_space_in_gib(),
        measurement_status=measurement_state.get_status(),
        cloud=cloud,
    )


@router.put("/reset-can", status_code=status.HTTP_200_OK)
async def reset_can():
    """Reset CAN connection"""

    await ICOsystemSingleton.close_instance()
    await ICOsystemSingleton.create_instance_if_none()


@router.websocket("/state")
async def state_websocket(
    websocket: WebSocket,
    messenger: Annotated[GeneralMessenger, Depends(get_messenger)],
):
    """State WebSocket for general information about system state

    The server pushes state updates to the client. Messages sent by the client
    are ignored, use ``GET /state`` to request the current state.
    """

    await websocket.accept()
    messenger.add_messenger(websocket)

    try:
        # Only the new client needs the current state
        await messenger.push_state_to(websocket)

        # Only receive to notice when the client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        messenger.remove_messenger(websocket)

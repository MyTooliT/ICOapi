"""Common endpoints"""

import logging
from typing import Annotated

from fastapi import APIRouter, status
from fastapi.params import Depends
from starlette.websockets import WebSocket

from icoapi.models.event_bus import WebSocketEventBus
from icoapi.models.globals import (
    ICOsystemSingleton,
    build_system_state,
    get_websocket_event_bus,
    require_no_measurement,
)
from icoapi.models.models import SystemStateModel
from icoapi.scripts.errors import HTTP_409_MEASUREMENT_RUNNING_SPEC

router = APIRouter(tags=["General"])

logger = logging.getLogger(__name__)


@router.get("/state", status_code=status.HTTP_200_OK)
async def state() -> SystemStateModel:
    """Get system state"""

    return await build_system_state()


@router.put(
    "/reset-can",
    status_code=status.HTTP_200_OK,
    responses={409: HTTP_409_MEASUREMENT_RUNNING_SPEC},
    dependencies=[Depends(require_no_measurement)],
)
async def reset_can():
    """Reset CAN connection

    Disconnects and searches for CAN networks again. The API reconnects to the
    network it was connected to before, if that network is still available. If
    it was not connected, it only reconnects if autoconnect is enabled.
    """

    try:
        await ICOsystemSingleton.reset()
    except Exception as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        logger.error("Cannot reconnect to CAN network: %s", error)


@router.websocket("/state")
async def state_websocket(
    websocket: WebSocket,
    bus: Annotated[WebSocketEventBus, Depends(get_websocket_event_bus)],
):
    """State WebSocket for general information about system state

    The server pushes state updates to the client. Messages sent by the client
    are ignored, use ``GET /state`` to request the current state.
    """

    await websocket.accept()
    bus.add_client(websocket)

    try:
        # Only the new client needs the current state
        await bus.send_state_to(websocket, await build_system_state())

        # Ignore everything the client sends (text and binary messages), only
        # receive to notice when the client disconnects
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        bus.remove_client(websocket)

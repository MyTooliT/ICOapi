import json
import logging

from fastapi import APIRouter, status
from fastapi.params import Depends
from starlette.websockets import WebSocket, WebSocketDisconnect

from icoapi.models.globals import GeneralMessenger, MeasurementState, NetworkSingleton, get_measurement_state, \
    get_messenger, get_trident_client
from icoapi.models.models import SocketMessage, SystemStateModel
from icoapi.models.trident import StorageClient
from icoapi.scripts.file_handling import get_disk_space_in_gb

router = APIRouter(
    tags=["General"]
)

logger = logging.getLogger(__name__)

@router.get("/state", status_code=status.HTTP_200_OK)
def state(measurement_state: MeasurementState = Depends(get_measurement_state), storage: StorageClient = Depends(get_trident_client)) -> SystemStateModel:
    return SystemStateModel(
        can_ready=NetworkSingleton.has_instance(),
        disk_capacity=get_disk_space_in_gb(),
        measurement_status=measurement_state.get_status(),
        cloud_status=bool(storage.is_authenticated())
    )


@router.put("/reset-can", status_code=status.HTTP_200_OK)
async def reset_can():
    await NetworkSingleton.close_instance()
    await NetworkSingleton.create_instance_if_none()


@router.websocket("/state")
async def state_websocket(
        websocket: WebSocket,
        messenger: GeneralMessenger = Depends(get_messenger),
):
    await websocket.accept()
    messenger.add_messenger(websocket)

    try:
        await messenger.push_messenger_update()

        while True:
            text = await websocket.receive_text()
            msg = SocketMessage(**json.loads(text))
            if msg.message == "get_state":
                await messenger.push_messenger_update()
    except WebSocketDisconnect:
        messenger.remove_messenger(websocket)

import asyncio
import datetime

from fastapi import APIRouter, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from models.autogen.metadata import UnifiedMetadata
from models.models import MeasurementStatus, ControlResponse, MeasurementInstructions
from models.globals import get_network, get_measurement_state, MeasurementState, Network
from scripts.measurement import run_measurement

router = APIRouter(
    prefix="/measurement",
    tags=["Measurement"]
)

@router.post("/start", response_model=ControlResponse)
async def start_measurement(
        instructions: MeasurementInstructions,
        network: Network = Depends(get_network),
        measurement_state: MeasurementState = Depends(get_measurement_state)
):
    message: str = "Measurement is already running."
    if not measurement_state.running:
        start = datetime.datetime.now()
        measurement_state.running = True
        measurement_state.name = instructions.name if instructions.name else start.strftime("%Y-%m-%d_%H-%M-%S")
        measurement_state.start_time = start.isoformat()
        try:
            measurement_state.tool_name = await network.get_name(node="STH 1")
        except Exception:
            measurement_state.tool_name = "noname"
        measurement_state.instructions = instructions
        measurement_state.task = asyncio.create_task(run_measurement(network, instructions, measurement_state))

        message = "Measurement started successfully."

    return ControlResponse(message=message, data=measurement_state.get_status())


@router.post("/stop", response_model=ControlResponse)
async def stop_measurement(measurement_state: MeasurementState = Depends(get_measurement_state)):
    message = "Measurement stopped successfully."
    data = measurement_state.get_status()

    if not measurement_state.running:
        message="No active measurement to stop."

    if measurement_state.task:
        measurement_state.task.cancel()

    measurement_state.reset()

    return ControlResponse(message=message, data=data)


@router.get("", response_model=MeasurementStatus)
async def measurement_status(measurement_state: MeasurementState = Depends(get_measurement_state)):
    return measurement_state.get_status()


@router.websocket("/stream")
async def websocket_endpoint(
        websocket: WebSocket,
        measurement_state: MeasurementState = Depends(get_measurement_state),
):
    await websocket.accept()
    measurement_state.clients.append(websocket)
    print(f"Client connected! {len(measurement_state.clients)} clients")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        measurement_state.clients.remove(websocket)
        print(f"Client disconnected! {len(measurement_state.clients)} clients")


@router.post("/metadata")
async def submit_metadata(data: UnifiedMetadata):
    """
    This should never be accessed. The metadata should be sent on measurement start and not updated.
    This solely exists to make openAPI parse the UnifiedMetadata class.
    """
    raise NotImplementedError()
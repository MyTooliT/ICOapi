import asyncio
import datetime
import logging

import pathvalidate
from fastapi import APIRouter, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect

from models.models import MeasurementSocketMessage, MeasurementStatus, ControlResponse, MeasurementInstructions
from models.globals import get_network, get_measurement_state, MeasurementState, Network
from scripts.measurement import run_measurement

router = APIRouter(
    prefix="/measurement",
    tags=["Measurement"]
)

logger = logging.getLogger(__name__)

@router.post("/start", response_model=ControlResponse)
async def start_measurement(
        instructions: MeasurementInstructions,
        network: Network = Depends(get_network),
        measurement_state: MeasurementState = Depends(get_measurement_state)
):
    message: str = "Measurement is already running."

    if not measurement_state.running:
        start = datetime.datetime.now()
        filename = start.strftime("%Y-%m-%d_%H-%M-%S")
        if instructions.name:
            sanitized = pathvalidate.sanitize_filename(instructions.name)
            filename = sanitized + "__" + filename
        if instructions.meta:
            measurement_state.pre_meta = instructions.meta
        measurement_state.running = True
        measurement_state.name = filename
        measurement_state.start_time = start.isoformat()
        try:
            measurement_state.tool_name = await network.get_name(node="STH 1")
            logger.debug(f"Tool found - name: {measurement_state.tool_name}")
        except Exception:
            measurement_state.tool_name = "noname"
            logger.error(f"Tool not found!")
        measurement_state.instructions = instructions
        measurement_state.task = asyncio.create_task(run_measurement(network, instructions, measurement_state))
        logger.info(f"Created measurement task with tool <{measurement_state.tool_name}> and timeout of {instructions.time}")

        message = "Measurement started successfully."

    return ControlResponse(message=message, data=measurement_state.get_status())


@router.post("/stop", response_model=ControlResponse)
async def stop_measurement(message: MeasurementSocketMessage, measurement_state: MeasurementState = Depends(get_measurement_state)):
    msg = "Measurement stopped successfully."
    data = measurement_state.get_status()

    if not measurement_state.running:
        logger.warning("Tried to stop without an active measurement")
        msg="No active measurement to stop."

    if measurement_state.task:
        measurement_state.task.cancel()

    await measurement_state.reset()

    return ControlResponse(message=msg, data=data)


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
    logger.info(f"Client connected to measurement stream - now {len(measurement_state.clients)} clients")

    try:
        while True:
            msg: MeasurementSocketMessage = await websocket.receive_json()
            logger.info(f"Received message from client: {msg.message}")
            if msg.message == "stop":
                measurement_state.post_metadata = msg.data
                measurement_state.stop_flag = True
    except WebSocketDisconnect:
        try:
            measurement_state.clients.remove(websocket)
            logger.info(f"Client disconnected from measurement stream - now {len(measurement_state.clients)} clients")
        except ValueError:
            logger.debug(f"Client was already disconnected - still {len(measurement_state.clients)} clients")

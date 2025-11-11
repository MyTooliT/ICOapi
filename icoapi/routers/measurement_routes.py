import asyncio
import datetime
import logging

import pathvalidate
from fastapi import APIRouter, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect

from icoapi.models.models import (
    MeasurementStatus,
    ControlResponse,
    MeasurementInstructions,
    Metadata,
)
from icoapi.models.globals import (
    get_messenger,
    get_system,
    get_measurement_state,
    MeasurementState,
    ICOsystem,
)
from icoapi.scripts.measurement import run_measurement

router = APIRouter(prefix="/measurement", tags=["Measurement"])

logger = logging.getLogger(__name__)


@router.post("/start", response_model=ControlResponse)
async def start_measurement(
    instructions: MeasurementInstructions,
    system: ICOsystem = Depends(get_system),
    measurement_state: MeasurementState = Depends(get_measurement_state),
    general_messenger=Depends(get_messenger),
):
    message: str = "Measurement is already running."
    measurement_state.stop_flag = False

    if not measurement_state.running:
        start = datetime.datetime.now()
        filename = start.strftime("%Y-%m-%d_%H-%M-%S")
        if instructions.name:
            replaced = (
                instructions.name.replace("ä", "ae")
                .replace("ö", "oe")
                .replace("ü", "ue")
                .replace("Ä", "Ae")
                .replace("Ö", "Oe")
                .replace("Ü", "Ue")
            )
            sanitized = pathvalidate.sanitize_filename(replaced)
            filename = sanitized + "__" + filename
        if instructions.meta:
            measurement_state.pre_meta = instructions.meta
        measurement_state.running = True
        measurement_state.name = filename
        measurement_state.wait_for_post_meta = instructions.wait_for_post_meta
        measurement_state.start_time = start.isoformat()
        try:
            measurement_state.tool_name = await system.sensor_node.get_name()
            logger.debug(f"Tool found - name: {measurement_state.tool_name}")
        except Exception:
            measurement_state.tool_name = "noname"
            logger.error("Tool not found!")
        measurement_state.instructions = instructions
        measurement_state.task = asyncio.create_task(
            run_measurement(system, instructions, measurement_state, general_messenger)
        )
        logger.info(
            f"Created measurement task with tool <{measurement_state.tool_name}> and"
            f" timeout of {instructions.time}"
        )

        message = "Measurement started successfully."

    return ControlResponse(message=message, data=measurement_state.get_status())


@router.post("/stop")
async def stop_measurement(
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    logger.info("Received stop request.")
    measurement_state.stop_flag = True


@router.post("/post_meta")
async def post_meta(
    meta: Metadata, measurement_state: MeasurementState = Depends(get_measurement_state)
):
    measurement_state.post_meta = meta
    logger.info("Received and set post metadata")


@router.get("", response_model=MeasurementStatus)
async def measurement_status(
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    return measurement_state.get_status()


@router.websocket("/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    await websocket.accept()
    measurement_state.clients.append(websocket)
    logger.info(
        f"Client connected to measurement stream - now {len(measurement_state.clients)} clients"
    )

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        try:
            measurement_state.clients.remove(websocket)
            logger.info(
                "Client disconnected from measurement stream - now"
                f" {len(measurement_state.clients)} clients"
            )
        except ValueError:
            logger.debug(
                f"Client was already disconnected - still {len(measurement_state.clients)} clients"
            )

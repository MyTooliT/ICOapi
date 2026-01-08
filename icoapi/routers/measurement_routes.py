"""Routes for measurement data"""

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
from icoapi.scripts.errors import (
    HTTP_504_MEASUREMENT_TIMEOUT_EXCEPTION,
    HTTP_504_MEASUREMENT_TIMEOUT_SPEC,
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
    """Start measurement"""

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
            logger.debug("Tool found - name: %s", measurement_state.tool_name)
        except AttributeError:
            measurement_state.tool_name = "noname"
            logger.error("Tool not found!")
        measurement_state.instructions = instructions
        measurement_state.task = asyncio.create_task(
            run_measurement(
                system, instructions, measurement_state, general_messenger
            )
        )
        logger.info(
            "Created measurement task with tool <%s> and timeout of %s",
            measurement_state.tool_name,
            instructions.time,
        )

        message = "Measurement started successfully."

    return ControlResponse(
        message=message, data=measurement_state.get_status()
    )


@router.post(
    "/stop",
    responses={
        200: {"description": "Measurement stopped successfully."},
        504: HTTP_504_MEASUREMENT_TIMEOUT_SPEC,
    },
)
async def stop_measurement(
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    """Stop measurement"""

    async def wait_until_measurement_is_stopped():
        while measurement_state.running:
            await asyncio.sleep(0.1)

    logger.info("Received stop request.")
    measurement_state.stop_flag = True

    timeout = 10
    try:
        await asyncio.wait_for(
            wait_until_measurement_is_stopped(), timeout=timeout
        )
    except TimeoutError as error:
        raise HTTP_504_MEASUREMENT_TIMEOUT_EXCEPTION from error


@router.post("/post_meta")
async def post_meta(
    meta: Metadata,
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    """Set post-measurement metadata"""

    measurement_state.post_meta = meta
    logger.info("Received and set post metadata")


@router.get("", response_model=MeasurementStatus)
async def measurement_status(
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    """Get measurement status"""
    return measurement_state.get_status()


@router.websocket("/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    measurement_state: MeasurementState = Depends(get_measurement_state),
):
    """Stream measurement data"""

    await websocket.accept()
    measurement_state.clients.append(websocket)
    logger.info(
        "Client connected to measurement stream - now %s clients",
        len(measurement_state.clients),
    )

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        try:
            measurement_state.clients.remove(websocket)
            logger.info(
                "Client disconnected from measurement stream - now %s clients",
                len(measurement_state.clients),
            )
        except ValueError:
            logger.debug(
                "Client was already disconnected - still %s clients",
                len(measurement_state.clients),
            )

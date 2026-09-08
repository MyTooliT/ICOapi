"""Routes for measurement data"""

import asyncio
import datetime
import logging
from typing import Annotated, Awaitable

import pathvalidate
from fastapi import APIRouter, Body, Depends
from icostate.error import IncorrectStateError
from icotronic.can import NoResponseError
from icotronic.can.error import UnsupportedFeatureException
from icotronic.can.sensor import SensorConfiguration
from netaddr import AddrFormatError, EUI
from starlette import status
from starlette.websockets import WebSocket, WebSocketDisconnect

from icoapi.models.models import (
    MeasurementStatus,
    ControlResponse,
    MeasurementInstructions,
    Metadata,
    ResolvedMeasurementChannels,
)
from icoapi.utils.measurement_examples import EXECUTE_EXAMPLES
from icoapi.models.globals import (
    get_messenger,
    get_system,
    get_measurement_state,
    MeasurementState,
    ICOsystem,
)
from icoapi.scripts.errors import (
    HTTP_400_INCORRECT_STATE_EXCEPTION,
    HTTP_400_UNSUPPOERTED_FEATURE_EXCEPTION,
    HTTP_422_INVALID_ADC_CONFIGURATION_EXCEPTION,
    HTTP_502_CAN_NO_RESPONSE_EXCEPTION,
    HTTP_504_MEASUREMENT_TIMEOUT_EXCEPTION,
    HTTP_504_MEASUREMENT_TIMEOUT_SPEC,
    HTTP_EXECUTE_STEP_FAILED_EXCEPTION,
)

from icoapi.scripts.data_handling import resolve_measurement_channels
from icoapi.scripts.measurement import (
    measurement_preparations,
    run_measurement,
    verify_sensor_configuration_applied,
    write_sensor_config_if_required,
)
from icoapi.scripts.sth_scripts import (
    connect_sth_device_by_mac,
    disconnect_sth_devices,
    write_sth_adc,
)

router = APIRouter(prefix="/measurement", tags=["Measurement"])

logger = logging.getLogger(__name__)


async def _begin_measurement(
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    system: ICOsystem,
    measurement_state: MeasurementState,
    general_messenger,
) -> ControlResponse:
    """Name, register and launch the measurement task.

    Shared by `/start` and `/execute` - everything here is agnostic to how
    the sensor node got into `SENSOR_NODE_CONNECTED` with the right ADC and
    sensor configuration already applied, which is the only thing that
    differs between the two callers.
    """

    if measurement_state.running:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION

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

    measurement_state.stop_flag = False
    measurement_state.name = filename
    measurement_state.wait_for_post_meta = instructions.wait_for_post_meta
    measurement_state.start_time = start.isoformat()
    measurement_state.instructions = instructions

    try:
        measurement_state.tool_name = await system.sensor_node.get_name()
        logger.debug("Tool found - name: %s", measurement_state.tool_name)
    except AttributeError:
        measurement_state.tool_name = "noname"
        logger.error("Tool not found!")

    try:
        measurement_state.start_supply_voltage = (
            await system.sensor_node.get_supply_voltage()
        )
        logger.debug(
            "Supply voltage at measurement start: %sV",
            measurement_state.start_supply_voltage,
        )
    except (AttributeError, NoResponseError):
        measurement_state.start_supply_voltage = None
        logger.error("Could not read supply voltage at measurement start!")

    measurement_state.task = asyncio.create_task(
        run_measurement(
            system,
            instructions,
            resolved_channels,
            measurement_state,
            general_messenger,
        )
    )
    logger.info(
        "Created measurement task with tool <%s> and timeout of %s",
        measurement_state.tool_name,
        instructions.time,
    )

    measurement_state.running = True
    await general_messenger.push_messenger_update()

    return ControlResponse(
        message="Measurement started successfully.",
        data=measurement_state.get_status(),
    )


@router.post("/start", response_model=ControlResponse)
async def start_measurement(
    instructions: MeasurementInstructions,
    system: ICOsystem = Depends(get_system),
    measurement_state: MeasurementState = Depends(get_measurement_state),
    general_messenger=Depends(get_messenger),
):
    """Start measurement"""

    resolved_channels = resolve_measurement_channels(instructions)

    try:
        await measurement_preparations(system, instructions, resolved_channels)
    except UnsupportedFeatureException as exc:
        raise HTTP_400_UNSUPPOERTED_FEATURE_EXCEPTION from exc
    except IncorrectStateError as exc:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION from exc
    except NoResponseError as exc:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION from exc
    except AssertionError as exc:
        raise HTTP_422_INVALID_ADC_CONFIGURATION_EXCEPTION from exc

    return await _begin_measurement(
        instructions, resolved_channels, system, measurement_state,
        general_messenger,
    )


async def _run_execute_step[T](step: str, awaitable: Awaitable[T]) -> T:
    """Await one step of `/measurement/execute`, translating a domain
    exception into a step-tagged HTTPException - the status code matches
    what the same failure would already produce on the single-purpose
    endpoints (`/sth/connect`, `/sth/write-adc`, `/measurement/start`), only
    the step name is new.
    """

    try:
        return await awaitable
    except UnsupportedFeatureException as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except IncorrectStateError as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except TimeoutError as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_404_NOT_FOUND, str(exc)
        ) from exc
    except NoResponseError as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_502_BAD_GATEWAY, str(exc)
        ) from exc
    except (ValueError, AddrFormatError) as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
        ) from exc


@router.post("/execute", response_model=ControlResponse)
async def execute_measurement(
    instructions: Annotated[
        MeasurementInstructions, Body(openapi_examples=EXECUTE_EXAMPLES)
    ],
    system: ICOsystem = Depends(get_system),
    measurement_state: MeasurementState = Depends(get_measurement_state),
    general_messenger=Depends(get_messenger),
):
    """Connect, configure and start a measurement in one call, for headless
    orchestration.

    All-or-nothing: on any failure, the STH is disconnected rather than left
    connected with a half-applied configuration. Idempotent with respect to
    an already-connected STH at the requested MAC address - the existing
    connection is reused rather than being torn down and re-established.
    """

    # Checked before touching the connection at all: disconnecting,
    # rewriting the ADC configuration or rewriting sensor channel routing
    # while a measurement is already streaming over that same connection
    # would corrupt it, not just fail cleanly.
    if measurement_state.running:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION

    resolved_channels = resolve_measurement_channels(instructions)

    try:
        requested_mac = EUI(instructions.mac_address)
    except AddrFormatError:
        requested_mac = None

    already_connected = (
        system.sensor_node_attributes is not None
        and requested_mac is not None
        and system.sensor_node_attributes.mac_address == requested_mac
    )

    try:
        if system.sensor_node_attributes is not None and not already_connected:
            await _run_execute_step(
                "connect", disconnect_sth_devices(system)
            )

        if not already_connected:
            await _run_execute_step(
                "connect",
                connect_sth_device_by_mac(system, instructions.mac_address),
            )

        if instructions.adc is not None:
            await _run_execute_step(
                "write-adc", write_sth_adc(system, instructions.adc)
            )

        sensor_configuration = SensorConfiguration(
            resolved_channels.first.channel_number,
            resolved_channels.second.channel_number,
            resolved_channels.third.channel_number,
        )
        await _run_execute_step(
            "sensor-configuration",
            write_sensor_config_if_required(system, sensor_configuration),
        )
        await verify_sensor_configuration_applied(
            system, sensor_configuration
        )
    except Exception:
        if system.sensor_node_attributes is not None:
            await disconnect_sth_devices(system)
        raise

    # Deliberately not wrapped in a disconnect-on-failure like the steps
    # above: connect/write-adc/sensor-configuration are what "half-applied"
    # in the docstring refers to, and by this point they have all already
    # succeeded. `_begin_measurement`'s only realistic failure is "a
    # measurement is already running" - disconnecting here would tear down
    # that *other*, already-running measurement's connection instead of
    # cleaning up this failed call.
    return await _begin_measurement(
        instructions, resolved_channels, system, measurement_state,
        general_messenger,
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

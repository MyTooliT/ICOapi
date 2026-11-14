"""Routes for measurement data"""

import asyncio
import datetime
import logging
from pathlib import Path
from typing import Annotated, Awaitable

import pathvalidate
from fastapi import APIRouter, Body, Depends, HTTPException
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
    MeasurementInstructionChannel,
    MeasurementInstructions,
    ResolvedChannel,
    ResolvedMeasurementChannels,
)
from icoapi.utils.measurement_examples import EXECUTE_EXAMPLES
from icoapi.models.globals import (
    Unit,
    get_messenger,
    get_system,
    get_measurement_state,
    ICOsystemSingleton,
    MeasurementState,
    ICOsystem,
)
from icoapi.scripts.errors import (
    HTTP_400_INCORRECT_STATE_EXCEPTION,
    HTTP_400_UNSUPPOERTED_FEATURE_EXCEPTION,
    HTTP_422_INVALID_ADC_CONFIGURATION_EXCEPTION,
    HTTP_502_CAN_NO_RESPONSE_EXCEPTION,
    HTTP_503_CAN_NOT_CONNECTED_EXCEPTION,
    HTTP_503_CAN_NOT_CONNECTED_SPEC,
    HTTP_504_MEASUREMENT_TIMEOUT_EXCEPTION,
    HTTP_504_MEASUREMENT_TIMEOUT_SPEC,
    HTTP_EXECUTE_STEP_FAILED_EXCEPTION,
)

from icoapi.scripts.data_handling import resolve_measurement_channels
from icoapi.scripts.features import multi_stu_support
from icoapi.scripts.group_measurement import run_group_measurement
from icoapi.scripts.preflight import (
    UnitCheck,
    check_units,
    describe_checks,
    raise_for_failed_checks,
)
from icoapi.scripts.file_handling import get_measurement_dir
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


def _new_measurement_name(
    instructions: MeasurementInstructions,
) -> tuple[datetime.datetime, str]:
    """Get the start time and the (unused) name of the file of a measurement"""

    # With UTC offset, so that clients in other time zones (remote access)
    # interpret the start time correctly. The file name uses local time.
    start = datetime.datetime.now().astimezone()
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

    # The time stamp only has a resolution of one second. A measurement
    # started in the same second as another one must not use the same file.
    unique_filename = filename
    number = 1
    while (Path(get_measurement_dir()) / f"{unique_filename}.hdf5").exists():
        number += 1
        unique_filename = f"{filename}_{number}"
    filename = unique_filename

    return start, filename


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

    Several clients can start a measurement at the same time. The check
    whether a measurement is running and marking the new one as running
    happen under the lock of the measurement state, so only one of them
    starts a measurement and the others get an error.
    """

    async with measurement_state.lock:
        return await _begin_measurement_locked(
            instructions,
            resolved_channels,
            system,
            measurement_state,
            general_messenger,
        )


async def _begin_measurement_locked(
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    system: ICOsystem,
    measurement_state: MeasurementState,
    general_messenger,
) -> ControlResponse:
    """Start the measurement (caller must hold the measurement state lock)"""

    if measurement_state.running:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION

    start, filename = _new_measurement_name(instructions)

    if instructions.meta:
        measurement_state.pre_meta = instructions.meta

    measurement_state.stop_flag = False
    measurement_state.name = filename
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


# -- Measurements with several units (multi STU support) ----------------------


def _uses_several_units() -> bool:
    """Check if measurements use more than one unit"""

    return multi_stu_support() and len(ICOsystemSingleton.units()) > 1


# pylint: disable-next=too-many-arguments,too-many-positional-arguments
async def _begin_group_measurement(
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    units: list[Unit],
    checks: list[UnitCheck],
    measurement_state: MeasurementState,
    general_messenger,
) -> ControlResponse:
    """Name, register and launch the measurement task for all units

    Like :func:`_begin_measurement`, but for the units that were checked
    already (see :func:`_start_group_measurement`).
    """

    async with measurement_state.lock:
        if measurement_state.running:
            raise HTTP_400_INCORRECT_STATE_EXCEPTION

        start, filename = _new_measurement_name(instructions)

        if instructions.meta:
            measurement_state.pre_meta = instructions.meta

        voltages = [
            check.supply_voltage
            for check in checks
            if check.supply_voltage is not None
        ]
        measurement_state.stop_flag = False
        measurement_state.name = filename
        measurement_state.start_time = start.isoformat()
        measurement_state.instructions = instructions
        measurement_state.tool_name = ", ".join(
            check.tool_name or check.unit for check in checks
        )
        # The lowest voltage is the one that matters
        measurement_state.start_supply_voltage = (
            min(voltages) if voltages else None
        )

        measurement_state.task = asyncio.create_task(
            run_group_measurement(
                units,
                checks,
                instructions,
                resolved_channels,
                measurement_state,
                general_messenger,
            )
        )
        logger.info(
            "Created measurement task for %s units with timeout of %s",
            len(units),
            instructions.time,
        )

        measurement_state.running = True
        await general_messenger.push_messenger_update()

        return ControlResponse(
            message="Measurement started successfully.",
            data=measurement_state.get_status(),
        )


async def _start_group_measurement(
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
    general_messenger,
    *,
    disconnect_on_failure: bool = False,
) -> ControlResponse:
    """Start a measurement with all units

    All-or-nothing: Every unit has to be ready (see
    :mod:`icoapi.scripts.preflight`), otherwise nothing is started and the
    error lists the problems of all units.

    Args:

        disconnect_on_failure:
            Disconnect the sensor devices of all units, if the measurement
            can not be started
    """

    # Checked before touching any unit: Changing the configuration of units
    # that stream would corrupt the running measurement
    if measurement_state.running:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION

    if instructions.ift_requested:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "IFT values can only be calculated for measurements with a "
                "single unit"
            ),
        )

    resolved_channels = resolve_measurement_channels(instructions)
    units = ICOsystemSingleton.units()

    checks = await check_units(
        units, instructions, resolved_channels, configure=True
    )
    try:
        raise_for_failed_checks(checks)
    except HTTPException:
        if disconnect_on_failure:
            await _disconnect_units(units)
        raise

    return await _begin_group_measurement(
        instructions,
        resolved_channels,
        units,
        checks,
        measurement_state,
        general_messenger,
    )


async def _disconnect_units(units: list[Unit]) -> None:
    """Disconnect the sensor devices of the units (failures are logged)"""

    async def disconnect(unit: Unit) -> None:
        if unit.system.sensor_node_attributes is None:
            return
        try:
            await disconnect_sth_devices(unit.system)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Cannot disconnect sensor device of unit <%s>: %s",
                unit.key,
                error,
            )

    await asyncio.gather(*(disconnect(unit) for unit in units))


async def _connect_units(
    instructions: MeasurementInstructions, units: list[Unit]
) -> None:
    """Connect the sensor devices of all units (all-or-nothing)

    A sensor device that is connected to its unit already is not connected
    again.
    """

    addresses = instructions.unit_mac_addresses or {}
    missing = [unit.key for unit in units if unit.key not in addresses]
    unknown = [key for key in addresses if key not in [u.key for u in units]]
    if missing or unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "`unit_mac_addresses` has to contain the MAC address of the "
                "sensor device of every unit. "
                + (f"Missing: {', '.join(missing)}. " if missing else "")
                + (f"Unknown units: {', '.join(unknown)}." if unknown else "")
            ),
        )

    async def connect(unit: Unit) -> None:
        system = unit.system
        try:
            requested = EUI(addresses[unit.key])
        except AddrFormatError:
            requested = None
        already_connected = (
            system.sensor_node_attributes is not None
            and requested is not None
            and system.sensor_node_attributes.mac_address == requested
        )
        try:
            if system.sensor_node_attributes is not None and not already_connected:
                await _run_execute_step(
                    "connect", disconnect_sth_devices(system)
                )
            if not already_connected:
                await _run_execute_step(
                    "connect",
                    connect_sth_device_by_mac(system, addresses[unit.key]),
                )
        except HTTPException as error:
            if isinstance(error.detail, str):
                error.detail = f"Unit {unit.key}: {error.detail}"
            raise

    results = await asyncio.gather(
        *(connect(unit) for unit in units), return_exceptions=True
    )
    failures = [result for result in results if isinstance(result, Exception)]
    if failures:
        await _disconnect_units(units)
        raise failures[0]


@router.get(
    "/preflight",
    responses={503: HTTP_503_CAN_NOT_CONNECTED_SPEC},
)
async def preflight(
    measurement_state: MeasurementState = Depends(get_measurement_state),
) -> dict:
    """Check if all units are ready for a measurement

    Without multi STU support the only unit is checked. Nothing is changed:
    The configuration of the measurement is not written to the sensor
    devices. The check made by `/start` also does that and checks that the
    configuration was applied.

    The answer lists every unit with its problems (if there are any), its
    sensor device, the connection quality and the load of its CAN bus.
    """

    units = ICOsystemSingleton.units()
    if not units:
        raise HTTP_503_CAN_NOT_CONNECTED_EXCEPTION
    if measurement_state.running:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION

    disabled = ResolvedChannel(channel_number=0, sensor=None)
    checks = await check_units(
        units,
        _instructions_without_channels(),
        ResolvedMeasurementChannels(
            first=disabled, second=disabled, third=disabled
        ),
        configure=False,
    )
    return describe_checks(checks)


# pylint: disable=duplicate-code
def _instructions_without_channels() -> MeasurementInstructions:
    """Get instructions of a measurement without channels (for the check)"""

    disabled = MeasurementInstructionChannel(sensor_id=None)
    return MeasurementInstructions(
        name=None,
        mac_address="",
        time=None,
        first=disabled,
        second=disabled,
        third=disabled,
        ift_requested=False,
        ift_channel="",
        ift_window_width=50,
    )


# pylint: enable=duplicate-code


@router.post(
    "/start",
    response_model=ControlResponse,
    responses={503: HTTP_503_CAN_NOT_CONNECTED_SPEC},
)
async def start_measurement(
    instructions: MeasurementInstructions,
    system: ICOsystem = Depends(get_system),
    measurement_state: MeasurementState = Depends(get_measurement_state),
    general_messenger=Depends(get_messenger),
):
    """Start measurement

    With multi STU support all units measure (see `GET /measurement/preflight`
    and `unit_mac_addresses`). If one unit is not ready, nothing is started.
    """

    if _uses_several_units():
        return await _start_group_measurement(
            instructions, measurement_state, general_messenger
        )

    resolved_channels = resolve_measurement_channels(instructions)

    try:
        await measurement_preparations(system, instructions, resolved_channels)
    except UnsupportedFeatureException as exc:
        raise HTTP_400_UNSUPPOERTED_FEATURE_EXCEPTION from exc
    except IncorrectStateError as exc:
        raise HTTP_400_INCORRECT_STATE_EXCEPTION from exc
    except NoResponseError as exc:
        await ICOsystemSingleton.refresh_system_stu_connected(
            system, False
        )
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
        await ICOsystemSingleton.refresh_stu_connected(False)
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_502_BAD_GATEWAY, str(exc)
        ) from exc
    except (ValueError, AddrFormatError) as exc:
        raise HTTP_EXECUTE_STEP_FAILED_EXCEPTION(
            step, status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
        ) from exc


@router.post(
    "/execute",
    response_model=ControlResponse,
    responses={503: HTTP_503_CAN_NOT_CONNECTED_SPEC},
)
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

    if _uses_several_units():
        # Every unit connects the sensor device it has an address for
        await _connect_units(instructions, ICOsystemSingleton.units())
        return await _start_group_measurement(
            instructions,
            measurement_state,
            general_messenger,
            disconnect_on_failure=True,
        )

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

"""Measure with all units at the same time

With multi STU support a measurement uses all units (a CAN network with its
STU and sensor device each). The data of all units is stored in one ICOschema
bundle: The data of every unit is a *source* of the file.

Every unit streams on its own. Their clocks are not synchronized, so every
source has its own start time (the time of its first message, taken from the
timestamp of the message) and timestamps in microseconds relative to it. A
client calculates the offset between two sources with their start times, see
:class:`icoapi.models.models.SourceInfo`.

The measurement is stopped as a whole: If the stream of one unit fails, the
streams of the other units are stopped, too. What was recorded until then
stays in the file, which is closed correctly.
"""

# The handling of failed measurements is the one of single measurements
# pylint: disable=duplicate-code

# -- Imports ------------------------------------------------------------------

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
from time import monotonic

import numpy as np
from icostate import ADCConfiguration, ICOsystem
from icotronic.can.sensor import SensorConfiguration
from icotronic.can.streaming import (
    StreamingConfiguration,
    StreamingTimeoutError,
)

from icoapi.models.event_bus import Channel
from icoapi.models.globals import (
    GeneralMessenger,
    MeasurementState,
    Unit,
)
from icoapi.models.models import (
    MeasurementInstructions,
    MetadataPrefix,
    ResolvedMeasurementChannels,
    SourcedDataValueModel,
)
from icoapi.scripts.bundle import CollectedMetadata, source_name
from icoapi.scripts.data_handling import MeasurementSensorInfo
from icoapi.scripts.file_handling import get_measurement_dir
from icoapi.scripts.measurement import (
    mark_measurement_stopped,
    notify_clients_of_measurement_error,
    publish_recording_event,
    write_metadata,
)
from icoapi.scripts.live_stream import (
    flush_clients,
    live_demand,
    send_to_clients,
)
from icoapi.scripts.preflight import UnitCheck
from icoapi.scripts.recording import SourceRecorder, create_source_spec
from icoapi.scripts.sth_scripts import disconnect_sth_devices
from icoapi.scripts.unit_instructions import UnitSetup
from icoapi.scripts.writer_thread import ThreadedBundleWriter, WriterError

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

BATCH_MESSAGES = 128
"""Number of messages of a unit that are converted and stored together"""

# -- Classes ------------------------------------------------------------------


@dataclass
class UnitRun:  # pylint: disable=too-many-instance-attributes
    """Everything the measurement of one unit needs"""

    unit: Unit
    check: UnitCheck
    instructions: MeasurementInstructions
    """The instructions for this unit"""
    resolved_channels: ResolvedMeasurementChannels
    name: str
    """Name of the source of the unit"""
    adc: ADCConfiguration
    streaming_configuration: StreamingConfiguration
    sensor_info: MeasurementSensorInfo
    recorder: SourceRecorder | None = None
    first_timestamp: float | None = None
    """Timestamp of the first message (in seconds since the epoch)"""
    overall_dataloss: float = 0.0
    pending_counters: list[int] = field(default_factory=list)
    """Counters of the messages that are not stored yet"""
    pending_timestamps: list[float] = field(default_factory=list)
    pending_values: list[list[float]] = field(default_factory=list)
    conversion: tuple[np.ndarray, np.ndarray, list[str]] | None = None
    """Factors and offsets of the values of a message (see `_conversion`)"""

    @property
    def system(self) -> ICOsystem:
        """The system of the unit"""

        return self.unit.system


# -- Functions ----------------------------------------------------------------


def unique_source_names(names: list[str | None]) -> list[str]:
    """Get a valid and unique name for every source

    Args:

        names:
            The (preferred) names, e.g. the names of the sensor devices

    Returns:

        Names that can be used for the sources of a bundle. If a name is used
        more than once, a number is added to all but the first.

    """

    result: list[str] = []
    for name in names:
        candidate = base = source_name(name)
        number = 1
        while candidate in result:
            number += 1
            candidate = f"{base}_{number}"
        result.append(candidate)
    return result


async def _send_to_clients(
    measurement_state: MeasurementState, message: list[dict]
) -> None:
    """Send points to the clients of the measurement (see ``live_stream``)"""

    await send_to_clients(measurement_state, message)


async def _send_dataloss(
    measurement_state: MeasurementState, name: str, dataloss: float
) -> None:
    """Send the data loss of a source to the clients of the measurement"""

    await _send_to_clients(
        measurement_state,
        [
            SourcedDataValueModel(
                source=name,
                first=None,
                second=None,
                third=None,
                ift=None,
                counter=None,
                timestamp=None,
                dataloss=dataloss,
            ).model_dump()
        ],
    )


def _conversion(
    run: UnitRun, values_per_message: int
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Get how the raw values of a message are converted

    Returns:

        The factor and the offset (physical value = raw value * factor +
        offset) of every value of a message and the names of the slots the
        values belong to (for the live data)

    """

    configuration = run.streaming_configuration
    voltage_scaling = run.sensor_info.voltage_scaling
    slots = [
        slot
        for slot in ("first", "second", "third")
        if getattr(configuration, slot)
    ]
    sensors = {
        slot: getattr(run.resolved_channels, slot).sensor for slot in slots
    }
    if len(slots) == 1:
        # One enabled channel: Every value of a message belongs to it
        names = ["first"]
        slots = slots * values_per_message
    else:
        names = list(slots)
    factors = np.array([
        sensors[slot].scaling_factor * voltage_scaling for slot in slots
    ])
    offsets = np.array([sensors[slot].offset for slot in slots])
    return factors, offsets, names


# pylint: disable-next=too-many-locals
async def _process_pending(
    run: UnitRun, measurement_state: MeasurementState
) -> None:
    """Convert, store and send the messages received since the last call

    Doing this for many messages at once (with numpy) is much cheaper than
    doing it for every message.
    """

    if not run.pending_counters:
        return
    assert run.recorder is not None

    counters = np.array(run.pending_counters, dtype=np.int64)
    timestamps = np.array(run.pending_timestamps, dtype=np.float64)
    raw = np.array(run.pending_values, dtype=np.float64)
    run.pending_counters = []
    run.pending_timestamps = []
    run.pending_values = []

    if run.conversion is None or run.conversion[0].shape[0] != raw.shape[1]:
        run.conversion = _conversion(run, raw.shape[1])
    factors, offsets, names = run.conversion
    converted = raw * factors + offsets

    run.recorder.add_streaming_batch(counters, timestamps, converted)

    # The live data is a display: Nobody needs it without clients and
    # clients only want some of the points (see `live_stream`)
    demand = live_demand(measurement_state)
    if demand == 0:
        return
    stride = 1
    if demand is not None:
        messages_per_second = run.adc.sample_rate() / raw.shape[1]
        stride = max(1, int(messages_per_second // demand))

    live_counters = counters[::stride].tolist()
    columns: dict[str, list] = {
        slot: [None] * len(live_counters)
        for slot in ("first", "second", "third")
    }
    for index, name in enumerate(names):
        columns[name] = converted[::stride, index].tolist()
    rows = [
        {
            "timestamp": timestamp,
            "first": first,
            "second": second,
            "third": third,
            "ift": None,
            "counter": counter,
            "dataloss": None,
            "source": run.name,
        }
        for timestamp, first, second, third, counter in zip(
            timestamps[::stride].tolist(),
            columns["first"],
            columns["second"],
            columns["third"],
            live_counters,
        )
    ]
    await _send_to_clients(measurement_state, rows)


async def _stream_unit(
    run: UnitRun,
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
) -> None:
    """Receive and store the data of one unit until the measurement ends"""

    assert run.recorder is not None
    dataloss_sent_time = monotonic()

    async with run.system.sensor_node.open_data_stream(
        run.streaming_configuration
    ) as stream:
        logger.info("Opened measurement stream of unit <%s>", run.unit.key)

        try:
            async for data, _ in stream:
                if run.first_timestamp is None:
                    # The timestamps of the messages are times of this
                    # computer (see `AsyncStreamBuffer`), so the start times
                    # of the units can be compared
                    run.first_timestamp = data.timestamp
                    run.recorder.set_start_time(
                        datetime.fromtimestamp(data.timestamp).isoformat()
                    )
                timestamp = data.timestamp - run.first_timestamp

                # Only collect here, since this runs for every message
                run.pending_counters.append(data.counter)
                run.pending_timestamps.append(timestamp)
                run.pending_values.append(data.values)
                if len(run.pending_counters) >= BATCH_MESSAGES:
                    await _process_pending(run, measurement_state)

                current_time = monotonic()
                if current_time >= dataloss_sent_time + 1:
                    await _send_dataloss(
                        measurement_state, run.name, stream.dataloss()
                    )
                    dataloss_sent_time = current_time
                    stream.reset_stats()

                if (
                    instructions.time is not None
                    and timestamp >= instructions.time
                ):
                    logger.info(
                        "Timeout of unit <%s> reached at <%ss>",
                        run.unit.key,
                        timestamp,
                    )
                    break

                if measurement_state.stop_flag:
                    logger.info(
                        "Stop flag set - stopping unit <%s>", run.unit.key
                    )
                    break
        finally:
            # Store what was received until now, even if the stream failed
            await _process_pending(run, measurement_state)

    run.overall_dataloss = run.recorder.dataloss()


async def _stream_unit_guarded(
    run: UnitRun,
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
    failed_units: list[str],
) -> None:
    """Stream a unit and remember if its stream is the one that failed

    Problems with the file (a full disk) are not the fault of a unit.
    """

    try:
        await _stream_unit(run, instructions, measurement_state)
    except WriterError:
        raise
    except Exception:
        failed_units.append(run.unit.key)
        raise


async def _run_all(tasks: list["asyncio.Task[None]"]) -> None:
    """Wait for all tasks. Stop all of them, if one fails.

    Raises:

        The exception of the first failed task

    """

    try:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    # Look at the exceptions of all finished tasks: One that nobody retrieves
    # is reported later, at a random place
    errors = [
        error
        for task in done
        if not task.cancelled() and (error := task.exception()) is not None
    ]
    if errors:
        raise errors[0]


async def _create_runs(
    setups: list[UnitSetup], checks: list[UnitCheck]
) -> list[UnitRun]:
    """Create the data every unit needs for the measurement"""

    names = unique_source_names([check.tool_name for check in checks])
    runs = []
    for setup, check, name in zip(setups, checks, names):
        assert setup.instructions.adc is not None
        resolved = setup.resolved_channels
        runs.append(
            UnitRun(
                unit=setup.unit,
                check=check,
                instructions=setup.instructions,
                resolved_channels=resolved,
                name=name,
                adc=await setup.unit.system.get_adc_configuration(),
                streaming_configuration=SensorConfiguration(
                    resolved.first.channel_number,
                    resolved.second.channel_number,
                    resolved.third.channel_number,
                ).streaming_configuration(),
                sensor_info=MeasurementSensorInfo(
                    resolved, setup.instructions.adc
                ),
            )
        )
    return runs


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-branches,too-many-positional-arguments
async def run_group_measurement(
    setups: list[UnitSetup],
    checks: list[UnitCheck],
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
    general_messenger: GeneralMessenger,
) -> None:
    """Run a measurement with all units

    Args:

        setups:
            What every unit does (its own instructions and sensors). The
            units are ready, see :mod:`icoapi.scripts.preflight`.

        checks:
            The result of the check of every unit

        instructions:
            The instructions of the measurement (the ones that are the same
            for all units, like the time)

        measurement_state:
            The state of the measurement

        general_messenger:
            The messenger that is used to publish the state and events

    """

    measurement_file_path = Path(
        f"{get_measurement_dir()}/{measurement_state.name}.hdf5"
    )
    failed_units: list[str] = []
    try:
        runs = await _create_runs(setups, checks)

        collected = CollectedMetadata()
        if instructions.meta:
            write_metadata(MetadataPrefix.PRE, instructions.meta, collected)
        specs = [
            create_source_spec(
                name=run.name,
                adc=run.adc,
                system=run.system,
                tool_name=run.check.tool_name,
                start_supply_voltage=run.check.supply_voltage,
                resolved_channels=run.resolved_channels,
                stu_mac_address=run.check.stu_mac_address or "",
                pre_metadata=collected.attributes.get("pre_metadata"),
            )
            for run in runs
        ]

        writer = ThreadedBundleWriter(str(measurement_file_path), specs)
        try:
            logger.info(
                "Opened measurement file: <%s> for writing (%s sources)",
                measurement_file_path,
                len(runs),
            )
            for picture_name, images in collected.pictures.items():
                writer.add_picture(picture_name, images)
            # Problems with the file show up now, not with the first data
            writer.flush()
            for run in runs:
                run.recorder = SourceRecorder(
                    writer[run.name], run.streaming_configuration
                )

            await _run_all([
                asyncio.create_task(
                    _stream_unit_guarded(
                        run, instructions, measurement_state, failed_units
                    )
                )
                for run in runs
            ])
            for run in runs:
                await _send_dataloss(
                    measurement_state, run.name, run.overall_dataloss
                )
            await flush_clients(measurement_state)
        finally:
            writer.close()

        if instructions.disconnect_after_measurement:
            for run in runs:
                await disconnect_sth_devices(run.system)

        # The measurement file is closed at this point
        await mark_measurement_stopped(measurement_state, general_messenger)
        await publish_recording_event(
            general_messenger,
            Channel.RECORDING_FINISHED,
            measurement_file_path,
            units=measurement_state.units,
        )

    except StreamingTimeoutError as error:
        logger.debug("Stream timeout error")
        await _fail(
            error,
            measurement_state,
            general_messenger,
            measurement_file_path,
            failed_units[0] if failed_units else None,
        )
    except asyncio.CancelledError as error:
        logger.debug("Measurement cancelled")
        await publish_recording_event(
            general_messenger,
            Channel.RECORDING_FAILED,
            measurement_file_path,
            error,
            units=measurement_state.units,
        )
        raise
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.exception("Measurement stopped due to an unexpected error")
        await _fail(
            error,
            measurement_state,
            general_messenger,
            measurement_file_path,
            failed_units[0] if failed_units else None,
        )
    finally:
        clients = len(measurement_state.clients)
        for client in measurement_state.clients:
            await client.close()
        logger.info("Ended measurement and cleared %s clients", clients)
        await measurement_state.reset()


async def _fail(
    error: BaseException,
    measurement_state: MeasurementState,
    general_messenger: GeneralMessenger,
    measurement_file_path: Path,
    failed_unit: str | None = None,
) -> None:
    """Report a failed measurement"""

    await notify_clients_of_measurement_error(measurement_state, error)
    await mark_measurement_stopped(measurement_state, general_messenger)
    await publish_recording_event(
        general_messenger,
        Channel.RECORDING_FAILED,
        measurement_file_path,
        error,
        units=measurement_state.units,
        failed_unit=failed_unit,
    )

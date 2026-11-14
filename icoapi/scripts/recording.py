"""Store the data of a measurement in a file

A running measurement writes to a :class:`RecordingFile`. There are two
implementations:

- :class:`LegacyRecordingFile` uses the ``Storage`` class of ICOtronic (this
  is what the API has always done).
- :class:`BundleRecordingFile` writes an ICOschema bundle (see
  :mod:`icoapi.scripts.bundle`).

:func:`open_recording_file` chooses one: the bundle format is only used with
multi STU support (see :mod:`icoapi.scripts.features`).
"""

# -- Imports ------------------------------------------------------------------

from abc import ABC, abstractmethod
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
import json
import logging
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from icoschema.v2 import (
    ChannelMetadata,
    LinearConversion,
    Sensor as SchemaSensor,
    SourceSpec,
)
from icostate import ADCConfiguration, ICOsystem
from icotronic.can.dataloss import MessageStats
from icotronic.can.streaming import StreamingConfiguration, StreamingData
from icotronic.measurement.storage import Storage, StorageData

from icoapi.models.globals import MeasurementState
from icoapi.models.models import (
    MeasurementInstructions,
    MetadataPrefix,
    ResolvedMeasurementChannels,
)
from icoapi.scripts.bundle import (
    ADDITIONAL_DATA_KEY,
    SLOTS,
    CollectedMetadata,
    source_name,
)
from icoapi.scripts.data_handling import add_sensor_data_to_storage
from icoapi.scripts.features import multi_stu_support
from icoapi.scripts.simulation import SimulatedICOsystem
from icoapi.scripts.writer_thread import ThreadedBundleWriter, ThreadedSource

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

# -- Classes ------------------------------------------------------------------


class RecordingFile(ABC):
    """A file that stores the data of a measurement

    Use it as context manager: The file is closed when the block ends.

    Args:

        path:
            The path of the measurement file

        streaming_configuration:
            The channels that are part of the measurement

    """

    def __init__(
        self, path: Path, streaming_configuration: StreamingConfiguration
    ) -> None:
        self.path = path
        self.streaming_configuration = streaming_configuration

    @abstractmethod
    def __enter__(self) -> Self:
        """Create the file"""

    @abstractmethod
    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the file"""

    # pylint: disable=too-many-arguments

    @abstractmethod
    def start(
        self,
        *,
        adc: ADCConfiguration,
        measurement_state: MeasurementState,
        system: ICOsystem,
        instructions: MeasurementInstructions,
        resolved_channels: ResolvedMeasurementChannels,
        stu_mac_address: str,
    ) -> None:
        """Store everything that is known before the first data arrives

        Args:

            adc:
                The ADC configuration that is used for the measurement

            measurement_state:
                The state of the measurement

            system:
                The system the data comes from

            instructions:
                The measurement instructions of the client

            resolved_channels:
                The sensors of the channels of the measurement

            stu_mac_address:
                The MAC address of the STU

        """

    # pylint: enable=too-many-arguments

    @abstractmethod
    def add_sensors(
        self, resolved_channels: ResolvedMeasurementChannels
    ) -> None:
        """Store the sensors of the channels (see :meth:`start`)"""

    @abstractmethod
    def add_streaming_data(self, data: StreamingData) -> None:
        """Store streaming data (already converted into the unit of sensor)"""

    @abstractmethod
    def dataloss(self) -> float:
        """Get the amount of lost messages (between 0 and 1)"""


class LegacyRecordingFile(RecordingFile):
    """Store measurement data using ``Storage`` from ICOtronic"""

    def __init__(
        self, path: Path, streaming_configuration: StreamingConfiguration
    ) -> None:
        super().__init__(path, streaming_configuration)
        self._context = Storage(path, streaming_configuration)
        self._storage: StorageData | None = None

    def __enter__(self) -> Self:
        self._storage = self._context.__enter__()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._context.__exit__(exception_type, exception_value, traceback)

    @property
    def storage(self) -> StorageData:
        """The ``Storage`` object of the file"""

        assert self._storage is not None
        return self._storage

    def start(  # pylint: disable=too-many-arguments
        self,
        *,
        adc: ADCConfiguration,
        measurement_state: MeasurementState,
        system: ICOsystem,
        instructions: MeasurementInstructions,
        resolved_channels: ResolvedMeasurementChannels,
        stu_mac_address: str,
    ) -> None:
        # Avoid circular import
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from icoapi.scripts.measurement import write_metadata

        storage = self.storage
        storage["conversion"] = "true"

        # Sourced from `adc` (read back from the device above), not
        # `instructions.adc` - `adc` reflects what was actually applied,
        # including defaults for any field the client left unset, which
        # `instructions.adc`'s own fields may not (they're Optional).
        storage["adc_prescaler"] = f"{adc.prescaler}"
        storage["adc_acquisition_time"] = f"{adc.acquisition_time}"
        storage["adc_oversampling_rate"] = f"{adc.oversampling_rate}"
        storage["adc_reference_voltage"] = f"{adc.reference_voltage}"

        if measurement_state.start_supply_voltage is not None:
            storage["start_supply_voltage"] = (
                f"{measurement_state.start_supply_voltage}"
            )

        # Device identity: which physical STH this data came from, and
        # which STU it was connected through. `sensor_node_attributes` is
        # set on connect and only cleared on disconnect, so it is
        # guaranteed present here - `run_measurement` only ever runs
        # while `SENSOR_NODE_CONNECTED`.
        assert system.sensor_node_attributes is not None
        storage["sth_mac_address"] = (
            system.sensor_node_attributes.mac_address.format()
        )
        storage["tool_name"] = measurement_state.tool_name or ""
        if isinstance(system, SimulatedICOsystem):
            # Simulated data must never be mistaken for a real measurement
            storage["simulated"] = "true"
        storage["stu_mac_address"] = stu_mac_address

        if instructions.meta:
            write_metadata(MetadataPrefix.PRE, instructions.meta, storage)

    def add_sensors(
        self, resolved_channels: ResolvedMeasurementChannels
    ) -> None:
        add_sensor_data_to_storage(
            self.storage,
            [
                resolved_channels.first,
                resolved_channels.second,
                resolved_channels.third,
            ],
        )

    def add_streaming_data(self, data: StreamingData) -> None:
        self.storage.add_streaming_data(data)

    def dataloss(self) -> float:
        return self.storage.dataloss()


class SourceRecorder:
    """Store the data of one source of a bundle

    Args:

        source:
            The writer of the source

        streaming_configuration:
            The channels of the source

    """

    def __init__(
        self,
        source: ThreadedSource,
        streaming_configuration: StreamingConfiguration,
    ) -> None:
        self._source = source
        self._single_channel = len(streaming_configuration.axes()) == 1
        self._stats = MessageStats()
        self._last_counter: int | None = None

    def set_start_time(self, start_time: str) -> None:
        """Set the time of the first message (ISO 8601, without timezone)"""

        self._source.update(start_time=start_time)

    def add_streaming_data(self, data: StreamingData) -> None:
        """Store streaming data

        The timestamp of the data is the time (in seconds) since the start of
        the measurement.
        """

        counter = data.counter
        if self._last_counter is None:
            self._stats.retrieved = 1
        elif counter != self._last_counter:
            self._stats.retrieved += 1
            self._stats.lost += (counter - self._last_counter) % 256 - 1
        self._last_counter = counter

        # Microseconds since the start of the measurement
        timestamp = int(round(data.timestamp * 1_000_000))
        if self._single_channel:
            # One enabled channel: Every message contains three values (that
            # share counter and timestamp) of that channel
            for value in data.values:
                self._source.append_row(timestamp, [value], counter)
        else:
            self._source.append_row(timestamp, data.values, counter)

    def dataloss(self) -> float:
        """Get the amount of lost messages (between 0 and 1)"""

        return self._stats.dataloss()


# pylint: disable-next=too-many-arguments,too-many-locals
def create_source_spec(
    *,
    name: str,
    adc: ADCConfiguration,
    system: ICOsystem,
    tool_name: str | None,
    start_supply_voltage: float | None,
    resolved_channels: ResolvedMeasurementChannels,
    stu_mac_address: str,
    pre_metadata: str | None,
) -> SourceSpec:
    """Describe the source of a bundle that stores the data of a measurement

    Args:

        name:
            The name of the source

        adc:
            The ADC configuration that is used for the measurement

        system:
            The system the data comes from

        tool_name:
            The name of the sensor device

        start_supply_voltage:
            The supply voltage of the sensor device at the start

        resolved_channels:
            The sensors of the channels of the measurement

        stu_mac_address:
            The MAC address of the STU

        pre_metadata:
            Metadata (JSON) of the measurement

    Returns:

        The description of the source, with everything that is known before
        the first data arrives

    """

    assert system.sensor_node_attributes is not None

    slots = [
        slot
        for slot in SLOTS
        if getattr(resolved_channels, slot).channel_number != 0
    ]
    channels: list[ChannelMetadata] = []
    sensors: list[dict[str, Any]] = []
    for slot in slots:
        resolved = getattr(resolved_channels, slot)
        sensor = resolved.sensor
        assert sensor is not None
        channels.append(
            ChannelMetadata(
                sensor=SchemaSensor(
                    sensor_id=sensor.sensor_id,
                    sensor_type=sensor.sensor_type,
                    name=sensor.name,
                    unit=sensor.unit,
                    dimension=sensor.dimension,
                ),
                # The values are converted before they are stored: The
                # conversion describes what was done to the voltage
                conversion=LinearConversion(
                    gain=sensor.scaling_factor, offset=sensor.offset
                ),
            )
        )
        sensors.append({
            **sensor.model_dump(),
            "channel_number": resolved.channel_number,
        })

    return SourceSpec(
        name=name,
        channels=channels,
        stu_mac=stu_mac_address,
        sth_mac=system.sensor_node_attributes.mac_address.format(),
        adc_reference_voltage=adc.reference_voltage,
        adc_prescaler=adc.prescaler,
        adc_acquisition_time=adc.acquisition_time,
        adc_oversample_rate=adc.oversampling_rate,
        pre_metadata=pre_metadata,
        additional_data=json.dumps({
            ADDITIONAL_DATA_KEY: {
                "version": _api_version(),
                "slots": slots,
                "sensors": sensors,
                "tool_name": tool_name or "",
                "start_supply_voltage": start_supply_voltage,
                "simulated": (
                    "true" if isinstance(system, SimulatedICOsystem) else None
                ),
            }
        }),
    )


class BundleRecordingFile(RecordingFile):
    """Store measurement data as ICOschema bundle

    The measurement is the only source of the bundle. The values are stored
    as they are in the old format: converted into the unit of the sensor. The
    conversion that was applied (volt to unit of the sensor) is part of the
    file. (Measurements of several units are stored by
    :mod:`icoapi.scripts.group_measurement`.)
    """

    def __init__(
        self, path: Path, streaming_configuration: StreamingConfiguration
    ) -> None:
        super().__init__(path, streaming_configuration)
        self._writer: ThreadedBundleWriter | None = None
        self._recorder: SourceRecorder | None = None
        self._first = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._writer is not None:
            self._writer.close()

    def start(  # pylint: disable=too-many-arguments
        self,
        *,
        adc: ADCConfiguration,
        measurement_state: MeasurementState,
        system: ICOsystem,
        instructions: MeasurementInstructions,
        resolved_channels: ResolvedMeasurementChannels,
        stu_mac_address: str,
    ) -> None:
        # Avoid circular import
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from icoapi.scripts.measurement import write_metadata

        collected = CollectedMetadata()
        if instructions.meta:
            write_metadata(MetadataPrefix.PRE, instructions.meta, collected)

        name = source_name(measurement_state.tool_name)
        spec = create_source_spec(
            name=name,
            adc=adc,
            system=system,
            tool_name=measurement_state.tool_name,
            start_supply_voltage=measurement_state.start_supply_voltage,
            resolved_channels=resolved_channels,
            stu_mac_address=stu_mac_address,
            pre_metadata=collected.attributes.get("pre_metadata"),
        )
        self._writer = ThreadedBundleWriter(str(self.path), [spec])
        self._recorder = SourceRecorder(
            self._writer[name], self.streaming_configuration
        )
        for picture_name, images in collected.pictures.items():
            self._writer.add_picture(picture_name, images)
        # Problems with the file show up now, not with the first data
        self._writer.flush()

    def add_sensors(
        self, resolved_channels: ResolvedMeasurementChannels
    ) -> None:
        """The sensors are stored when the file is created"""

    def add_streaming_data(self, data: StreamingData) -> None:
        assert self._recorder is not None

        if self._first:
            self._first = False
            # Same as in the old format: The time of the first message
            self._recorder.set_start_time(datetime.now().isoformat())
        self._recorder.add_streaming_data(data)

    def dataloss(self) -> float:
        assert self._recorder is not None
        return self._recorder.dataloss()


# -- Functions ----------------------------------------------------------------


def _api_version() -> str | None:
    """Get the version of the API (if it is installed)"""

    try:
        return version("icoapi")
    except PackageNotFoundError:
        return None


def open_recording_file(
    path: Path, streaming_configuration: StreamingConfiguration
) -> RecordingFile:
    """Create the file that stores the data of a measurement

    Args:

        path:
            The path of the measurement file

        streaming_configuration:
            The channels that are part of the measurement

    Returns:

        A recording file for the bundle format, if multi STU support is
        switched on, and a recording file for the old format otherwise.

    """

    recording_file_class = (
        BundleRecordingFile if multi_stu_support() else LegacyRecordingFile
    )
    return recording_file_class(path, streaming_configuration)

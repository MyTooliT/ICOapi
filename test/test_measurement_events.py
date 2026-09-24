"""Tests for the events published about finished measurements

The measurement task is run with a fake sensor node, so no hardware is
required.
"""

# -- Imports ------------------------------------------------------------------

import asyncio
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any, AsyncIterator, cast

from icostate import ICOsystem
from icotronic.can.streaming import StreamingData, StreamingTimeoutError
from icotronic.measurement.storage import StorageException
from netaddr import EUI
from pytest import MonkeyPatch, fixture, mark
from starlette.websockets import WebSocketDisconnect

from icoapi.api import app
from icoapi.models.event_bus import Channel
from icoapi.models.globals import GeneralMessenger, MeasurementState
from icoapi.models.models import (
    ADCValues,
    MeasurementInstructionChannel,
    MeasurementInstructions,
    ResolvedChannel,
    ResolvedMeasurementChannels,
    Sensor,
)
from icoapi.scripts import measurement
from icoapi.scripts.file_handling import API_PREFIX, get_measurement_dir
from icoapi.scripts.measurement import (
    create_recording_payload,
    open_metadata_storage,
    run_measurement,
)

# -- Classes --------------------------------------------------------------------

NAME = "Test Measurement__2026-01-01_00-00-00"


class FakeStream:
    """Stream of measurement data from a fake sensor node

    After sending all messages the stream ends the measurement with the given
    ``failure`` or, if there is a ``block`` event, waits until it is set.
    """

    def __init__(
        self,
        timestamps: list[float],
        failure: BaseException | None = None,
        block: asyncio.Event | None = None,
    ) -> None:
        self.timestamps = timestamps
        self.failure = failure
        self.block = block

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *_arguments: Any) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[tuple[StreamingData, None]]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[tuple[StreamingData, None]]:
        """Send all messages"""

        for counter, timestamp in enumerate(self.timestamps):
            yield (
                StreamingData(
                    counter=counter, timestamp=timestamp, values=[8000] * 3
                ),
                None,
            )
        if self.failure is not None:
            raise self.failure
        if self.block is not None:
            await self.block.wait()

    def dataloss(self) -> float:
        """Get the dataloss"""

        return 0.0

    def reset_stats(self) -> None:
        """Reset the dataloss statistics"""


class FakeSystem:
    """Minimal sensor node system for running a measurement"""

    def __init__(self, stream: FakeStream) -> None:
        mac_address = EUI("00-11-22-33-44-55")
        self.sensor_node_attributes = SimpleNamespace(mac_address=mac_address)
        self.sensor_node = SimpleNamespace(
            open_data_stream=lambda _configuration: stream
        )

    async def get_adc_configuration(self) -> SimpleNamespace:
        """Get ADC configuration"""

        return SimpleNamespace(
            prescaler=2,
            acquisition_time=8,
            oversampling_rate=64,
            reference_voltage=3.3,
            sample_rate=lambda: 1000.0,
        )

    async def get_stu_mac_address(self) -> EUI:
        """Get MAC address of the STU"""

        return EUI("00-00-00-00-00-01")


class RecordingMessenger:
    """Messenger that records what a measurement publishes

    It also checks whether the measurement file can be opened at the moment the
    measurement is reported as stopped.
    """

    def __init__(
        self, measurement_state: MeasurementState, file_path: Path
    ) -> None:
        self.measurement_state = measurement_state
        self.file_path = file_path
        self.events: list[tuple[Channel, dict[str, Any]]] = []
        self.file_usable_when_stopped: list[bool] = []

    async def push_messenger_update(self) -> None:
        """Check that the file is closed once the measurement has stopped"""

        # Opening a file that does not exist would create it
        if self.measurement_state.running or not self.file_path.exists():
            return
        try:
            with open_metadata_storage(self.file_path):
                pass
            self.file_usable_when_stopped.append(True)
        except Exception:  # pylint: disable=broad-exception-caught
            self.file_usable_when_stopped.append(False)

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Record published event"""

        self.events.append((channel, payload))


# pylint: disable-next=too-many-instance-attributes
class Measurement:
    """Run the measurement task with a fake sensor node"""

    def __init__(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(
            measurement, "get_measurement_dir", lambda: str(tmp_path)
        )
        self.file_path = tmp_path / f"{NAME}.hdf5"
        self.state = MeasurementState()
        self.state.name = NAME
        self.state.running = True
        self.messenger = RecordingMessenger(self.state, self.file_path)

    def run(
        self, stream: FakeStream, time: int | None = 1
    ) -> "asyncio.Task[None]":
        """Start measurement task"""

        disabled = MeasurementInstructionChannel(sensor_id=None)
        instructions = MeasurementInstructions(
            name=NAME,
            mac_address="00-11-22-33-44-55",
            time=time,
            first=MeasurementInstructionChannel(sensor_id="acc"),
            second=disabled,
            third=disabled,
            ift_requested=False,
            ift_channel="",
            ift_window_width=50,
            adc=ADCValues(
                prescaler=2,
                acquisition_time=8,
                oversampling_rate=64,
                reference_voltage=3.3,
            ),
            meta=None,
        )
        sensor = Sensor(
            name="Acceleration",
            sensor_type=None,
            sensor_id="acc",
            unit="g",
            dimension="Acceleration",
            phys_min=-100,
            phys_max=100,
            volt_min=0,
            volt_max=3.3,
        )
        channels = ResolvedMeasurementChannels(
            first=ResolvedChannel(channel_number=1, sensor=sensor),
            second=ResolvedChannel(channel_number=0, sensor=None),
            third=ResolvedChannel(channel_number=0, sensor=None),
        )

        return asyncio.create_task(
            run_measurement(
                cast(ICOsystem, FakeSystem(stream)),
                instructions,
                channels,
                self.state,
                cast(GeneralMessenger, self.messenger),
            )
        )

    @property
    def channels(self) -> list[Channel]:
        """Channels of the published events"""

        return [channel for channel, _payload in self.messenger.events]


@fixture(name="fake_measurement")
def fixture_fake_measurement(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> Measurement:
    """Measurement that runs with a fake sensor node"""

    return Measurement(tmp_path, monkeypatch)


# -- Tests --------------------------------------------------------------------


class TestRecordingPayload:
    """Tests for the payload of the events"""

    def test_file(self, tmp_path: Path) -> None:
        """The payload should describe the measurement file"""

        file_path = tmp_path / "Test Measurement__1.hdf5"
        file_path.write_bytes(b"x" * 1234)

        assert create_recording_payload(file_path) == {
            "name": "Test Measurement__1.hdf5",
            "size": 1234,
            "url": f"{API_PREFIX}/files/Test%20Measurement__1.hdf5",
        }

    def test_missing_file(self, tmp_path: Path) -> None:
        """Only the name is known if the file does not exist"""

        payload = create_recording_payload(tmp_path / "missing.hdf5")

        assert payload == {"name": "missing.hdf5", "size": None, "url": None}

    def test_error(self, tmp_path: Path) -> None:
        """The payload should contain the error if there is one"""

        file_path = tmp_path / "test.hdf5"
        file_path.write_bytes(b"x")

        payload = create_recording_payload(file_path, ValueError("Bad value"))

        assert payload["size"] == 1
        assert payload["error"] == {"type": "ValueError", "message": "Bad value"}

    def test_route_of_file(self, tmp_path: Path, client) -> None:
        """The route in the payload should download the file"""

        file_path = tmp_path / "Test Measurement__1.hdf5"
        file_path.write_bytes(b"data")
        app.dependency_overrides[get_measurement_dir] = lambda: str(tmp_path)

        try:
            route = create_recording_payload(file_path)["url"]
            # The test client already uses the prefix as part of its base URL
            response = client.get(route.removeprefix(f"{API_PREFIX}/"))
        finally:
            app.dependency_overrides.pop(get_measurement_dir, None)

        assert response.status_code == 200
        assert response.content == b"data"


class TestMeasurementEvents:
    """Test the events published by the measurement task"""

    async def test_timed_measurement_finished(
        self, fake_measurement: Measurement
    ) -> None:
        """A measurement that reaches its time should publish ``Finished``"""

        await fake_measurement.run(FakeStream([0.0, 0.5, 1.0]))

        assert fake_measurement.channels == [Channel.RECORDING_FINISHED]
        payload = fake_measurement.messenger.events[0][1]
        file_path = fake_measurement.file_path
        assert payload == {
            "name": file_path.name,
            "size": file_path.stat().st_size,
            "url": f"{API_PREFIX}/files/Test%20Measurement__2026-01-01_00-00-00.hdf5",
        }
        assert payload["size"] > 0

    async def test_stopped_measurement_finished(
        self, fake_measurement: Measurement
    ) -> None:
        """A measurement stopped by the user should publish ``Finished``"""

        fake_measurement.state.stop_flag = True

        await fake_measurement.run(FakeStream([0.0, 0.1, 0.2]), time=None)

        assert fake_measurement.channels == [Channel.RECORDING_FINISHED]

    async def test_file_is_closed_when_measurement_stops(
        self, fake_measurement: Measurement
    ) -> None:
        """The measurement is only reported as stopped after closing the file

        This makes it possible to add post metadata to the file right away.
        """

        await fake_measurement.run(FakeStream([0.0, 0.5, 1.0]))

        assert fake_measurement.messenger.file_usable_when_stopped == [True]
        assert not fake_measurement.state.running

    @mark.parametrize(
        "failure",
        [
            StreamingTimeoutError("No data"),
            RuntimeError("Unexpected"),
            WebSocketDisconnect(1006),
        ],
        ids=["timeout", "exception", "disconnect"],
    )
    async def test_failed_measurement(
        self, fake_measurement: Measurement, failure: BaseException
    ) -> None:
        """A measurement that stops with an error should publish ``Failed``"""

        await fake_measurement.run(FakeStream([0.0, 0.1], failure=failure))

        assert fake_measurement.channels == [Channel.RECORDING_FAILED]
        payload = fake_measurement.messenger.events[0][1]
        file_path = fake_measurement.file_path
        assert payload["name"] == file_path.name
        assert payload["size"] == file_path.stat().st_size
        assert payload["url"].endswith(".hdf5")
        assert payload["error"] == {
            "type": type(failure).__name__,
            "message": str(failure),
        }
        assert fake_measurement.messenger.file_usable_when_stopped == [True]

    async def test_cancelled_measurement_failed(
        self, fake_measurement: Measurement
    ) -> None:
        """A cancelled measurement should publish ``Failed``"""

        block = asyncio.Event()
        task = fake_measurement.run(FakeStream([0.0, 0.1], block=block))
        await asyncio.sleep(0.2)

        task.cancel()
        await asyncio.wait([task])

        assert task.cancelled()
        assert fake_measurement.channels == [Channel.RECORDING_FAILED]
        payload = fake_measurement.messenger.events[0][1]
        assert payload["error"]["type"] == "CancelledError"

    async def test_failure_without_file(
        self, fake_measurement: Measurement, monkeypatch: MonkeyPatch
    ) -> None:
        """Only the name is published if the file could not be created"""

        def storage(*_arguments: Any) -> None:
            raise StorageException("Unable to open file")

        monkeypatch.setattr(measurement, "Storage", storage)

        await fake_measurement.run(FakeStream([0.0]))

        assert fake_measurement.channels == [Channel.RECORDING_FAILED]
        payload = fake_measurement.messenger.events[0][1]
        assert payload == {
            "name": fake_measurement.file_path.name,
            "size": None,
            "url": None,
            "error": {
                "type": "StorageException",
                "message": "Unable to open file",
            },
        }


def wait_until(condition: Callable[[], bool], timeout: float = 30.0) -> bool:
    """Wait until a condition is true (or the timeout is reached)"""

    end = monotonic() + timeout
    while monotonic() < end:
        if condition():
            return True
        sleep(0.1)
    return condition()


class TestMeasurementEventsHardware:
    """Test the events published for measurements with a real sensor node"""

    @mark.hardware
    def test_finished_event(
        self,
        recording_event_bus,
        measurement_single_channel,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """A finished measurement should publish ``Finished`` with its file"""

        assert wait_until(
            lambda: not client.get(str(measurement_prefix)).json()["running"]
        )
        assert wait_until(lambda: recording_event_bus.events, timeout=10)
        # A failure after the measurement would show up shortly afterwards
        sleep(0.5)

        assert [
            channel for channel, _payload in recording_event_bus.events
        ] == [Channel.RECORDING_FINISHED]
        payload = recording_event_bus.events[0][1]
        name = payload["name"]
        try:
            assert name.startswith("Test Measurement__")
            assert name.endswith(".hdf5")
            file_path = Path(get_measurement_dir()) / name
            assert payload["size"] == file_path.stat().st_size > 0

            # The route in the event downloads the measurement file
            response = client.get(payload["url"].removeprefix(f"{API_PREFIX}/"))
            assert response.status_code == 200
            assert len(response.content) == payload["size"]
        finally:
            client.delete(f"files/{name}")

    @mark.hardware
    def test_stopped_measurement_finished_event(
        self,
        recording_event_bus,
        measurement_instructions_single_channel,
        measurement_prefix,
        client,
    ) -> None:
        """A measurement stopped by the user should publish ``Finished``"""

        start = f"{measurement_prefix}/start"
        stop = f"{measurement_prefix}/stop"

        # No time limit: The measurement only ends, when we stop it
        response = client.post(
            start, json={**measurement_instructions_single_channel, "time": None}
        )
        assert response.status_code == 200
        try:
            sleep(1)
            assert not recording_event_bus.events
        finally:
            assert client.post(stop).status_code == 200

        assert wait_until(lambda: recording_event_bus.events, timeout=10)
        sleep(0.5)

        assert [
            channel for channel, _payload in recording_event_bus.events
        ] == [Channel.RECORDING_FINISHED]
        payload = recording_event_bus.events[0][1]
        client.delete(f"files/{payload['name']}")
        assert payload["size"] > 0

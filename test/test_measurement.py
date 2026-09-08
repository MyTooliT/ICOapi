"""Tests for measurement endpoint"""

# -- Imports ------------------------------------------------------------------

from datetime import datetime
from logging import getLogger
from pathlib import Path
from time import time

from fastapi import HTTPException
from icostate import ADCConfiguration
from icotronic.can.streaming import StreamingConfiguration
from icotronic.measurement.storage import Storage
from pytest import mark, raises

import numpy as np

from icoapi.models.models import (
    MeasurementInstructionChannel,
    MeasurementInstructions,
    Metadata,
    MetadataPrefix,
    PCBSensorConfiguration,
    Sensor,
)
from icoapi.scripts.data_handling import (
    resolve_channel,
    resolve_measurement_channels,
)
from icoapi.scripts.measurement import write_image_array, write_metadata

# -- Functions ----------------------------------------------------------------


def disabled_channel() -> MeasurementInstructionChannel:
    """A disabled measurement channel instruction"""

    return MeasurementInstructionChannel(sensor_id=None)


def build_instructions(
    sensor_configuration: PCBSensorConfiguration | None = None,
    first_sensor_id: str | None = None,
) -> MeasurementInstructions:
    """Build minimal measurement instructions for validation unit tests"""

    return MeasurementInstructions(
        name=None,
        mac_address="00-11-22-33-44-55",
        time=3,
        first=MeasurementInstructionChannel(sensor_id=first_sensor_id),
        second=disabled_channel(),
        third=disabled_channel(),
        ift_requested=False,
        ift_channel="",
        ift_window_width=50,
        adc=None,
        meta=None,
        sensor_configuration=sensor_configuration,
    )


def get_measurement_websocket_endpoint(
    measurement_prefix,
    client,
) -> str:
    """Get the endpoint for the measurement WebSocket"""

    measurement_status = str(measurement_prefix)

    response = client.get(measurement_status)
    assert response.status_code == 200
    assert response.json()["running"] is True

    ws_url = str(client.base_url).replace("http", "ws")
    stream = f"{ws_url}{measurement_prefix}/stream"

    return stream


# -- Classes ------------------------------------------------------------------


class TestWriteMetadata:
    """Direct unit tests for the metadata writing helpers"""

    def test_write_image_array_overwrite(self, tmp_path: Path) -> None:
        """``write_image_array`` should overwrite an existing node in place

        Regression test: it used to try to remove the pre-existing array
        node from the wrong HDF5 path (``/acceleration``, a table with no
        children of its own) instead of ``/``, where ``create_array``
        actually places the node. That raised ``NoSuchNodeError`` instead
        of removing and replacing the array.
        """

        file_path = tmp_path / "image_array_overwrite.hdf5"

        with Storage(
            file_path, StreamingConfiguration(first=True)
        ) as storage:
            write_image_array(
                storage, "post__pictures", np.array([b"hello"]), True
            )
            write_image_array(
                storage, "post__pictures", np.array([b"world"]), True
            )

            picture_array = storage.hdf.get_node("/post__pictures")
            assert picture_array.read().tolist() == [b"world"]

    def test_write_metadata_with_picture_overwrite(
        self, tmp_path: Path
    ) -> None:
        """Writing a picture parameter twice via `write_metadata` should
        overwrite, not crash"""

        file_path = tmp_path / "picture_overwrite.hdf5"

        with Storage(
            file_path, StreamingConfiguration(first=True)
        ) as storage:
            write_metadata(
                MetadataPrefix.POST,
                Metadata(
                    version="1.0.0",
                    profile="milling",
                    parameters={"pictures": {"0": "aGVsbG8="}},
                ),
                storage,
            )
            write_metadata(
                MetadataPrefix.POST,
                Metadata(
                    version="1.0.0",
                    profile="milling",
                    parameters={"pictures": {"0": "d29ybGQ="}},
                ),
                storage,
            )

            picture_array = storage.hdf.get_node("/post__pictures")
            assert picture_array.read().tolist() == [b"d29ybGQ="]


class TestResolveMeasurementChannels:
    """Direct unit tests for `resolve_measurement_channels`"""

    def test_passes_when_not_required_and_absent(self, monkeypatch) -> None:
        """No inline config and no strictness requirement - resolves against
        the file's default configuration; every slot disabled"""

        monkeypatch.setenv("REQUIRE_INLINE_SENSOR_CONFIG", "0")
        resolved = resolve_measurement_channels(build_instructions())

        assert resolved.first.channel_number == 0
        assert resolved.first.sensor is None

    def test_rejects_when_required_and_absent(self, monkeypatch) -> None:
        """Strictness requires inline config; request has none"""

        monkeypatch.setenv("REQUIRE_INLINE_SENSOR_CONFIG", "1")
        with raises(HTTPException) as excinfo:
            resolve_measurement_channels(build_instructions())

        assert excinfo.value.status_code == 422
        assert "requires inline sensor configuration" in excinfo.value.detail

    def test_resolves_against_inline_configuration(self, monkeypatch) -> None:
        """Strictness requires inline config; request supplies one and its
        sensor_id resolves to the matching channel number"""

        monkeypatch.setenv("REQUIRE_INLINE_SENSOR_CONFIG", "1")

        sensor = Sensor(
            name="Test Sensor",
            sensor_type=None,
            sensor_id="test_sensor_01",
            unit="-",
            dimension="Test",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        )
        sensor_configuration = PCBSensorConfiguration(
            configuration_id="test-config",
            configuration_name="Test Config",
            channels={3: sensor},
        )

        resolved = resolve_measurement_channels(
            build_instructions(
                sensor_configuration=sensor_configuration,
                first_sensor_id="test_sensor_01",
            )
        )

        assert resolved.first.channel_number == 3
        assert resolved.first.sensor is sensor

    def test_rejects_unknown_sensor_id_regardless_of_strictness(
        self, monkeypatch
    ) -> None:
        """A sensor_id absent from the inline config is rejected even when
        REQUIRE_INLINE_SENSOR_CONFIG is off - the two checks are independent"""

        monkeypatch.setenv("REQUIRE_INLINE_SENSOR_CONFIG", "0")

        sensor_configuration = PCBSensorConfiguration(
            configuration_id="test-config",
            configuration_name="Test Config",
            channels={},
        )

        with raises(HTTPException) as excinfo:
            resolve_measurement_channels(
                build_instructions(
                    sensor_configuration=sensor_configuration,
                    first_sensor_id="does-not-exist",
                )
            )

        assert excinfo.value.status_code == 422
        assert "does-not-exist" in excinfo.value.detail


class TestResolveChannel:
    """Direct unit tests for `resolve_channel`"""

    def test_disabled_sensor_id_returns_disabled_channel(self) -> None:
        """`sensor_id is None` always means disabled, regardless of
        `channels`"""

        result = resolve_channel(None, {})

        assert result.channel_number == 0
        assert result.sensor is None

    def test_resolves_sensor_id_to_channel_number(self) -> None:
        """A matching sensor_id resolves to its channel number and Sensor"""

        sensor = Sensor(
            name="Test Sensor",
            sensor_type=None,
            sensor_id="test_sensor_01",
            unit="-",
            dimension="Test",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        )
        channels = {3: sensor}

        result = resolve_channel("test_sensor_01", channels)

        assert result.channel_number == 3
        assert result.sensor is sensor

    def test_unknown_sensor_id_raises(self) -> None:
        """A sensor_id matching nothing in `channels` is always a hard
        error - there is no independent channel_number left to fall back
        to routing, whether `channels` came from an inline request or from
        sensors.yaml"""

        with raises(HTTPException) as excinfo:
            resolve_channel("does-not-exist", {})

        assert excinfo.value.status_code == 422
        assert "does-not-exist" in excinfo.value.detail


class TestMeasurement:
    """Measurement endpoint test methods"""

    def test_measurement_status_disconnected(
        self, measurement_prefix, client
    ) -> None:
        """Test endpoint ``/`` in disconnected state"""

        measurement_status = measurement_prefix

        response = client.get(measurement_status)
        assert response.status_code == 200

        body = response.json()

        for key in (
            "instructions",
            "name",
            "running",
            "start_time",
            "tool_name",
            "start_supply_voltage",
        ):
            assert key in body

    @mark.hardware
    def test_measurement_status_measuring(
        self,
        measurement_prefix,
        test_sensor_node,
        measurement_single_channel,
        client,
    ) -> None:
        """Test endpoint ``/`` while measurement takes place"""

        measurement_status = measurement_prefix
        measurement_instructions_single_channel = measurement_single_channel

        response = client.get(measurement_status)
        assert response.status_code == 200

        body = response.json()

        assert body["instructions"] is not None
        instructions = body["instructions"]
        for key in measurement_instructions_single_channel:
            assert (
                instructions[key]
                == measurement_instructions_single_channel[key]
            )
        assert body["running"] is True
        assert body["name"].startswith(
            measurement_instructions_single_channel["name"]
        )
        assert body["tool_name"] == test_sensor_node["name"]

        assert isinstance(body["start_supply_voltage"], float)
        assert body["start_supply_voltage"] > 0

        assert isinstance(body["start_time"], str)
        start_time = body["start_time"]
        timestamp = datetime.fromisoformat(start_time).timestamp()
        current_timestamp = time()
        assert current_timestamp - 10 <= timestamp <= current_timestamp

    def test_measurement_start_unknown_sensor_id(
        self, measurement_prefix, client
    ) -> None:
        """`/start` should reject with 422 before any CAN traffic when a
        streaming slot's sensor_id isn't in the inline sensor
        configuration"""

        start = f"{measurement_prefix}/start"

        sensor = {
            "name": "Acceleration 100g",
            "sensor_type": "ADXL1001",
            "sensor_id": "acc100g_01",
            "unit": "g",
            "dimension": "Acceleration",
            "phys_min": -100.0,
            "phys_max": 100.0,
            "volt_min": 0.33,
            "volt_max": 2.97,
        }

        instructions = {
            "name": "Test Measurement",
            "mac_address": "00-11-22-33-44-55",
            "time": 3,
            "first": {"sensor_id": "does-not-exist"},
            "second": {"sensor_id": None},
            "third": {"sensor_id": None},
            "ift_requested": False,
            "ift_channel": "",
            "ift_window_width": 50,
            "adc": None,
            "meta": None,
            "wait_for_post_meta": False,
            "disconnect_after_measurement": False,
            "sensor_configuration": {
                "configuration_id": "test-config",
                "configuration_name": "Test Config",
                "channels": {"1": sensor},
            },
        }

        response = client.post(start, json=instructions)

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Sensor ID 'does-not-exist' does not exist in the active sensor"
            " configuration."
        )

    def test_measurement_start_requires_inline_sensor_config(
        self, measurement_prefix, client, monkeypatch
    ) -> None:
        """`/start` should reject with 422 before any CAN traffic when
        REQUIRE_INLINE_SENSOR_CONFIG=1 and the request has no inline
        `sensor_configuration`"""

        monkeypatch.setenv("REQUIRE_INLINE_SENSOR_CONFIG", "1")

        start = f"{measurement_prefix}/start"

        instructions = {
            "name": "Test Measurement",
            "mac_address": "00-11-22-33-44-55",
            "time": 3,
            "first": {"sensor_id": None},
            "second": {"sensor_id": None},
            "third": {"sensor_id": None},
            "ift_requested": False,
            "ift_channel": "",
            "ift_window_width": 50,
            "adc": None,
            "meta": None,
            "wait_for_post_meta": False,
            "disconnect_after_measurement": False,
        }

        response = client.post(start, json=instructions)

        assert response.status_code == 422
        assert "requires inline sensor configuration" in (
            response.json()["detail"]
        )

    @mark.hardware
    def test_measurement_start_no_input(
        self,
        measurement_prefix,
        connect,  # pylint: disable=unused-argument
        client,
    ) -> None:
        """Test endpoint ``/start`` without specifying required input data"""

        start = f"{measurement_prefix}/start"
        response = client.post(start)
        assert response.status_code == 422
        assert response.json() == {
            "detail": [{
                "input": None,
                "loc": ["body"],
                "msg": "Field required",
                "type": "missing",
            }]
        }

    @mark.hardware
    def test_measurement_start_correct_input(
        self,
        measurement_prefix,
        measurement_instructions_single_channel,
        client,
    ) -> None:
        """Test endpoint ``/start`` with correct data"""

        measurement_status = measurement_prefix
        start = f"{measurement_prefix}/start"
        stop = f"{measurement_prefix}/stop"

        # ========================
        # = Test Normal Response =
        # ========================

        response = client.post(
            start, json=measurement_instructions_single_channel
        )
        assert response.status_code == 200

        assert (
            response.json()["message"] == "Measurement started successfully."
        )

        response = client.get(measurement_status)
        assert response.status_code == 200
        body = response.json()
        instructions = body["instructions"]
        assert (
            instructions["adc"]
            == measurement_instructions_single_channel["adc"]
        )
        assert (
            instructions["first"]
            == measurement_instructions_single_channel["first"]
        )

        response = client.post(stop)
        assert response.status_code == 200
        assert response.json() is None

    @mark.hardware
    def test_measurement_stop(
        self,
        measurement_prefix,
        client,
    ) -> None:
        """Test endpoint ``/stop`` without running measurement"""

        stop = f"{measurement_prefix}/stop"
        response = client.post(stop)
        assert response.status_code == 200
        assert response.json() is None

    @mark.hardware
    def test_measurement_post_meta(
        self,
        measurement_prefix,
        measurement_wait_for_meta,  # pylint: disable=unused-argument
        client,
    ) -> None:
        """Test adding post metadata to measurement"""

        stream = get_measurement_websocket_endpoint(measurement_prefix, client)

        data = None
        with client.websocket_connect(stream) as websocket:
            while data := websocket.receive_json():
                message = data[0]
                # Dataloss values are sent at end of measurement session
                # We ignore data sent before
                if message["dataloss"] is not None:
                    break

        post_meta = f"{measurement_prefix}/post_meta"

        metadata = {
            "version": "1.0",
            "profile": "default",
            "parameters": {
                "Post Metadata": {"value": "Post Metadata", "unit": "string"},
            },
        }

        response = client.post(post_meta, json=metadata)
        assert response.status_code == 200

    @mark.hardware
    def test_measurement_stream_simple(
        self,
        measurement_single_channel,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """Check `/stream` for single channel stream"""

        stream = get_measurement_websocket_endpoint(measurement_prefix, client)

        with client.websocket_connect(stream) as websocket:
            data = websocket.receive_json()
            assert isinstance(data, list)
            assert len(data) >= 1
            message = data[0]
            for key in (
                "timestamp",
                "first",
                "second",
                "third",
                "ift",
                "counter",
                "dataloss",
            ):
                assert key in message
            assert message["timestamp"] >= 0
            assert -125 <= message["first"] <= 100
            assert message["second"] is None
            assert message["third"] is None
            assert 0 <= message["counter"] <= 255
            assert message["ift"] is None

    @mark.hardware
    def test_measurement_stream_dataloss(
        self,
        measurement_single_channel,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """Check `/stream` for message loss"""

        stream = get_measurement_websocket_endpoint(measurement_prefix, client)

        data = None
        with client.websocket_connect(stream) as websocket:
            while data := websocket.receive_json():
                message = data[0]
                # Dataloss values are sent at end of measurement session
                # We ignore data sent before
                if message["dataloss"] is not None:
                    break

        message = data[0]
        assert message["dataloss"] < 0.1

    @mark.hardware
    def test_measurement_stream_ift_value(
        self,
        measurement_ift_value,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """Check `/stream` for single channel stream with active IFT value"""

        stream = get_measurement_websocket_endpoint(measurement_prefix, client)

        data = None
        with client.websocket_connect(stream) as websocket:
            while data := websocket.receive_json():
                message = data[0]
                # IFT values are sent at end of measurement session
                # We ignore data sent before
                if message["ift"] is not None:
                    break

        getLogger().debug("IFT Value data: %s", data)

        assert isinstance(data, list)
        assert len(data) == 1
        message = data[0]
        assert message["ift"] is not None
        values = message["ift"]

        assert isinstance(values, list)
        getLogger().debug("Instructions: %s", measurement_ift_value)
        sample_rate = ADCConfiguration(
            **measurement_ift_value["adc"]
        ).sample_rate()
        getLogger().debug("Sample Rate: %.2f Hz", sample_rate)
        approx_number_values = (
            measurement_ift_value["time"] - 0.15
        ) * sample_rate
        assert len(values) >= approx_number_values

        timestamp_before = 0
        for value in values:
            timestamp = value["x"]
            ift_value = value["y"]
            assert timestamp_before <= timestamp
            assert ift_value >= 0
            timestamp_before = timestamp

    @mark.hardware
    def test_measurement_stream_three_values(
        self,
        measurement_three_channels,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """Check `/stream` for three channel stream with active IFT value"""

        stream = get_measurement_websocket_endpoint(measurement_prefix, client)

        with client.websocket_connect(stream) as websocket:
            data = websocket.receive_json()
            getLogger().info("Data: %s", data)
            assert isinstance(data, list)
            assert len(data) >= 1
            message = data[0]
            assert message["timestamp"] >= 0
            assert -125 <= message["first"] <= 125
            assert -125 <= message["second"] <= 125
            assert -125 <= message["third"] <= 125
            # pylint: enable=fixme
            assert 0 <= message["counter"] <= 255
            assert message["ift"] is None

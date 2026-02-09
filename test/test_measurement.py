"""Tests for measurement endpoint"""

# -- Imports ------------------------------------------------------------------

from datetime import datetime
from logging import getLogger
from time import time

from icostate import ADCConfiguration
from pytest import mark

# -- Functions ----------------------------------------------------------------


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

        assert isinstance(body["start_time"], str)
        start_time = body["start_time"]
        timestamp = datetime.fromisoformat(start_time).timestamp()
        current_timestamp = time()
        assert current_timestamp - 10 <= timestamp <= current_timestamp

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
            assert -100 <= message["first"] <= 100
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
            measurement_ift_value["time"] - 0.1
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
            assert -100 <= message["first"] <= 100
            assert -100 <= message["second"] <= 100
            assert -100 <= message["third"] <= 100
            assert 0 <= message["counter"] <= 255
            assert message["ift"] is None

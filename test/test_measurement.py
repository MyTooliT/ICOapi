"""Tests for measurement endpoint"""

# -- Imports ------------------------------------------------------------------

from datetime import datetime
from time import time

from pytest import mark

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
        measurement_simple,
        client,
    ) -> None:
        """Test endpoint ``/`` while measurement takes place"""

        measurement_status = measurement_prefix
        measurement_instructions_simple = measurement_simple

        response = client.get(measurement_status)
        assert response.status_code == 200

        body = response.json()

        assert body["instructions"] is not None
        instructions = body["instructions"]
        for key in measurement_instructions_simple:
            assert instructions[key] == measurement_instructions_simple[key]
        assert body["running"] is True
        assert body["name"].startswith(measurement_instructions_simple["name"])
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
        self, measurement_prefix, measurement_instructions_simple, client
    ) -> None:
        """Test endpoint ``/start`` with correct data"""

        measurement_status = measurement_prefix
        start = f"{measurement_prefix}/start"
        stop = f"{measurement_prefix}/stop"

        # ========================
        # = Test Normal Response =
        # ========================

        response = client.post(start, json=measurement_instructions_simple)
        assert response.status_code == 200

        assert (
            response.json()["message"] == "Measurement started successfully."
        )

        response = client.get(measurement_status)
        assert response.status_code == 200
        body = response.json()
        instructions = body["instructions"]
        assert instructions["adc"] == measurement_instructions_simple["adc"]
        assert (
            instructions["first"] == measurement_instructions_simple["first"]
        )

        response = client.post(stop)
        assert response.status_code == 200
        assert response.json() is None

    @mark.hardware
    def test_measurement_stream(
        self,
        measurement_simple,  # pylint: disable=unused-argument
        measurement_prefix,
        client,
    ) -> None:
        """Check WebSocket streaming data"""

        measurement_status = str(measurement_prefix)

        response = client.get(measurement_status)
        assert response.status_code == 200
        assert response.json()["running"] is True

        ws_url = str(client.base_url).replace("http", "ws")
        stream = f"{ws_url}{measurement_prefix}/stream"

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

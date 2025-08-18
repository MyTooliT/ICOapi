# -- Classes ------------------------------------------------------------------


class TestMeasurement:

    def test_root(self, measurement_prefix, client) -> None:
        """Test endpoint ``/``"""

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

    def test_start(
        self, measurement_prefix, measurement_configuration, client
    ) -> None:
        """Test endpoint ``/start``"""

        measurement_status = measurement_prefix
        start = f"{measurement_prefix}/start"
        stop = f"{measurement_prefix}/stop"

        # ========================
        # = Test Normal Response =
        # ========================

        response = client.post(start, json=measurement_configuration)
        assert response.status_code == 200

        assert (
            response.json()["message"] == "Measurement started successfully."
        )

        response = client.get(measurement_status)
        assert response.status_code == 200
        body = response.json()
        instructions = body["instructions"]
        assert instructions["adc"] == measurement_configuration["adc"]
        assert instructions["first"] == measurement_configuration["first"]

        response = client.post(stop)

        # =======================
        # = Test Error Response =
        # =======================

        response = client.post(start)
        assert response.status_code == 422

    def test_stream(self, measurement, measurement_prefix, client) -> None:
        """Check WebSocket streaming data"""

        measurement

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

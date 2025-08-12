# -- Classes ------------------------------------------------------------------


class TestMeasurement:

    def test_root(self, measurement_prefix, client) -> None:
        """Test endpoint ``/``"""

        measurement_status = str(measurement_prefix)

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

    def test_start(self, connect, measurement_prefix, client) -> None:
        """Test endpoint ``/start``"""

        node = connect

        measurement_status = str(measurement_prefix)
        start = str(measurement_prefix / "start")
        stop = str(measurement_prefix / "stop")

        adc_config = {
            "prescaler": 2,
            "acquisition_time": 8,
            "oversampling_rate": 64,
            "reference_voltage": 3.3,
        }
        sensor = {
            "channel_number": 1,
            "sensor_id": "acc100g_01",
        }
        disabled = {
            "channel_number": 0,
            "sensor_id": "",
        }

        # ========================
        # = Test Normal Response =
        # ========================

        response = client.post(
            start,
            json={
                "name": node["name"],
                "mac": node["mac_address"],
                "time": 10,
                "first": sensor,
                "second": disabled,
                "third": disabled,
                "ift_requested": False,
                "ift_channel": "",
                "ift_window_width": 0,
                "adc": adc_config,
                "meta": {"version": "", "profile": "", "parameters": {}},
            },
        )
        assert response.status_code == 200

        assert (
            response.json()["message"] == "Measurement started successfully."
        )

        response = client.get(measurement_status)
        assert response.status_code == 200
        body = response.json()
        instructions = body["instructions"]
        assert instructions["adc"] == adc_config
        assert instructions["first"] == sensor

        response = client.post(stop)

        # =======================
        # = Test Error Response =
        # =======================

        response = client.post(start)
        assert response.status_code == 422

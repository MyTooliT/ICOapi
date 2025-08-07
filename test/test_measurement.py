# -- Imports ------------------------------------------------------------------

from asyncio import sleep

from pytest import mark

# -- Classes ------------------------------------------------------------------


@mark.usefixtures("anyio_backend")
class TestSTU:

    async def test_root(self, measurement_prefix, client) -> None:
        """Test endpoint ``/``"""

        measurement_status = str(measurement_prefix)

        response = await client.get(measurement_status)
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

    async def test_start(self, connect, measurement_prefix, client) -> None:
        """Test endpoint ``/start``"""

        node = connect

        start = str(measurement_prefix / "start")
        stop = str(measurement_prefix / "stop")

        # ========================
        # = Test Normal Response =
        # ========================

        response = await client.post(
            start,
            json={
                "name": node["name"],
                "mac": node["mac_address"],
                "time": 0,
                "first": {
                    "channel_number": 1,
                    "sensor_id": "Acceleration Sensor",
                },
                "second": {
                    "channel_number": 0,
                    "sensor_id": "",
                },
                "third": {
                    "channel_number": 0,
                    "sensor_id": "",
                },
                "ift_requested": False,
                "ift_channel": "",
                "ift_window_width": 0,
                "adc": {
                    "prescaler": 2,
                    "acquisition_time": 8,
                    "oversampling_rate": 64,
                    "reference_voltage": 3.3,
                },
                "meta": {"version": "", "profile": "", "parameters": {}},
            },
        )
        assert response.status_code == 200

        assert (
            response.json()["message"] == "Measurement started successfully."
        )

        # Wait for measurement to take place
        await sleep(10)

        response = await client.post(stop)

        # =======================
        # = Test Error Response =
        # =======================

        response = await client.post(start)
        assert response.status_code == 422

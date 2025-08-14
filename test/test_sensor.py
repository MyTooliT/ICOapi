# -- Imports ------------------------------------------------------------------

from types import NoneType

# -- Classes ------------------------------------------------------------------


class TestSensor:

    def test_sensor(self, sensor_prefix, client) -> None:
        """Test endpoint ``/sensor``"""

        response = client.get(sensor_prefix)

        assert response.status_code == 200

        body = response.json()
        assert isinstance(body, list)
        for config in body:
            for key in ("name", "sensor_type", "sensor_id", "unit"):
                assert isinstance(config[key], (str, NoneType))
            for key in (
                "phys_min",
                "phys_max",
                "volt_min",
                "volt_max",
                "scaling_factor",
                "offset",
            ):
                assert isinstance(config[key], float)

    def test_sensorreset(self, sensorreset_prefix, client) -> None:
        """Test endpoint ``/sensorreset``"""

        response = client.post(sensorreset_prefix)

        assert response.status_code == 200

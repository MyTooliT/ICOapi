"""Tests for sensor endpoint"""

# -- Imports ------------------------------------------------------------------

from types import NoneType

# -- Functions ----------------------------------------------------------------


def test_sensor(sensor_prefix, client) -> None:
    """Test endpoint ``/sensor``"""

    response = client.get(sensor_prefix)

    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, dict)

    sensors = body["sensors"]
    assert isinstance(sensors, list)

    for sensor in sensors:
        for key in ("name", "sensor_id", "unit", "dimension"):
            assert isinstance(sensor[key], str)
        for key in (
            "phys_min",
            "phys_max",
            "volt_min",
            "volt_max",
            "scaling_factor",
            "offset",
        ):
            assert isinstance(sensor[key], float)
        assert isinstance(sensor["sensor_type"], (str, NoneType))

    configurations = body["configurations"]
    assert isinstance(configurations, list)

    for configuration in configurations:
        for key in ("configuration_id", "configuration_name"):
            assert isinstance(configuration[key], str)
        assert isinstance(configuration["channels"], dict)

"""OpenAPI request examples for `POST /measurement/execute`"""

from fastapi.openapi.models import Example

# Real values from a Test-STH (see test/conftest.py's `test_sensor_node` /
# `test_sensor_node_adc_configuration` / `sensor_id` fixtures) so this is a
# request that actually runs, not a placeholder someone has to edit first -
# swap `mac_address` for a MAC from `GET /sth` and it works against any STH.
_EXAMPLE_MAC_ADDRESS = "14-2D-41-D7-77-7D"
_EXAMPLE_ADC = {
    "prescaler": 2,
    "acquisition_time": 8,
    "oversampling_rate": 64,
    "reference_voltage": 3.3,
}

EXECUTE_EXAMPLES: dict[str, Example] = {
    "default_configuration": {
        "summary": "Default configuration (from sensors.yaml)",
        "description": (
            "Resolves `sensor_id` against the local sensor configuration"
            " file's default configuration - the same file "
            "`GET /api/v1/sensor` serves."
        ),
        "value": {
            "name": "Example Measurement",
            "mac_address": _EXAMPLE_MAC_ADDRESS,
            "time": 5,
            "first": {"sensor_id": "acc100g_01"},
            "second": {},
            "third": {},
            "ift_requested": False,
            "ift_channel": "",
            "ift_window_width": 50,
            "adc": _EXAMPLE_ADC,
            "wait_for_post_meta": False,
            "disconnect_after_measurement": True,
        },
    },
    "inline_sensor_configuration": {
        "summary": "Inline sensor configuration (headless orchestration)",
        "description": (
            "Self-contained: the sensor's full calibration travels with the"
            " request instead of being resolved from the local file. This"
            " is what `REQUIRE_INLINE_SENSOR_CONFIG=1` requires."
        ),
        "value": {
            "name": "Example Measurement",
            "mac_address": _EXAMPLE_MAC_ADDRESS,
            "time": 5,
            "first": {"sensor_id": "acc100g_01"},
            "second": {},
            "third": {},
            "ift_requested": False,
            "ift_channel": "",
            "ift_window_width": 50,
            "adc": _EXAMPLE_ADC,
            "wait_for_post_meta": False,
            "disconnect_after_measurement": True,
            "sensor_configuration": {
                "configuration_id": "example",
                "configuration_name": "Example inline configuration",
                "channels": {
                    "1": {
                        "sensor_id": "acc100g_01",
                        "name": "Acceleration 100g",
                        "sensor_type": "ADXL1001",
                        "unit": "g",
                        "dimension": "Acceleration",
                        "phys_min": -100.0,
                        "phys_max": 100.0,
                        "volt_min": 0.33,
                        "volt_max": 2.97,
                    }
                },
            },
        },
    },
}

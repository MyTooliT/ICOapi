"""Configuration for pytest"""

# -- Imports ------------------------------------------------------------------

from fastapi.testclient import TestClient
from httpx import AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport
from netaddr import EUI
from pytest import fixture

from icoapi.api import app

# -- Fixtures -----------------------------------------------------------------

# pylint: disable=redefined-outer-name


@fixture(scope="session")
def anyio_backend():
    """Set default async backend"""

    return "asyncio"


@fixture(scope="session")
def measurement_prefix():
    """Prefix for measurement endpoints"""

    return "measurement"


@fixture(scope="session")
def reset_can_prefix():
    """Prefix for CAN reset endpoint"""

    return "reset-can"


@fixture(scope="session")
def sensor_prefix():
    """Prefix for sensor endpoints"""

    return "sensor"


@fixture(scope="session")
def sensorreset_prefix():
    """Prefix for sensor reset endpoints"""

    return "sensorreset"


@fixture(scope="session")
def state_prefix():
    """Prefix for state endpoint"""

    return "state"


@fixture(scope="session")
def sth_prefix():
    """Prefix for STH endpoint"""

    return "sth"


@fixture(scope="session")
def stu_prefix():
    """Prefix for STU endpoint"""

    return "stu"


@fixture(scope="session")
def sensor_name():
    """Name of sensor used for testing"""

    return "Acceleration 100g"


@fixture(scope="session")
def client():
    """Test client used to communicate with API"""

    with TestClient(
        app=app,
        base_url="http://test/api/v1/",
    ) as test_client:
        yield test_client


@fixture(scope="session")
async def async_client():
    """Async test client used to communicate with API"""

    async with AsyncClient(
        transport=ASGIWebSocketTransport(app=app),
        base_url="http://test/api/v1/",
    ) as async_client:
        yield async_client


@fixture(scope="session")
def test_sensor_node(sth_prefix, client):
    """Get test sensor node information"""

    response = client.get(str(sth_prefix))

    assert response.status_code == 200
    sensor_nodes = response.json()

    # We assume that a sensor device with the name `Test-STH` is available and
    # ready for connection
    node = None
    for sensor_node in sensor_nodes:
        if sensor_node["name"] == "Test-STH":
            node = sensor_node
            break
    assert node is not None
    mac_address = node["mac_address"]
    assert mac_address is not None
    assert EUI(mac_address)  # Check for valid MAC address

    yield node


@fixture(scope="session")
def test_sensor_node_adc_configuration(sth_prefix, test_sensor_node, client):
    """Get ADC configuration of test sensor node"""

    assert (
        client.put(
            f"{sth_prefix}/connect",
            json={"mac_address": test_sensor_node["mac_address"]},
        ).status_code
        == 200
    )

    response = client.get(f"{sth_prefix}/read-adc")
    assert response.status_code == 200
    adc_configuration = response.json()

    client.put(f"{sth_prefix}/disconnect")

    return adc_configuration


@fixture
def connect(sth_prefix, test_sensor_node, client):
    """Connect sensor node"""

    node = test_sensor_node

    mac_address = node["mac_address"]
    response = client.put(
        f"{sth_prefix}/connect", json={"mac_address": mac_address}
    )
    assert response.status_code == 200
    assert response.json() is None

    yield node

    client.put(f"{sth_prefix}/disconnect")


@fixture
def sensor_id(sensor_name, client):
    """Get the sensor id of the sensor used for testing"""

    response = client.get("sensor")
    assert response.status_code == 200
    sensors = response.json()["sensors"]

    sensor_id = None
    for config in sensors:
        if config["name"] == sensor_name:
            sensor_id = config["sensor_id"]

    return sensor_id


@fixture
def measurement_instructions(
    test_sensor_node_adc_configuration, connect, sensor_id
):
    """Get test measurement configuration"""

    node = connect

    first = {
        # Use a different sensor channel number for the first measurement
        # channel to make sure we execute the code for changing the sensor
        # configuration.
        "channel_number": 2,
        "sensor_id": sensor_id,
    }
    disabled = {
        "channel_number": 0,
        "sensor_id": None,
    }

    configuration = {
        "name": "Test Measurement",
        "mac_address": node["mac_address"],
        "time": 10,
        "first": first,
        "second": disabled,
        "third": disabled,
        "ift_requested": False,
        "ift_channel": "",
        "ift_window_width": 0,
        "adc": test_sensor_node_adc_configuration,
        "meta": {"version": "", "profile": "", "parameters": {}},
    }

    return configuration


@fixture
def measurement(measurement_prefix, measurement_instructions, client):
    """Fixture for running measurement"""

    start = f"{measurement_prefix}/start"
    stop = f"{measurement_prefix}/stop"

    response = client.post(start, json=measurement_instructions)

    assert response.status_code == 200

    yield measurement_instructions

    response = client.post(stop)

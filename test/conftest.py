"""Configuration for pytest"""

# -- Imports ------------------------------------------------------------------

from re import match
from typing import Any

from fastapi.testclient import TestClient
from httpx import AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport
from netaddr import EUI
from pytest import fixture

from icoapi.api import app

# -- Functions ----------------------------------------------------------------


def create_measurement_instructions(
    mac_address: str, **instructions
) -> dict[str, Any]:
    """Create measurement instructions based on given arguments"""

    def set_default(name: str, value: Any) -> None:
        """Set instruction name to default value, if not already set before"""
        if instructions.get(name, None) is None:
            instructions[name] = value

    disabled = {
        "channel_number": 0,
        "sensor_id": None,
    }

    for channel in ("first", "second", "third"):
        set_default(channel, disabled)

    set_default("ift_requested", False)
    set_default("ift_channel", "")
    set_default("ift_window_width", 50)
    set_default("meta", {"version": "", "profile": "", "parameters": {}})
    set_default("name", "Test Measurement")
    set_default("time", 10)

    instructions["mac_address"] = mac_address

    return instructions


def generate_measurement_fixture(fixture_name: str, instructions: str) -> str:
    """Create fixture for running measurement"""

    if not all([
        isinstance(fixture_name, str),
        isinstance(instructions, str),
        (0 < len(fixture_name) < 30),
        (0 < len(instructions) < 40),
        match(r"^[a-zA-Z_]+$", fixture_name),
        match(r"^[a-zA-Z_]+$", instructions),
    ]):
        raise ValueError("Please do not try to generate/run arbitrary code 🥺")

    code = f"""
@fixture
def {fixture_name}(
    measurement_prefix, {instructions}, client
):
    start = f"{{measurement_prefix}}/start"
    stop = f"{{measurement_prefix}}/stop"

    response = client.post(start, json={instructions})

    assert response.status_code == 200

    yield {instructions}

    response = client.post(stop)
"""

    return code


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
def measurement_instructions_simple(
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

    instructions = create_measurement_instructions(
        mac_address=node["mac_address"],
        adc=test_sensor_node_adc_configuration,
        first=first,
    )

    return instructions


@fixture
def measurement_instructions_ift_value(
    test_sensor_node_adc_configuration, connect, sensor_id
):
    """Get test measurement configuration"""

    node = connect

    second = {
        "channel_number": 1,
        "sensor_id": sensor_id,
    }

    instructions = create_measurement_instructions(
        mac_address=node["mac_address"],
        adc=test_sensor_node_adc_configuration,
        first=second,
        ift_requested=True,
        ift_channel=1,
    )

    return instructions


# pylint: disable=exec-used

# If you think that creating the fixture by using exec is horrible, I do
# agree ☹️. If you find a solution to specify the argument of the fixture
# dynamically, then please fix the code and submit a pull request.

exec(
    generate_measurement_fixture(
        "measurement_simple", "measurement_instructions_simple"
    )
)
exec(
    generate_measurement_fixture(
        "measurement_ift_value", "measurement_instructions_ift_value"
    )
)

# pylint: enable=exec-used

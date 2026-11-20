"""Configuration for pytest"""

# -- Imports ------------------------------------------------------------------

import asyncio
from collections.abc import Iterator
from os import environ
from re import match
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport
from netaddr import EUI
from pytest import fixture

from icoapi.api import app, setup_config
from icoapi.models.event_bus import Channel, EventBus
from icoapi.models.globals import GeneralMessenger, ICOsystemSingleton
from icoapi.models.models import CANNetwork, CANStatus, SystemStateModel

# -- Classes ------------------------------------------------------------------


class RecordingEventBus(EventBus):
    """Event bus that records everything published"""

    def __init__(self) -> None:
        self.states: list[SystemStateModel] = []
        self.events: list[tuple[Channel, dict[str, Any]]] = []

    async def publish_state(self, state: SystemStateModel) -> None:
        self.states.append(state)

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        self.events.append((channel, payload))


# -- Functions ----------------------------------------------------------------


def create_measurement_instructions(
    mac_address: str, **instructions
) -> dict[str, Any]:
    """Create measurement instructions based on given arguments"""

    def set_default(name: str, value: Any) -> None:
        """Set instruction name to default value, if not already set before"""
        if instructions.get(name) is None:
            instructions[name] = value

    disabled = {
        "sensor_id": None,
    }

    for channel in ("first", "second", "third"):
        set_default(channel, disabled)

    set_default("ift_requested", False)
    set_default("ift_channel", "")
    set_default("ift_window_width", 50)
    set_default("meta", {"version": "", "profile": "", "parameters": {}})
    set_default("name", "Test Measurement")
    set_default("time", 3)
    set_default("wait_for_post_meta", False)
    set_default("disconnect_after_measurement", False)

    instructions["mac_address"] = mac_address

    return instructions


def generate_measurement_fixture(fixture_name: str, instructions: str) -> str:
    """Create fixture for running measurement"""

    if not all(
        [
            isinstance(fixture_name, str),
            isinstance(instructions, str),
            (0 < len(fixture_name) < 30),
            (0 < len(instructions) < 40),
            match(r"^[a-zA-Z_]+$", fixture_name),
            match(r"^[a-zA-Z_]+$", instructions),
        ]
    ):
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


def reset_can_state() -> None:
    """Forget the CAN connection and networks of the API"""

    ICOsystemSingleton._instance = None
    ICOsystemSingleton._units = {}
    ICOsystemSingleton.status = CANStatus.NO_NETWORK
    ICOsystemSingleton.networks = []
    ICOsystemSingleton.selected = None
    ICOsystemSingleton.error = None
    ICOsystemSingleton.stu_connected = False


@fixture
def isolated_can_state() -> Iterator[None]:
    """Start with an empty CAN state and restore the previous one afterwards

    The API is started once for all tests that use ``client``. Tests that
    change the CAN state must not take its connection away.
    """

    names = (
        "_instance",
        "_units",
        "status",
        "networks",
        "selected",
        "error",
        "stu_connected",
    )
    saved = {
        name: (
            dict(value)
            if isinstance(value := getattr(ICOsystemSingleton, name), dict)
            else value
        )
        for name in names
    }
    reset_can_state()
    yield
    for name, value in saved.items():
        setattr(ICOsystemSingleton, name, value)


@fixture
async def http() -> Any:
    """HTTP client that does not run the application lifespan"""

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1/"
    ) as http_client:
        yield http_client


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

    setup_config()
    environ.setdefault("ICOAPI_CAN_AUTOCONNECT", "1")

    with TestClient(
        app=app,
        base_url="http://test/api/v1/",
    ) as test_client:
        yield test_client


@fixture(scope="session", autouse=True)
def flush_can_network(request) -> None:
    """Flush the CAN network once before the first hardware test

    A bus that reached its warning/heavy limit stalls the following tests, so
    release the adapter, search for networks again and reset the STU before
    any hardware test runs. Does nothing if no hardware test is selected or if
    the hardware is simulated.
    """

    if environ.get("ICOAPI_SIMULATE", "").strip().lower() == "only":
        return
    if not any(
        item.get_closest_marker("hardware") for item in request.session.items
    ):
        return

    setup_config()
    environ.setdefault("ICOAPI_CAN_AUTOCONNECT", "1")

    # Same as `just reset-can`. The adapter is released afterwards, since
    # the application connects again when `client` starts it (in its own
    # event loop).
    asyncio.run(ICOsystemSingleton.reset())
    asyncio.run(ICOsystemSingleton.disconnect())
    reset_can_state()

    # Same as `icon stu reset`
    response = request.getfixturevalue("client").put("stu/reset")
    assert response.status_code == 200, "Unable to reset STU"


@fixture(autouse=True)
def fake_can_connection(request) -> Iterator[None]:
    """Pretend to be connected to a CAN network in tests without hardware

    Tests marked with ``hardware`` use the real connection.
    """

    uses_api = {"client", "async_client"} & set(request.fixturenames)
    if not uses_api or request.node.get_closest_marker("hardware"):
        yield
        return

    # Start the application first, since startup resets the CAN state
    for name in ("client", "async_client"):
        if name in request.fixturenames:
            request.getfixturevalue(name)

    original = (
        ICOsystemSingleton._instance,
        ICOsystemSingleton.status,
        ICOsystemSingleton.networks,
        ICOsystemSingleton.stu_connected,
    )
    original_units = ICOsystemSingleton._units
    ICOsystemSingleton._units = {}
    network = CANNetwork(interface="virtual", channel="test")
    system = MagicMock()
    system.is_sensor_node_connected = AsyncMock(return_value=False)
    system.sensor_node_attributes = None
    ICOsystemSingleton._instance = system
    ICOsystemSingleton.status = CANStatus.CONNECTED
    ICOsystemSingleton.networks = [network]
    ICOsystemSingleton.stu_connected = True

    yield

    ICOsystemSingleton._units = original_units
    (
        ICOsystemSingleton._instance,
        ICOsystemSingleton.status,
        ICOsystemSingleton.networks,
        ICOsystemSingleton.stu_connected,
    ) = original


@fixture(scope="session")
async def async_client():
    """Async test client used to communicate with API"""

    setup_config()
    environ.setdefault("ICOAPI_CAN_AUTOCONNECT", "1")

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
def recording_event_bus() -> Iterator[RecordingEventBus]:
    """Record everything the API publishes on its event buses

    Use this fixture before the fixtures that start a measurement.
    """

    bus = RecordingEventBus()
    GeneralMessenger.add_bus(bus)

    yield bus

    GeneralMessenger.remove_bus(bus)


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
def three_distinct_sensor_ids(client) -> list[str]:
    """Sensor IDs of (at least) three channels in the active configuration

    Fetched from the live default sensor configuration rather than
    hardcoded, so this works against whatever tool holder is actually
    connected. Each `sensor_id` resolves to its own channel number (see
    `resolve_channel` in `icoapi/scripts/data_handling.py`), so distinct
    sensor IDs are required to exercise distinct channels - unlike the old
    channel_number-based instructions, a single sensor_id can no longer be
    reused across slots to force multiple channels active at once.
    """

    response = client.get("sensor")
    assert response.status_code == 200
    body = response.json()

    default_configuration_id = body["default_configuration_id"]
    configuration = next(
        config
        for config in body["configurations"]
        if config["configuration_id"] == default_configuration_id
    )
    channels = configuration["channels"]
    assert len(channels) >= 3, (
        "Active sensor configuration needs at least three channels for the"
        " multi-channel measurement fixtures"
    )

    # Channel keys are strings in JSON; sort numerically for a stable pick.
    ordered_channel_numbers = sorted(channels, key=int)
    return [
        channels[channel_number]["sensor_id"]
        for channel_number in ordered_channel_numbers[:3]
    ]


@fixture
def measurement_instructions_single_channel(
    test_sensor_node_adc_configuration, connect, sensor_id
):
    """Single channel measurement instructions"""

    node = connect

    first = {
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
    """Single channel measurement instructions with activated IFT value"""

    node = connect

    second = {
        "sensor_id": sensor_id,
    }

    instructions = create_measurement_instructions(
        mac_address=node["mac_address"],
        adc=test_sensor_node_adc_configuration,
        second=second,
        time=5,
        ift_requested=True,
        ift_channel="second",
    )

    return instructions


@fixture
def measurement_instructions_three_channels(
    test_sensor_node_adc_configuration, connect, three_distinct_sensor_ids
):
    """Tripple channel measurement instructions with activated IFT value"""

    node = connect

    def get_sensor(sensor_id: str) -> dict[str, Any]:
        return {
            "sensor_id": sensor_id,
        }

    first_id, second_id, third_id = three_distinct_sensor_ids

    instructions = create_measurement_instructions(
        mac_address=node["mac_address"],
        adc=test_sensor_node_adc_configuration,
        first=get_sensor(first_id),
        second=get_sensor(second_id),
        third=get_sensor(third_id),
        time=5,
        ift_requested=True,
        ift_channel="third",
    )

    return instructions


# If you think that creating the fixture by using exec is horrible, I do
# agree ☹️. If you find a solution to specify the argument of the fixture
# dynamically, then please fix the code and submit a pull request.

exec(
    generate_measurement_fixture(
        "measurement_single_channel", "measurement_instructions_single_channel"
    )
)
exec(
    generate_measurement_fixture(
        "measurement_ift_value", "measurement_instructions_ift_value"
    )
)
exec(
    generate_measurement_fixture(
        "measurement_three_channels", "measurement_instructions_three_channels"
    )
)

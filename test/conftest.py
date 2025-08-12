# -- Imports ------------------------------------------------------------------

from pathlib import Path

from fastapi.testclient import TestClient
from netaddr import EUI
from pytest import fixture

from icoapi.api import app

# -- Fixtures -----------------------------------------------------------------


@fixture(scope="session")
def anyio_backend():
    return "asyncio"


@fixture
def measurement_prefix():
    return Path("measurement")


@fixture
def reset_can_prefix():
    return Path("reset-can")


@fixture
def state_prefix():
    return Path("state")


@fixture
def sth_prefix():
    return Path("sth")


@fixture
def stu_prefix():
    return Path("stu")


@fixture(scope="session")
def client():
    with TestClient(
        app=app,
        base_url="http://test/api/v1/",
    ) as client:
        yield client


@fixture
def get_test_sensor_node(sth_prefix, client):
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


@fixture
def connect(sth_prefix, get_test_sensor_node, client):
    node = get_test_sensor_node

    mac_address = node["mac_address"]
    response = client.put(
        str(sth_prefix / "connect"), json={"mac": mac_address}
    )
    assert response.status_code == 200
    assert response.json() is None

    yield node

    client.put(str(sth_prefix / "disconnect"))

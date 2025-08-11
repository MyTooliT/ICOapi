# -- Imports ------------------------------------------------------------------

from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from netaddr import EUI
from pytest import fixture

from icoapi.api import app

# -- Fixtures -----------------------------------------------------------------


@fixture(scope="session")
def anyio_backend():
    return "asyncio"


@fixture
async def measurement_prefix():
    return Path("measurement")


@fixture
async def sth_prefix():
    return Path("sth")


@fixture
async def stu_prefix():
    return Path("stu")


@fixture(scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app),
            base_url="http://test/api/v1/",
        ) as client:
            yield client


@fixture
async def get_test_sensor_node(sth_prefix, client):
    response = await client.get(str(sth_prefix))

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
async def connect(sth_prefix, get_test_sensor_node, client):
    node = get_test_sensor_node

    mac_address = node["mac_address"]
    response = await client.put(
        str(sth_prefix / "connect"), json={"mac": mac_address}
    )
    assert response.status_code == 200
    assert response.json() is None

    yield node

    await client.put(str(sth_prefix / "disconnect"))

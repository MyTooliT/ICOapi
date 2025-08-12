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


@fixture
def measurement(measurement_prefix, connect, client):
    node = connect

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

    yield

    response = client.post(stop)

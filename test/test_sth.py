# -- Imports ------------------------------------------------------------------

from typing import Any

from netaddr import EUI
from pytest import mark

# -- Globals ------------------------------------------------------------------

sth_prefix = "/api/v1/sth"

# -- Functions ----------------------------------------------------------------


async def get_and_connect_test_sensor_node(client) -> dict[str, Any]:
    response = await client.get(sth_prefix)

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

    mac_address = sensor_node["mac_address"]
    response = await client.put(
        f"{sth_prefix}/connect", json={"mac": mac_address}
    )
    assert response.status_code == 200
    assert response.json() is None

    return node


# -- Tests --------------------------------------------------------------------


@mark.anyio
async def test_root(client) -> None:
    """Test endpoint ``/``"""

    response = await client.get(sth_prefix)

    assert response.status_code == 200
    sensor_devices = response.json()
    # We assume that at least one sensor device is available
    assert len(sensor_devices) >= 1

    sensor_device = sensor_devices[0]
    assert sensor_device["device_number"] == 0
    mac_address = sensor_device["mac_address"]
    # Check that MAC address is valid and assert that it is equal to (the
    # string representation) of itself
    assert EUI(mac_address) == mac_address
    assert len(sensor_device["name"]) <= 8
    assert 0 >= sensor_device["rssi"] >= -80


@mark.anyio
async def test_connect_disconnect(client) -> None:
    """Test endpoint ``/connect`` and ``disconnect``"""

    # ========================
    # = Test Normal Response =
    # ========================

    await get_and_connect_test_sensor_node(client)

    await client.put(f"{sth_prefix}/disconnect")

    # =======================
    # = Test Error Response =
    # =======================

    response = await client.put(
        f"{sth_prefix}/connect", json={"mac": "01-02-03-04-05-06"}
    )

    assert response.status_code == 404


@mark.anyio
async def test_rename(client) -> None:
    """Test endpoint ``/rename``"""

    sensor_node = await get_and_connect_test_sensor_node(client)
    mac_address = sensor_node["mac_address"]

    response = await client.put(
        f"{sth_prefix}/rename",
        json={"mac_address": mac_address, "new_name": "Hello"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
    old_name = response.json()["old_name"]
    name = response.json()["name"]
    assert name == "Hello"

    response = await client.put(
        f"{sth_prefix}/rename",
        json={"mac_address": mac_address, "new_name": old_name},
    )
    assert isinstance(response.json(), dict)
    assert response.json()["old_name"] == name
    assert response.json()["name"] == old_name

    await client.put(f"{sth_prefix}/disconnect")


@mark.anyio
async def test_read_adc(client) -> None:
    """Test endpoint ``/read-adc``"""

    await get_and_connect_test_sensor_node(client)

    response = await client.get(f"{sth_prefix}/read-adc")
    assert response.status_code == 200
    adc_configuration = response.json()
    assert "prescaler" in adc_configuration
    assert "acquisition_time" in adc_configuration
    assert "oversampling_rate" in adc_configuration
    assert "reference_voltage" in adc_configuration

    await client.put(f"{sth_prefix}/disconnect")

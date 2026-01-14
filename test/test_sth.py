"""STH endpoint test methods"""

# -- Imports ------------------------------------------------------------------

from fastapi.testclient import TestClient
from netaddr import EUI
from pytest import mark

# -- Functions ----------------------------------------------------------------


def rename_sth(sth_prefix: str, mac_address: str, client: TestClient):
    """Rename STH"""

    response = client.put(
        f"{sth_prefix}/rename",
        json={"mac_address": mac_address, "new_name": "Hello"},
    )
    assert response.status_code == 200

    assert isinstance(response.json(), dict)
    old_name = response.json()["old_name"]
    name = response.json()["name"]
    assert name == "Hello"

    response = client.put(
        str(f"{sth_prefix}/rename"),
        json={"mac_address": mac_address, "new_name": old_name},
    )
    assert isinstance(response.json(), dict)
    assert response.json()["old_name"] == name
    assert response.json()["name"] == old_name


# -- Tests --------------------------------------------------------------------


class TestSTH:
    """STH endpoint test methods"""

    @mark.hardware
    def test_sth_list_sensor_nodes(self, sth_prefix, client) -> None:
        """Test endpoint ``/``"""

        response = client.get(sth_prefix)

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
        assert 0 >= sensor_device["rssi"] >= -90

    @mark.hardware
    def test_connect_disconnect(
        self, sth_prefix, test_sensor_node, client
    ) -> None:
        """Test endpoint ``/connect`` and ``/disconnect``"""

        # ========================
        # = Test Normal Response =
        # ========================

        mac_address = test_sensor_node["mac_address"]
        response = client.put(
            f"{sth_prefix}/connect", json={"mac_address": mac_address}
        )
        assert response.status_code == 200
        assert response.json() is None

        response = client.put(f"{sth_prefix}/disconnect")
        assert response.status_code == 200
        assert response.json() is None

        # =======================
        # = Test Error Response =
        # =======================

        response = client.put(
            f"{sth_prefix}/connect", json={"mac_address": "01-02-03-04-05-06"}
        )

        assert response.status_code == 404

    @mark.hardware
    def test_rename_disconnected(
        self, sth_prefix, test_sensor_node, client
    ) -> None:
        """Test endpoint ``/rename`` while disconnected from STH"""

        mac_address = test_sensor_node["mac_address"]
        rename_sth(sth_prefix, mac_address, client)

    @mark.hardware
    def test_rename_connected(self, sth_prefix, connect, client) -> None:
        """Test endpoint ``/rename`` while connected to STH"""

        sensor_node = connect
        mac_address = sensor_node["mac_address"]

        rename_sth(sth_prefix, mac_address, client)

    @mark.hardware
    def test_read_adc_connected(
        self,
        sth_prefix,
        client,
        connect,
        # pylint: disable=unused-argument
    ) -> None:
        """Test endpoint ``/read-adc`` when connected to sensor node"""

        response = client.get(f"{sth_prefix}/read-adc")
        assert response.status_code == 200
        adc_configuration = response.json()
        adc_attributes_int = {
            "prescaler",
            "acquisition_time",
            "oversampling_rate",
        }
        for attribute in adc_attributes_int:
            assert attribute in adc_configuration
            assert isinstance(adc_configuration[attribute], int)
        assert "reference_voltage" in adc_configuration
        assert isinstance(adc_configuration["reference_voltage"], float)

    @mark.hardware
    def test_read_adc_disconnected(
        self,
        sth_prefix,
        client,
    ) -> None:
        """Test endpoint ``/read-adc`` when not connected to sensor node"""

        response = client.get(f"{sth_prefix}/read-adc")
        assert response.status_code == 404

    @mark.hardware
    def test_write_adc_connected(
        self,
        sth_prefix,
        connect,
        client,
        # pylint: disable=unused-argument
    ) -> None:
        """Test endpoint ``/write-adc`` when connected to sensor node"""

        response = client.get(f"{sth_prefix}/read-adc")
        assert response.status_code == 200
        adc_configuration = response.json()

        response = client.put(
            f"{sth_prefix}/write-adc",
            json=adc_configuration,
        )

        assert response.status_code == 200

    @mark.hardware
    def test_write_adc_disconnected(
        self,
        sth_prefix,
        test_sensor_node_adc_configuration,
        client,
    ) -> None:
        """Test endpoint ``/write-adc`` when not connected to sensor node"""

        response = client.put(
            f"{sth_prefix}/write-adc",
            json=test_sensor_node_adc_configuration,
        )
        assert response.status_code == 404

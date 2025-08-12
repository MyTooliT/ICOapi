# -- Imports ------------------------------------------------------------------

from netaddr import EUI

# -- Tests --------------------------------------------------------------------


class TestSTH:

    def test_root(self, sth_prefix, client) -> None:
        """Test endpoint ``/``"""

        response = client.get(str(sth_prefix))

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

    def test_connect_disconnect(
        self, sth_prefix, get_test_sensor_node, client
    ) -> None:
        """Test endpoint ``/connect`` and ``/disconnect``"""

        # ========================
        # = Test Normal Response =
        # ========================

        node = get_test_sensor_node

        mac_address = node["mac_address"]
        response = client.put(
            str(sth_prefix / "connect"), json={"mac": mac_address}
        )
        assert response.status_code == 200
        assert response.json() is None

        client.put(str(sth_prefix / "disconnect"))

        # =======================
        # = Test Error Response =
        # =======================

        response = client.put(
            str(sth_prefix / "connect"), json={"mac": "01-02-03-04-05-06"}
        )

        assert response.status_code == 404

    def test_rename(self, sth_prefix, connect, client) -> None:
        """Test endpoint ``/rename``"""

        sensor_node = connect
        mac_address = sensor_node["mac_address"]

        response = client.put(
            str(sth_prefix / "rename"),
            json={"mac_address": mac_address, "new_name": "Hello"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        old_name = response.json()["old_name"]
        name = response.json()["name"]
        assert name == "Hello"

        response = client.put(
            str(sth_prefix / "rename"),
            json={"mac_address": mac_address, "new_name": old_name},
        )
        assert isinstance(response.json(), dict)
        assert response.json()["old_name"] == name
        assert response.json()["name"] == old_name

    def test_read_adc(self, sth_prefix, client, connect) -> None:
        """Test endpoint ``/read-adc``"""

        response = client.get(str(sth_prefix / "read-adc"))
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

    def test_write_adc(self, sth_prefix, connect, client) -> None:
        """Test endpoint ``/write-adc``"""

        response = client.get(str(sth_prefix / "read-adc"))
        assert response.status_code == 200
        adc_configuration = response.json()

        response = client.put(
            str(sth_prefix / "write-adc"),
            json=adc_configuration,
        )

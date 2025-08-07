# -- Imports ------------------------------------------------------------------

from posixpath import join

from netaddr import EUI
from pytest import mark

# -- Tests --------------------------------------------------------------------


@mark.usefixtures("anyio_backend")
class TestSTH:

    prefix = "sth"

    async def test_root(self, client) -> None:
        """Test endpoint ``/``"""

        response = await client.get(self.prefix)

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

    async def test_connect_disconnect(
        self, get_test_sensor_node, client
    ) -> None:
        """Test endpoint ``/connect`` and ``/disconnect``"""

        # ========================
        # = Test Normal Response =
        # ========================

        node = get_test_sensor_node

        mac_address = node["mac_address"]
        response = await client.put(
            join(self.prefix, "connect"), json={"mac": mac_address}
        )
        assert response.status_code == 200
        assert response.json() is None

        await client.put(join(self.prefix, "disconnect"))

        # =======================
        # = Test Error Response =
        # =======================

        response = await client.put(
            join(self.prefix, "connect"), json={"mac": "01-02-03-04-05-06"}
        )

        assert response.status_code == 404

    async def test_rename(self, client, connect) -> None:
        """Test endpoint ``/rename``"""

        sensor_node = connect
        mac_address = sensor_node["mac_address"]

        response = await client.put(
            join(self.prefix, "rename"),
            json={"mac_address": mac_address, "new_name": "Hello"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        old_name = response.json()["old_name"]
        name = response.json()["name"]
        assert name == "Hello"

        response = await client.put(
            join(self.prefix, "rename"),
            json={"mac_address": mac_address, "new_name": old_name},
        )
        assert isinstance(response.json(), dict)
        assert response.json()["old_name"] == name
        assert response.json()["name"] == old_name

    async def test_read_adc(self, client, connect) -> None:
        """Test endpoint ``/read-adc``"""

        response = await client.get(join(self.prefix, "read-adc"))
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

    async def test_write_adc(self, client, connect) -> None:
        """Test endpoint ``/write-adc``"""

        response = await client.get(join(self.prefix, "read-adc"))
        assert response.status_code == 200
        adc_configuration = response.json()

        response = await client.put(
            join(self.prefix, "write-adc"),
            json=adc_configuration,
        )

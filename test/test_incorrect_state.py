"""Test response in incorrect state"""

# -- Imports ------------------------------------------------------------------

from pytest import mark

# -- Tests --------------------------------------------------------------------


class TestIncorrectState:
    """STH endpoint test methods"""

    @mark.hardware
    def test_stu_reset_while_connected(
        self,
        stu_prefix,
        sth_prefix,
        connect,  # pylint: disable=unused-argument
        client,
    ) -> None:
        """Test endpoint ``/reset`` while connected to a sensor device

        The reset only works without sensor device connection. The API
        disconnects the sensor device first, since a client may not know about
        the connection (e.g. after reloading the page).
        """

        response = client.put(f"{stu_prefix}/reset")
        assert response.status_code == 200

        # The sensor device is disconnected now
        response = client.put(f"{sth_prefix}/disconnect")
        assert response.status_code == 400

    @mark.hardware
    def test_sth_disconnect(self, sth_prefix, client) -> None:
        """Test response to ``STH/disconnect`` in incorrect state"""

        # Disconnect only possible after connection to sensor node
        # (not in state “STU connected”)
        response = client.put(f"{sth_prefix}/disconnect")

        assert response.status_code == 400

    @mark.hardware
    def test_sth_connect(self, sth_prefix, test_sensor_node, client) -> None:
        """Test response to ``STH/connect`` in incorrect state"""

        mac_address = test_sensor_node["mac_address"]
        response = client.put(
            f"{sth_prefix}/connect", json={"mac_address": mac_address}
        )

        # Connecting to sensor node, when already connected does not work
        response = client.put(
            f"{sth_prefix}/connect", json={"mac_address": mac_address}
        )
        assert response.status_code == 400

        response = client.put(f"{sth_prefix}/disconnect")

        assert response.status_code == 200

"""Test response in incorrect state"""

# -- Imports ------------------------------------------------------------------

from pytest import mark

# -- Tests --------------------------------------------------------------------


class TestIncorrectState:
    """STH endpoint test methods"""

    @mark.hardware
    def test_disconnect(self, sth_prefix, client) -> None:
        """Test response to ``STH/disconnect`` in incorrect state"""

        # Disconnect only possible after connection to sensor node
        # (not in state “STU connected”)
        response = client.put(f"{sth_prefix}/disconnect")

        assert response.status_code == 400

    @mark.hardware
    def test_connect(self, sth_prefix, test_sensor_node, client) -> None:
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

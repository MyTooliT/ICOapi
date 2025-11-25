"""Tests for STU endpoint"""

# -- Imports ------------------------------------------------------------------

from netaddr import EUI
from pytest import mark

# -- Tests --------------------------------------------------------------------


class TestSTU:
    """STU endpoint test methods"""

    @mark.hardware
    def test_root(self, stu_prefix, client) -> None:
        """Test endpoint ``/``"""

        response = client.get(stu_prefix)

        assert response.status_code == 200
        sth_response = response.json()[0]
        assert sth_response["device_number"] == 1
        mac_address = sth_response["mac_address"]
        # Check that MAC address is valid and assert that it is equal to (the
        # string representation) of itself
        assert EUI(mac_address) == mac_address
        assert sth_response["name"] == "STU 1"

    @mark.hardware
    def test_reset(self, stu_prefix, client) -> None:
        """Test endpoint ``/reset``"""

        response = client.put(f"{stu_prefix}/reset")

        assert response.status_code == 200
        assert response.json() is None

    def test_connected(self, stu_prefix, client) -> None:
        """Test endpoint ``/connected``"""

        response = client.get(f"{stu_prefix}/connected")
        assert response.status_code == 200
        # STU is not connected to sensor device yet
        assert response.json() is False

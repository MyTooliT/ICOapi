# -- Imports ------------------------------------------------------------------

from fastapi.testclient import TestClient
from netaddr import EUI

from icoapi.api import app

# -- Globals ------------------------------------------------------------------

client = TestClient(app)
stu_prefix = "/api/v1/stu"

# -- Tests --------------------------------------------------------------------


def test_root() -> None:
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

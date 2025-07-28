# -- Imports ------------------------------------------------------------------

from fastapi.testclient import TestClient

from icoapi.api import app

# -- Globals ------------------------------------------------------------------

client = TestClient(app)
stu_prefix = "/api/v1/stu"

# -- Tests --------------------------------------------------------------------


def test_root() -> None:
    """Test endpoint ``/``"""

    response = client.get(stu_prefix)
    assert response.status_code == 200

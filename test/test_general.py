# -- Imports ------------------------------------------------------------------

from pytest import mark

# -- Tests --------------------------------------------------------------------


@mark.usefixtures("anyio_backend")
class TestGeneral:

    async def test_state(self, state_prefix, client) -> None:
        """Test endpoint ``/state``"""

        response = await client.get(str(state_prefix))

        assert response.status_code == 200

        body = response.json()
        assert body["can_ready"] is True

        disk_capacity = body["disk_capacity"]
        assert disk_capacity["total"] >= disk_capacity["available"]
        assert disk_capacity["available"] > 0

        measurement_status = body["measurement_status"]
        for attribute in ("instructions", "name", "start_time", "tool_name"):
            assert measurement_status[attribute] is None
        assert measurement_status["running"] is False

    async def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = await client.put("/reset-can")

        assert response.status_code == 200
        assert response.json() is None

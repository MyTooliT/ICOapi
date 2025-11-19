"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from logging import getLogger

# -- Tests --------------------------------------------------------------------


class TestGeneral:
    """General endpoint test methods"""

    def test_state(self, state_prefix, client) -> None:
        """Test endpoint ``/state``"""

        response = client.get(state_prefix)

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

    def test_state_websocket(self, state_prefix, client) -> None:
        """Test WebSocket endpoint ``state``"""

        ws_url = str(client.base_url).replace("http", "ws")
        state = f"{ws_url}{state_prefix}"

        logger = getLogger(__name__)
        logger.info("Try to connect to WebSocket URL: %s", state)

        with client.websocket_connect(state):
            pass

    def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = client.put(reset_can_prefix)

        assert response.status_code == 200
        assert response.json() is None

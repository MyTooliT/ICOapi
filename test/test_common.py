"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from asyncio import TaskGroup, wait_for
from logging import getLogger

from httpx_ws import aconnect_ws
from pytest import mark

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

    @mark.anyio
    async def test_state_websocket(self, state_prefix, async_client) -> None:
        """Test WebSocket endpoint ``state``"""

        ws_url = str(async_client.base_url).replace("http", "ws")
        state = f"{ws_url}{state_prefix}"
        logger = getLogger(__name__)

        async def connect_to_websocket():
            messages = []
            logger.debug("Try to connect to WebSocket URL: %s", state)
            async with aconnect_ws(state, async_client) as state_ws:
                try:
                    while True:
                        message = await wait_for(state_ws.receive_text(), timeout=1.0)
                        messages.append(message)
                except TimeoutError:
                    pass

                return messages

        async with TaskGroup() as task_group:
            stream_data_task = task_group.create_task(connect_to_websocket())

        messages = stream_data_task.result()
        assert len(messages) >= 1

        logger.debug("Retrieved %d messages", len(stream_data_task.result()))

    def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = client.put(reset_can_prefix)

        assert response.status_code == 200
        assert response.json() is None

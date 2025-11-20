"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from asyncio import sleep, TaskGroup, wait_for
from asyncio.exceptions import CancelledError
from json import loads
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
    async def test_state_websocket(
        self, state_prefix, sth_prefix, test_sensor_node, async_client
    ) -> None:
        """Test WebSocket endpoint ``state``"""

        state = str(async_client.base_url).replace("http", "ws") + state_prefix
        logger = getLogger(__name__)

        async def get_websocket_messages():
            messages = []
            logger.debug("Try to connect to WebSocket URL: %s", state)
            async with aconnect_ws(state, async_client) as state_ws:
                try:
                    while True:
                        message = await wait_for(
                            state_ws.receive_text(), timeout=20.0
                        )
                        messages.append(loads(message))
                        logger.debug(
                            "Retrieved WebSocket message: %s", message
                        )
                except CancelledError, TimeoutError:
                    pass

                return messages

        async def connect_and_disconnect():
            mac_address = test_sensor_node["mac_address"]
            logger.debug("Connect to sensor node")
            await async_client.put(
                f"{sth_prefix}/connect", json={"mac_address": mac_address}
            )
            await sleep(0)
            logger.debug("Disconnect from sensor node")
            await async_client.put(f"{sth_prefix}/disconnect")
            await sleep(0)

        async with TaskGroup() as task_group:
            messages_task = task_group.create_task(get_websocket_messages())
            connection_task = task_group.create_task(connect_and_disconnect())
            await connection_task
            messages_task.cancel()

        messages = messages_task.result()
        assert len(messages) >= 1

        logger.debug(
            "Retrieved %d message%s",
            len(messages),
            "s" if len(messages) > 1 else "",
        )
        for message_number, message in enumerate(messages, start=1):
            assert "message" in message
            assert message["message"] == "state"
            assert "data" in message
            logger.debug("Message %d: %s", message_number, message)

    def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = client.put(reset_can_prefix)

        assert response.status_code == 200
        assert response.json() is None

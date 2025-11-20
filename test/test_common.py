"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from asyncio import sleep, TaskGroup, wait_for
from asyncio.exceptions import CancelledError
from logging import getLogger

from netaddr import EUI
from httpx import AsyncClient
from httpx_ws import aconnect_ws, AsyncWebSocketSession
from pytest import mark

# -- Functions ----------------------------------------------------------------


async def get_websocket_messages(ws: AsyncWebSocketSession):
    """Retrieve messages from WebSocket"""

    logger = getLogger(__name__)

    messages = []
    try:
        while True:
            message = await wait_for(ws.receive_json(), timeout=20.0)
            messages.append(message)
            logger.debug("Retrieved WebSocket message: %s", message)
    except (CancelledError, TimeoutError):
        pass

    return messages


async def connect_and_disconnect_sensor_node(
    sth_prefix: str,
    async_client: AsyncClient,
    ws_state: AsyncWebSocketSession,
    mac_address: EUI,
):
    """Connect to and than disconnect from sensor node

    Retrieves current state information from state WebSocket ``ws_state`` after
    connection changes.
    """

    logger = getLogger(__name__)

    logger.debug("Connect to sensor node")
    await async_client.put(
        f"{sth_prefix}/connect", json={"mac_address": mac_address}
    )
    get_state = {"message": "get_state"}
    await ws_state.send_json(get_state)
    logger.debug("Disconnect from sensor node")
    await async_client.put(f"{sth_prefix}/disconnect")
    await ws_state.send_json(get_state)
    await sleep(1)  # Wait until new state message is written to socket


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
        mac_address = test_sensor_node["mac_address"]

        ws: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as ws:
            async with TaskGroup() as task_group:
                messages_task = task_group.create_task(
                    get_websocket_messages(ws)
                )
                connection_task = task_group.create_task(
                    connect_and_disconnect_sensor_node(
                        sth_prefix, async_client, ws, mac_address
                    )
                )
                await connection_task
                messages_task.cancel()

        messages = messages_task.result()
        assert len(messages) >= 2

        logger.debug("Retrieved %d messages", len(messages))
        for message_number, message in enumerate(messages, start=1):
            assert "message" in message
            assert message["message"] == "state"
            assert "data" in message
            assert "can_ready" in message["data"]
            assert message["data"]["can_ready"] is True
            logger.debug("Message %d: %s", message_number, message)

    def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = client.put(reset_can_prefix)

        assert response.status_code == 200
        assert response.json() is None

"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from asyncio import TaskGroup, wait_for
from logging import getLogger
from typing import Any

from netaddr import EUI
from httpx import AsyncClient
from httpx_ws import aconnect_ws, AsyncWebSocketSession
from pytest import mark

# -- Functions ----------------------------------------------------------------


async def get_websocket_messages(
    ws: AsyncWebSocketSession, message_count: int
) -> list[dict[Any, Any]]:
    """Retrieve JSON messages from WebSocket

    Args:

        ws:

            The WebSocket session that should be used to retrieve messages

        message_count:

            The number of messages that should be retrieved by this function

    Returns:

        The JSON messages retrieved from the WebSocket

    Raises:

        TimeoutError if the time between two sent messages is larger than 20 s

    """

    logger = getLogger(__name__)

    messages: list[dict[Any, Any]] = []
    while len(messages) < message_count:
        message = await wait_for(ws.receive_json(), timeout=20.0)
        messages.append(message)
        logger.debug("Retrieved WebSocket message: %s", message)

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


# -- Tests --------------------------------------------------------------------


class TestGeneral:
    """General endpoint test methods"""

    def test_state_disconnected(self, state_prefix, client) -> None:
        """Test endpoint ``/state`` while disconnected from sensor node"""

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

    def test_state_measurement(
        self, state_prefix, measurement, client
    ) -> None:
        """Test endpoint ``/state`` while measurement is running"""

        response = client.get(state_prefix)

        assert response.status_code == 200

        body = response.json()
        assert body["can_ready"] is True

        measurement_status = body["measurement_status"]
        assert measurement_status["running"] is True

    @mark.anyio
    @mark.hardware
    async def test_state_websocket(
        self, state_prefix, sth_prefix, test_sensor_node, async_client
    ) -> None:
        """Test WebSocket endpoint ``state``"""

        state = str(async_client.base_url).replace("http", "ws") + state_prefix
        logger = getLogger(__name__)
        mac_address = test_sensor_node["mac_address"]

        # Connect to and disconnect from sensor node. Currently this will not
        # change the message reported by the `state` WebSocket significantly,
        # which makes this test probably less useful than it should be.
        # However, changing the state (for example by starting a measurement)
        # seems to be too much work (to me 😅) for testing the WebSocket for
        # now.
        ws: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as ws:
            expected_number_messages = 3
            async with TaskGroup() as task_group:
                messages_task = task_group.create_task(
                    get_websocket_messages(ws, expected_number_messages)
                )
                task_group.create_task(
                    connect_and_disconnect_sensor_node(
                        sth_prefix, async_client, ws, mac_address
                    )
                )
                await messages_task

        messages = messages_task.result()
        assert len(messages) == expected_number_messages

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

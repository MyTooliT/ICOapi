"""Tests for misc endpoints"""

# -- Imports ------------------------------------------------------------------

from asyncio import TaskGroup, sleep, wait_for
from datetime import datetime, timedelta
from logging import getLogger
from typing import Any

from httpx_ws import aconnect_ws, AsyncWebSocketSession
from pytest import fixture, mark, raises

from icoapi.models.globals import TridentHandler, get_messenger

# -- Functions ----------------------------------------------------------------


def get_state_url(state_prefix: str, async_client) -> str:
    """Get URL of the state WebSocket"""

    return str(async_client.base_url).replace("http", "ws") + state_prefix


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


def check_state_measurement_data(
    data,
    sensor_node_info: dict[str, Any],
    measurement_instructions_single_channel: dict[str, Any],
):
    """Check if the given state data for a running measurement is correct"""

    assert data["can_ready"] is True

    measurement_status = data["measurement_status"]
    assert measurement_status["running"] is True
    assert isinstance(measurement_status["name"], str)
    assert len(measurement_status["name"]) > 0

    assert isinstance(measurement_status["start_time"], str)
    start_time = datetime.fromisoformat(measurement_status["start_time"])
    current_time = datetime.now()
    assert current_time - timedelta(seconds=30) <= start_time <= current_time

    assert measurement_status["tool_name"] == sensor_node_info["name"]
    instructions = measurement_status["instructions"]
    assert isinstance(instructions, dict)
    assert (
        instructions["name"] == measurement_instructions_single_channel["name"]
    )
    assert instructions["mac_address"] == sensor_node_info["mac_address"]
    assert instructions["time"] > 0

    first_channel = instructions["first"]
    assert isinstance(first_channel, dict)
    assert (
        first_channel["sensor_id"]
        == measurement_instructions_single_channel["first"]["sensor_id"]
    )

    for number in ("second", "third"):
        channel = instructions[number]
        assert isinstance(channel, dict)
        assert channel["sensor_id"] is None


# -- Tests --------------------------------------------------------------------


class TestCommon:
    """Common endpoint test methods"""

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

    @mark.hardware
    def test_state_measurement(
        self,
        state_prefix,
        test_sensor_node,
        measurement_single_channel,
        client,
    ) -> None:
        """Test endpoint ``/state`` while measurement is running"""

        response = client.get(state_prefix)

        assert response.status_code == 200

        body = response.json()
        check_state_measurement_data(
            body, test_sensor_node, measurement_single_channel
        )

    async def test_state_websocket_new_client_only(
        self, state_prefix, async_client
    ) -> None:
        """Check that only a newly connected client receives the state"""

        state = str(async_client.base_url).replace("http", "ws") + state_prefix

        first: AsyncWebSocketSession
        second: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as first:
            messages = await get_websocket_messages(first, 1)
            assert messages[0]["message"] == "state"

            async with aconnect_ws(state, async_client) as second:
                messages = await get_websocket_messages(second, 1)
                assert messages[0]["message"] == "state"

                with raises(TimeoutError):
                    await wait_for(first.receive_json(), timeout=0.5)

    @mark.hardware
    async def test_state_websocket_connect(
        self, state_prefix, async_client
    ) -> None:
        """Check that WebSocket endpoint ``state`` sends state on connect"""

        state = str(async_client.base_url).replace("http", "ws") + state_prefix
        logger = getLogger(__name__)

        ws: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as ws:
            expected_number_messages = 1
            messages = await get_websocket_messages(
                ws, expected_number_messages
            )

        assert len(messages) == expected_number_messages

        logger.debug("Retrieved %d messages", len(messages))
        for message_number, message in enumerate(messages, start=1):
            assert "message" in message
            assert message["message"] == "state"
            assert "data" in message
            assert "can_ready" in message["data"]
            assert message["data"]["can_ready"] is True
            logger.debug("Message %d: %s", message_number, message)

    @mark.hardware
    async def test_state_websocket_measurement(
        self,
        state_prefix,
        test_sensor_node,
        measurement_single_channel,
        async_client,
    ) -> None:
        """Check WebSocket endpoint ``state`` while measurement is active"""

        state = str(async_client.base_url).replace("http", "ws") + state_prefix

        ws: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as ws:
            expected_number_messages = 1
            async with TaskGroup() as task_group:
                messages_task = task_group.create_task(
                    get_websocket_messages(ws, expected_number_messages)
                )
                await messages_task

        messages = messages_task.result()
        assert len(messages) == expected_number_messages
        check_state_measurement_data(
            messages.pop()["data"],
            test_sensor_node,
            measurement_single_channel,
        )

    def test_reset_can(self, reset_can_prefix, client) -> None:
        """Test endpoint ``reset-can``"""

        response = client.put(reset_can_prefix)

        assert response.status_code == 200
        assert response.json() is None


class TestStateWebSocket:
    """Tests for the state WebSocket that do not need any hardware

    The tests only use what a client of the WebSocket sees. State changes are
    triggered via the cloud state (``TridentHandler``), which pushes state
    updates without any connected hardware.
    """

    @fixture(autouse=True)
    async def reset_cloud_state(self):
        """Start and end each test with the default cloud state"""

        await TridentHandler.reset()
        yield
        await TridentHandler.reset()

    async def test_payload(self, state_prefix, async_client) -> None:
        """The state message should contain the same data as ``GET /state``"""

        ws: AsyncWebSocketSession
        async with aconnect_ws(
            get_state_url(state_prefix, async_client), async_client
        ) as ws:
            messages = await get_websocket_messages(ws, 1)

        message = messages[0]
        assert message["message"] == "state"
        data = message["data"]

        assert isinstance(data["can_ready"], bool)
        assert {"total", "available"} <= set(data["disk_capacity"])
        assert data["cloud"]["enabled"] is False
        assert data["cloud"]["healthy"] is False
        measurement_status = data["measurement_status"]
        assert measurement_status["running"] is False
        for attribute in ("instructions", "name", "start_time", "tool_name"):
            assert measurement_status[attribute] is None

        response = await async_client.get(state_prefix)
        assert response.status_code == 200
        body = response.json()
        for key in ("can_ready", "cloud", "measurement_status"):
            assert data[key] == body[key]

    async def test_late_subscriber_gets_current_state(
        self, state_prefix, async_client
    ) -> None:
        """A client connecting later should get the latest state

        Pushing state while no client is connected must not fail.
        """

        await TridentHandler.set_enabled()
        await get_messenger().push_messenger_update()

        ws: AsyncWebSocketSession
        async with aconnect_ws(
            get_state_url(state_prefix, async_client), async_client
        ) as ws:
            messages = await get_websocket_messages(ws, 1)

        assert messages[0]["data"]["cloud"]["enabled"] is True

    async def test_updates_arrive_in_order(
        self, state_prefix, async_client
    ) -> None:
        """State updates should be received in the order they happened"""

        ws: AsyncWebSocketSession
        async with aconnect_ws(
            get_state_url(state_prefix, async_client), async_client
        ) as ws:
            # Wait for initial message, to make sure the client is registered
            await get_websocket_messages(ws, 1)

            await TridentHandler.set_enabled()
            await TridentHandler.set_health(True)
            await TridentHandler.set_disabled()

            messages = await get_websocket_messages(ws, 3)

        assert [
            (message["data"]["cloud"]["enabled"], message["data"]["cloud"]["healthy"])
            for message in messages
        ] == [(True, False), (True, True), (False, True)]

    async def test_disconnected_client_does_not_affect_others(
        self, state_prefix, async_client
    ) -> None:
        """Updates should still reach clients after another one disconnected"""

        state = get_state_url(state_prefix, async_client)

        first: AsyncWebSocketSession
        second: AsyncWebSocketSession
        async with aconnect_ws(state, async_client) as first:
            await get_websocket_messages(first, 1)

            async with aconnect_ws(state, async_client) as second:
                await get_websocket_messages(second, 1)

            await TridentHandler.set_enabled()
            messages = await get_websocket_messages(first, 1)

        assert messages[0]["data"]["cloud"]["enabled"] is True

    async def test_client_messages_are_ignored(
        self, state_prefix, async_client
    ) -> None:
        """Messages sent by the client should be ignored

        They neither trigger a response nor should they break the connection.
        """

        ws: AsyncWebSocketSession
        async with aconnect_ws(
            get_state_url(state_prefix, async_client), async_client
        ) as ws:
            await get_websocket_messages(ws, 1)

            await ws.send_json({"message": "get_state"})
            await ws.send_text("This is not JSON")
            await ws.send_bytes(b"\x00\x01")
            # Give the server the chance to process the messages
            await sleep(0.2)

            await TridentHandler.set_enabled()
            messages = await get_websocket_messages(ws, 1)

        # The first message after the client messages must be the pushed
        # update, not a response to one of the client messages
        assert messages[0]["data"]["cloud"]["enabled"] is True

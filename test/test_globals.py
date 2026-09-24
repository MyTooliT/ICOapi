"""Tests for global state helpers and event buses"""

# -- Imports ------------------------------------------------------------------

import asyncio
from typing import Any, cast

from starlette.websockets import WebSocket

from icoapi.models.event_bus import (
    Channel,
    CompositeEventBus,
    EventBus,
    WebSocketEventBus,
)
from icoapi.models.globals import GeneralMessenger, build_system_state
from icoapi.models.models import SystemStateModel

# -- Classes --------------------------------------------------------------------


# pylint: disable-next=too-few-public-methods
class FakeWebSocket:
    """Minimal WebSocket double that records sent JSON messages"""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.messages: list[dict] = []
        self.fail_after = fail_after
        self.busy = False
        self.send_attempts = 0

    async def send_json(self, data) -> None:
        """Record a JSON message, failing after the configured send count"""

        self.send_attempts += 1
        assert not self.busy, "Concurrent send on the same WebSocket"
        self.busy = True
        try:
            await asyncio.sleep(0)
            if (
                self.fail_after is not None
                and len(self.messages) >= self.fail_after
            ):
                raise RuntimeError("Simulated broken connection")
            self.messages.append(data)
        finally:
            self.busy = False


def as_websocket(fake: FakeWebSocket) -> WebSocket:
    """Use a ``FakeWebSocket`` double as ``WebSocket``

    ``FakeWebSocket`` only implements the ``send_json`` method that
    ``WebSocketEventBus`` actually calls, so it is cast to ``WebSocket`` for
    the type checker rather than subclassing the real, ASGI-backed class.
    """

    return cast(WebSocket, cast(object, fake))


class RecordingEventBus(EventBus):
    """Event bus that records everything published"""

    def __init__(self) -> None:
        self.states: list[SystemStateModel] = []
        self.events: list[tuple[Channel, dict[str, Any]]] = []
        self.closed = False

    async def publish_state(self, state: SystemStateModel) -> None:
        self.states.append(state)

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        self.events.append((channel, payload))

    async def close(self) -> None:
        self.closed = True


class FailingEventBus(EventBus):
    """Event bus that fails to publish anything"""

    async def publish_state(self, state: SystemStateModel) -> None:
        raise ConnectionError("Simulated broken bus")

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        raise ConnectionError("Simulated broken bus")

    async def close(self) -> None:
        raise ConnectionError("Simulated broken bus")


class BlockedEventBus(RecordingEventBus):
    """Event bus that does not finish publishing until it is released"""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def publish_state(self, state: SystemStateModel) -> None:
        await self.release.wait()
        await super().publish_state(state)


class TestWebSocketEventBus:
    """Tests for ``WebSocketEventBus``

    These are regression tests for a bug where overlapping updates
    (triggered by several state attributes being set in quick succession) sent
    to the same WebSocket concurrently, which crashed the underlying
    connection with an ``AssertionError``.
    """

    async def test_concurrent_pushes_do_not_interleave_sends(self) -> None:
        """Concurrent pushes must be serialized per client"""

        bus = WebSocketEventBus()
        client = FakeWebSocket()
        bus.add_client(as_websocket(client))
        state = await build_system_state()

        push_count = 5
        await asyncio.gather(
            *(bus.publish_state(state) for _ in range(push_count))
        )

        assert len(client.messages) == push_count

    async def test_broken_client_is_dropped_without_blocking_others(
        self,
    ) -> None:
        """A failing client must not stop the broadcast to other clients,

        and must be dropped so it is not retried on the next broadcast.
        """

        bus = WebSocketEventBus()
        broken = FakeWebSocket(fail_after=0)
        healthy = FakeWebSocket()
        bus.add_client(as_websocket(broken))
        bus.add_client(as_websocket(healthy))
        state = await build_system_state()

        await bus.publish_state(state)
        await bus.publish_state(state)

        assert broken.send_attempts == 1
        assert len(healthy.messages) == 2

    async def test_send_state_to_only_reaches_given_client(self) -> None:
        """Sending state to a single client must not reach other clients"""

        bus = WebSocketEventBus()
        new_client = FakeWebSocket()
        other_client = FakeWebSocket()
        bus.add_client(as_websocket(other_client))
        bus.add_client(as_websocket(new_client))

        await bus.send_state_to(
            as_websocket(new_client), await build_system_state()
        )

        assert len(new_client.messages) == 1
        assert new_client.messages[0]["message"] == "state"
        assert "can_ready" in new_client.messages[0]["data"]
        assert not other_client.messages

    async def test_send_state_to_is_serialized_with_pushes(self) -> None:
        """Sending state to a single client must not interleave with pushes"""

        bus = WebSocketEventBus()
        client = FakeWebSocket()
        bus.add_client(as_websocket(client))
        state = await build_system_state()

        push_count = 3
        await asyncio.gather(
            bus.send_state_to(as_websocket(client), state),
            *(bus.publish_state(state) for _ in range(push_count)),
        )

        assert len(client.messages) == push_count + 1

    async def test_send_state_to_broken_client_is_dropped(self) -> None:
        """A client that fails to receive the initial state is dropped"""

        bus = WebSocketEventBus()
        broken = FakeWebSocket(fail_after=0)
        healthy = FakeWebSocket()
        bus.add_client(as_websocket(broken))
        bus.add_client(as_websocket(healthy))
        state = await build_system_state()

        await bus.send_state_to(as_websocket(broken), state)
        await bus.publish_state(state)

        assert broken.send_attempts == 1
        assert len(healthy.messages) == 1

    async def test_removed_client_receives_nothing(self) -> None:
        """A removed client must not receive updates anymore"""

        bus = WebSocketEventBus()
        removed = FakeWebSocket()
        kept = FakeWebSocket()
        bus.add_client(as_websocket(removed))
        bus.add_client(as_websocket(kept))

        bus.remove_client(as_websocket(removed))
        await bus.publish_state(await build_system_state())

        assert not removed.messages
        assert len(kept.messages) == 1

    async def test_events_are_ignored(self) -> None:
        """WebSocket clients only receive the state, not events"""

        bus = WebSocketEventBus()
        client = FakeWebSocket()
        bus.add_client(as_websocket(client))

        await bus.publish_event(Channel.RECORDING_FINISHED, {"name": "test"})

        assert not client.messages

    async def test_close_forgets_clients(self) -> None:
        """A closed bus should not publish to old clients"""

        bus = WebSocketEventBus()
        client = FakeWebSocket()
        bus.add_client(as_websocket(client))

        await bus.close()
        await bus.publish_state(await build_system_state())

        assert not client.messages


class TestCompositeEventBus:
    """Tests for ``CompositeEventBus``"""

    async def test_publishes_to_all_buses(self) -> None:
        """State and events must reach all buses"""

        first = RecordingEventBus()
        second = RecordingEventBus()
        bus = CompositeEventBus([first])
        bus.add_bus(second)
        state = await build_system_state()

        await bus.publish_state(state)
        await bus.publish_event(Channel.RECORDING_FAILED, {"name": "test"})

        for recording_bus in (first, second):
            assert recording_bus.states == [state]
            assert recording_bus.events == [
                (Channel.RECORDING_FAILED, {"name": "test"})
            ]

    async def test_failing_bus_does_not_affect_others(self) -> None:
        """A bus that fails must neither raise nor block the other buses"""

        healthy = RecordingEventBus()
        bus = CompositeEventBus([FailingEventBus(), healthy])
        state = await build_system_state()

        await bus.publish_state(state)
        await bus.publish_event(Channel.RECORDING_FINISHED, {})
        await bus.close()

        assert healthy.states == [state]
        assert healthy.events == [(Channel.RECORDING_FINISHED, {})]
        assert healthy.closed

    async def test_blocked_bus_does_not_delay_others(self) -> None:
        """Buses must receive the state independent of each other"""

        blocked = BlockedEventBus()
        healthy = RecordingEventBus()
        bus = CompositeEventBus([blocked, healthy])
        state = await build_system_state()

        task = asyncio.create_task(bus.publish_state(state))
        await asyncio.sleep(0.05)

        assert healthy.states == [state]
        assert not blocked.states
        assert not task.done()

        blocked.release.set()
        await task
        assert blocked.states == [state]


class TestGeneralMessenger:
    """Tests for ``GeneralMessenger``"""

    async def test_added_bus_receives_state_and_events(self) -> None:
        """Added buses must receive everything until they are removed"""

        recording = RecordingEventBus()
        GeneralMessenger.add_bus(recording)
        try:
            await GeneralMessenger.push_messenger_update()
            await GeneralMessenger.publish_event(
                Channel.RECORDING_FINISHED, {"name": "test.hdf5"}
            )
        finally:
            GeneralMessenger.remove_bus(recording)
        await GeneralMessenger.push_messenger_update()
        await GeneralMessenger.publish_event(Channel.RECORDING_FAILED, {})

        assert len(recording.states) == 1
        assert recording.events == [
            (Channel.RECORDING_FINISHED, {"name": "test.hdf5"})
        ]

    def setup_method(self) -> None:
        """Start each test without WebSocket clients"""

        GeneralMessenger.websocket_bus().clear_clients()

    def teardown_method(self) -> None:
        """Leave no WebSocket clients behind for other tests"""

        GeneralMessenger.websocket_bus().clear_clients()

    async def test_push_messenger_update_reaches_websocket_clients(
        self,
    ) -> None:
        """The current state must be published to WebSocket clients"""

        client = FakeWebSocket()
        GeneralMessenger.websocket_bus().add_client(as_websocket(client))

        await GeneralMessenger.push_messenger_update()

        assert len(client.messages) == 1
        message = client.messages[0]
        assert message["message"] == "state"
        assert {"can_ready", "disk_capacity", "cloud", "measurement_status"} <= (
            set(message["data"])
        )

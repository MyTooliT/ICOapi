"""Tests for sending live data to clients"""

# -- Imports ------------------------------------------------------------------

import asyncio
from time import monotonic
from typing import Any

from icoapi.models.globals import MeasurementState
from icoapi.scripts import live_stream
from icoapi.scripts.live_stream import (
    MAX_PENDING_ROWS,
    configure_client,
    flush_clients,
    send_to_clients,
)

# -- Classes ------------------------------------------------------------------


class Client:
    """WebSocket client that collects everything it gets"""

    client = "test"

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def send_json(self, data: Any) -> None:
        """Receive message"""

        self.messages.append(data)

    @property
    def rows(self) -> list[dict]:
        """All points that were received"""

        return [row for message in self.messages for row in message]


def state_with(*clients: Client) -> MeasurementState:
    """Get a measurement state that has clients"""

    state = MeasurementState()
    state.clients.extend(clients)  # type: ignore[arg-type]
    return state


def rows(source: str, rate: float, seconds: float) -> list[dict]:
    """Get the points of a source that sends ``rate`` points per second"""

    return [
        {"source": source, "timestamp": number / rate, "first": number}
        for number in range(int(rate * seconds))
    ]


# -- Tests --------------------------------------------------------------------


class TestSending:
    """Test that the streams of all units can send to the same client"""

    async def test_one_message_at_a_time(self) -> None:
        """Streams that send at the same time wait for each other"""

        class SlowClient(Client):
            """Client that fails if it is used by two senders at once"""

            busy = False

            async def send_json(self, data: Any) -> None:
                assert not self.busy, "Two senders at once"
                self.busy = True
                await asyncio.sleep(0.01)
                await super().send_json(data)
                self.busy = False

        client = SlowClient()
        state = state_with(client)

        await asyncio.gather(
            *(
                send_to_clients(state, [{"source": f"STH-{number}"}])
                for number in range(3)
            )
        )
        await flush_clients(state)

        assert [row["source"] for row in client.rows] == [
            "STH-0",
            "STH-1",
            "STH-2",
        ]
        assert state.clients == [client]

    async def test_failing_client_is_dropped(self) -> None:
        """A client that fails does not stop the others or the measurement"""

        class BrokenClient(Client):
            """Client whose connection fails"""

            async def send_json(self, data: Any) -> None:
                raise AssertionError

        broken, good = BrokenClient(), Client()
        state = state_with(broken, good)

        await send_to_clients(state, [{"source": "STH"}])
        await flush_clients(state)

        assert state.clients == [good]
        assert good.rows == [{"source": "STH"}]

    async def test_slow_client_does_not_hold_the_streams_up(self) -> None:
        """Sending does not wait for a client; the oldest points are dropped"""

        release = asyncio.Event()

        class StuckClient(Client):
            """Client that does not receive anything for a while"""

            async def send_json(self, data: Any) -> None:
                await release.wait()
                await super().send_json(data)

        client = StuckClient()
        state = state_with(client)
        total = MAX_PENDING_ROWS + 5000

        # Returns at once although the client receives nothing
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    send_to_clients(state, [{"number": number}])
                    for number in range(total)
                )
            ),
            timeout=5,
        )
        release.set()
        await flush_clients(state)

        numbers = [row["number"] for row in client.rows]
        assert numbers == sorted(numbers)
        assert numbers[-1] == total - 1
        assert len(numbers) <= MAX_PENDING_ROWS + 1
        assert numbers[0] > 0


class TestSettings:
    """Test what a client can ask for"""

    async def test_rate_is_per_source(self) -> None:
        """A client gets the points per second it asked for from every unit"""

        client = Client()
        configure_client(client, rate=60, updates=None)
        state = state_with(client)

        for first, second in zip(
            rows("A", 3175, 2), rows("B", 3175, 2), strict=True
        ):
            await send_to_clients(state, [first, second])
        # Data loss has no timestamp and always arrives
        await send_to_clients(
            state, [{"source": "A", "timestamp": None, "dataloss": 0.5}]
        )
        await flush_clients(state)

        for source in ("A", "B"):
            points = [
                row
                for row in client.rows
                if row["source"] == source and row["timestamp"] is not None
            ]
            assert 118 <= len(points) <= 122  # 2 seconds with 60 points
        assert any(row.get("dataloss") == 0.5 for row in client.rows)

    async def test_all_points_without_rate(self) -> None:
        """Clients that do not ask for a rate get every point"""

        client = Client()
        state = state_with(client)

        await send_to_clients(state, rows("A", 1000, 1))
        await flush_clients(state)

        assert len(client.rows) == 1000

    async def test_updates_are_collected(self) -> None:
        """Points are sent together if the client wants fewer updates"""

        client = Client()
        configure_client(client, rate=None, updates=20)
        state = state_with(client)

        start = monotonic()
        for number in range(200):
            await send_to_clients(
                state, [{"source": "A", "timestamp": number}]
            )
            await asyncio.sleep(0.001)
        await flush_clients(state)
        duration = monotonic() - start

        assert len(client.rows) == 200
        # At most 20 messages per second (plus the first one and the flush).
        # The duration depends on the timer resolution of the system (about
        # 15 ms on Windows), so it is measured instead of assumed.
        assert len(client.messages) <= 20 * duration + 3
        assert len(client.messages) < 200

    async def test_stream_route_takes_the_settings(
        self, monkeypatch: Any
    ) -> None:
        """The client says what it wants when it connects"""

        from fastapi.testclient import TestClient

        from icoapi.api import app

        seen: list[Any] = []
        original = live_stream.configure_client

        def spy(
            client: Any, rate: float | None, updates: float | None
        ) -> None:
            seen.append((rate, updates))
            original(client, rate, updates)

        monkeypatch.setattr(
            "icoapi.routers.measurement_routes.configure_client", spy
        )
        # No ``with``: this would run the lifespan of the application, which
        # closes the CAN connection that the hardware tests share.
        client = TestClient(app)
        with client.websocket_connect(
            "/api/v1/measurement/stream?rate=60&updates=30"
        ):
            pass

        assert seen == [(60, 30)]

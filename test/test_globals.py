"""Tests for global state helpers"""

# -- Imports ------------------------------------------------------------------

import asyncio
from typing import cast

from starlette.websockets import WebSocket

from icoapi.models.globals import GeneralMessenger

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


def add_fake_messenger(fake: FakeWebSocket) -> None:
    """Register a ``FakeWebSocket`` double as a messenger client

    ``FakeWebSocket`` only implements the ``send_json`` method that
    ``GeneralMessenger`` actually calls, so it is cast to ``WebSocket`` for
    the type checker rather than subclassing the real, ASGI-backed class.
    """

    GeneralMessenger.add_messenger(cast(WebSocket, cast(object, fake)))


class TestGeneralMessenger:
    """Tests for ``GeneralMessenger`` broadcast behaviour

    These are regression tests for a bug where overlapping calls to
    ``push_messenger_update`` (triggered by several state attributes being
    set in quick succession) sent to the same WebSocket concurrently, which
    crashed the underlying connection with an ``AssertionError``.
    """

    def setup_method(self) -> None:
        """Start each test with an empty messenger list"""

        GeneralMessenger.clear_messengers()

    def teardown_method(self) -> None:
        """Leave no messenger clients behind for other tests"""

        GeneralMessenger.clear_messengers()

    async def test_concurrent_pushes_do_not_interleave_sends(self) -> None:
        """Concurrent pushes must be serialized per client"""

        client = FakeWebSocket()
        add_fake_messenger(client)

        push_count = 5
        await asyncio.gather(
            *(
                GeneralMessenger.push_messenger_update()
                for _ in range(push_count)
            )
        )

        assert len(client.messages) == push_count

    async def test_broken_client_is_dropped_without_blocking_others(
        self,
    ) -> None:
        """A failing client must not stop the broadcast to other clients,

        and must be dropped so it is not retried on the next broadcast.
        """

        broken = FakeWebSocket(fail_after=0)
        healthy = FakeWebSocket()
        add_fake_messenger(broken)
        add_fake_messenger(healthy)

        await GeneralMessenger.push_messenger_update()
        await GeneralMessenger.push_messenger_update()

        assert broken.send_attempts == 1
        assert len(healthy.messages) == 2

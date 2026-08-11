"""Tests for global state helpers"""

# -- Imports ------------------------------------------------------------------

import asyncio

from icoapi.models.globals import GeneralMessenger

# -- Classes --------------------------------------------------------------------


class FakeWebSocket:
    """Minimal WebSocket double that records sent JSON messages"""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.messages: list[dict] = []
        self.fail_after = fail_after
        self.busy = False

    async def send_json(self, data) -> None:
        """Record a JSON message, failing after the configured send count"""

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


class TestGeneralMessenger:
    """Tests for ``GeneralMessenger`` broadcast behaviour

    These are regression tests for a bug where overlapping calls to
    ``push_messenger_update`` (triggered by several state attributes being
    set in quick succession) sent to the same WebSocket concurrently, which
    crashed the underlying connection with an ``AssertionError``.
    """

    def setup_method(self) -> None:
        GeneralMessenger._clients.clear()

    def teardown_method(self) -> None:
        GeneralMessenger._clients.clear()

    async def test_concurrent_pushes_do_not_interleave_sends(self) -> None:
        """Concurrent pushes must be serialized per client"""

        client = FakeWebSocket()
        GeneralMessenger.add_messenger(client)

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
        """A failing client must not stop the broadcast to other clients"""

        broken = FakeWebSocket(fail_after=0)
        healthy = FakeWebSocket()
        GeneralMessenger.add_messenger(broken)
        GeneralMessenger.add_messenger(healthy)

        await GeneralMessenger.push_messenger_update()

        assert broken not in GeneralMessenger._clients
        assert healthy in GeneralMessenger._clients
        assert len(healthy.messages) == 1

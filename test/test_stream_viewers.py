"""Test that the people who watch a measurement can not stop it

A browser that shows the live data (``/measurement/stream``) is only a viewer.
It may close the stream at any moment (e.g. “Hide Stream” in ICOweb) or lose
its connection. Depending on the moment, sending to such a client raises
``RuntimeError`` or ``WebSocketDisconnect``. Neither may end the measurement:
the data is written to the file regardless of who is watching.
"""


# -- Imports ------------------------------------------------------------------

from typing import Any

from pytest import mark
from starlette.websockets import WebSocketDisconnect

from icoapi.models.globals import MeasurementState
from icoapi.scripts.measurement import (
    notify_clients_of_measurement_error,
    send_dataloss,
    send_json_to_clients,
)

# -- Classes ------------------------------------------------------------------


class Client:
    """WebSocket client that collects everything it gets"""

    client = "good"

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def send_json(self, data: Any) -> None:
        """Receive message"""

        self.messages.append(data)


class GoneClient(Client):
    """WebSocket client whose connection is gone"""

    client = "gone"

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def send_json(self, data: Any) -> None:
        """Fail like a closed WebSocket"""

        raise self.error


def state_with(*clients: Client) -> MeasurementState:
    """Get a measurement state that has clients"""

    state = MeasurementState()
    state.clients.extend(clients)  # type: ignore[arg-type]
    return state


# -- Tests --------------------------------------------------------------------

DISCONNECTS = [
    # Sending to a socket that is closing (the case that ended measurements)
    WebSocketDisconnect(1006),
    # Sending to a socket that is closed
    RuntimeError('Cannot call "send" once a close message has been sent.'),
    ConnectionResetError(),
    OSError(),
]


class TestViewersCanNotStopTheMeasurement:
    """Test sending to clients that are gone"""

    @mark.parametrize("error", DISCONNECTS, ids=type)
    async def test_gone_client_is_dropped(self, error: BaseException) -> None:
        """A client that is gone is dropped, the others still get the data"""

        gone, good = GoneClient(error), Client()
        state = state_with(gone, good)

        await send_json_to_clients(state, [{"first": 1}], "data")

        assert state.clients == [good]
        assert good.messages == [[{"first": 1}]]

    async def test_clients_after_a_gone_one_get_the_data(self) -> None:
        """A failing client does not keep the following ones from the data"""

        first, gone, last = (
            Client(),
            GoneClient(WebSocketDisconnect()),
            Client(),
        )
        state = state_with(first, gone, last)

        await send_json_to_clients(state, {"a": 1}, "data")

        assert first.messages == last.messages == [{"a": 1}]
        assert state.clients == [first, last]

    async def test_client_that_leaves_while_sending(self) -> None:
        """A client removes itself from the list as soon as it disconnects"""

        state = MeasurementState()

        class LeavingClient(Client):
            """Client that disconnects while the message is sent"""

            client = "leaving"

            async def send_json(self, data: Any) -> None:
                state.clients.remove(self)  # type: ignore[arg-type]
                raise WebSocketDisconnect(1001)

        leaving, good = LeavingClient(), Client()
        state.clients.extend([leaving, good])  # type: ignore[list-item]

        await send_json_to_clients(state, {"a": 1}, "data")

        assert state.clients == [good]
        assert good.messages == [{"a": 1}]

    async def test_dataloss_does_not_fail(self) -> None:
        """Dataloss is sent once per second: a gone client is no problem"""

        gone, good = GoneClient(WebSocketDisconnect()), Client()
        state = state_with(gone, good)

        await send_dataloss(state, 0.5)

        assert state.clients == [good]
        assert good.messages[0][0]["dataloss"] == 0.5

    async def test_error_notification_does_not_fail(self) -> None:
        """Telling clients about a failed measurement must not fail itself"""

        gone, good = GoneClient(WebSocketDisconnect()), Client()
        state = state_with(gone, good)

        await notify_clients_of_measurement_error(state, ValueError("broken"))

        assert good.messages == [
            {"error": True, "type": "ValueError", "message": "broken"}
        ]
        assert not state.clients

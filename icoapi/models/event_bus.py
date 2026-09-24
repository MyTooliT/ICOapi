"""Event buses used to publish updates about the API

ICOapi only writes to an event bus, clients only read from it. Everything a
client wants to tell ICOapi goes through the REST API. This keeps the
transports (e.g. WebSocket, MQTT) interchangeable.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Sequence
from enum import StrEnum, unique
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from icoapi.models.models import SocketMessage, SystemStateModel

logger = logging.getLogger(__name__)


@unique
class Channel(StrEnum):
    """Logical channels of an event bus

    Transports map a channel to their own addressing scheme, e.g. to a topic
    (MQTT) or to the ``message`` field of a message (WebSocket).
    """

    STATE = "state"
    RECORDING_FINISHED = "recording/finished"
    RECORDING_FAILED = "recording/failed"


class EventBus(ABC):
    """Publisher side of an event bus

    Implementations must not block for long while publishing. A transport
    that can be slow (e.g. a network connection to a broker) has to queue
    messages internally, so it never delays the caller or other buses.
    """

    @abstractmethod
    async def publish_state(self, state: SystemStateModel) -> None:
        """Publish the current general state

        The state is “latest wins”: subscribers that connect later receive the
        most recent state.
        """

    @abstractmethod
    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Publish a one-shot event

        In contrast to the state, events are not replayed to subscribers that
        connect later.
        """

    async def close(self) -> None:
        """Release all resources used by the bus"""


class WebSocketEventBus(EventBus):
    """Event bus that publishes to clients connected via WebSocket

    The WebSocket endpoint registers and removes its clients. Only the state
    is published, events are ignored.
    """

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    def add_client(self, client: WebSocket) -> None:
        """Add client that should receive updates"""

        self._clients.append(client)
        logger.info("Added WebSocket instance to general messenger list")

    def remove_client(self, client: WebSocket) -> None:
        """Remove client"""

        try:
            self._clients.remove(client)
            logger.info(
                "Removed WebSocket instance from general messenger list"
            )
        except ValueError:
            logger.warning(
                "Tried removing WebSocket instance from general messenger list"
                " but failed."
            )

    def clear_clients(self) -> None:
        """Remove all clients"""

        num_of_clients = len(self._clients)
        self._clients.clear()
        logger.info(
            "Cleared %s clients from general messenger list", num_of_clients
        )

    async def _send(
        self, message: SocketMessage, recipients: Sequence[WebSocket]
    ) -> None:
        """Send a message to the given clients

        Sends are serialized, since concurrent sends on the same WebSocket
        connection are not supported and can crash the connection. Clients
        that fail to receive the message are dropped.
        """

        payload = message.model_dump()
        async with self._lock:
            for client in list(recipients):
                try:
                    await client.send_json(payload)
                except (RuntimeError, WebSocketDisconnect):
                    logger.warning(
                        "Dropping unresponsive WebSocket instance from"
                        " general messenger list"
                    )
                    self.remove_client(client)

    async def publish_state(self, state: SystemStateModel) -> None:
        """Send the state to all clients"""

        await self._send(
            SocketMessage(message=Channel.STATE.value, data=state),
            self._clients,
        )

        if len(self._clients) > 0:
            logger.info("Pushed SystemState to %s clients.", len(self._clients))

    async def send_state_to(
        self, client: WebSocket, state: SystemStateModel
    ) -> None:
        """Send the state to a single client

        This gives a newly connected client the current state without
        sending it to all other clients again.
        """

        await self._send(
            SocketMessage(message=Channel.STATE.value, data=state), [client]
        )

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Ignore the event, WebSocket clients only receive the state"""

        logger.debug("Ignoring event on channel <%s> for WebSocket", channel)

    async def close(self) -> None:
        """Forget all clients"""

        self.clear_clients()


class CompositeEventBus(EventBus):
    """Event bus that publishes to multiple buses

    A bus that fails to publish does not affect the other buses.
    """

    def __init__(self, buses: Iterable[EventBus] = ()) -> None:
        self._buses: list[EventBus] = list(buses)

    def add_bus(self, bus: EventBus) -> None:
        """Add a bus that should receive everything published"""

        self._buses.append(bus)

    async def _fan_out(
        self, action: Callable[[EventBus], Awaitable[None]]
    ) -> None:
        """Run action for all buses and log errors instead of raising them"""

        results = await asyncio.gather(
            *(action(bus) for bus in self._buses), return_exceptions=True
        )
        for bus, result in zip(self._buses, results):
            if isinstance(result, Exception):
                logger.error(
                    "Publishing via %s failed: %s",
                    type(bus).__name__,
                    result,
                    exc_info=result,
                )
            elif isinstance(result, BaseException):
                raise result

    async def publish_state(self, state: SystemStateModel) -> None:
        """Publish the state to all buses"""

        await self._fan_out(lambda bus: bus.publish_state(state))

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Publish the event to all buses"""

        await self._fan_out(lambda bus: bus.publish_event(channel, payload))

    async def close(self) -> None:
        """Close all buses"""

        await self._fan_out(lambda bus: bus.close())

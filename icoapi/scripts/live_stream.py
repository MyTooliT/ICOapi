"""Send the live data of a measurement to the clients

The live data is a display: The file has all the data. A client (e.g. a
browser that draws charts) can only handle a limited amount of data, so every
client can say how much it wants when it connects (``/measurement/stream``):

- ``rate``: Points per second **per source**. The other points are left out.
  Without it every point is sent.
- ``updates``: Messages per second. The points that were collected in the
  meantime are sent together.

The streams of all units send to the same clients and must never wait for a
slow client: Points wait in a bounded buffer and the oldest ones are dropped
if the client does not catch up. One task sends to a client at a time, because
a WebSocket can only handle one sender that waits for a slow connection.
"""

# -- Imports ------------------------------------------------------------------

import asyncio
from dataclasses import dataclass
import logging
import os
from time import monotonic
from typing import Any
from weakref import WeakKeyDictionary

from icoapi.models.globals import MeasurementState

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

MAX_PENDING_ROWS = 50_000
"""Points that may wait for a client before the oldest ones are dropped"""

FLUSH_TIMEOUT = 5.0
"""Seconds to wait for the clients to receive the last messages"""

# -- Classes ------------------------------------------------------------------


@dataclass(frozen=True)
class LiveSettings:
    """What a client wants to receive"""

    rate: float | None = None
    """Points per second and source (``None``: all points)"""

    updates: float | None = None
    """Messages per second (``None``: the default of the API)"""

    def period(self) -> float:
        """The time between two messages in seconds"""

        updates = self.updates or float(
            os.getenv("WEBSOCKET_UPDATE_RATE", "300")
        )
        return 1 / max(updates, 1.0)


_settings: WeakKeyDictionary[Any, LiveSettings] = WeakKeyDictionary()
"""The settings of the clients"""


def configure_client(
    client: Any, rate: float | None, updates: float | None
) -> None:
    """Set what a client wants to receive (``None`` or 0: no limit)"""

    _settings[client] = LiveSettings(rate or None, updates or None)


class _ClientSender:  # pylint: disable=too-few-public-methods
    """Send the live data to one client"""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.settings = _settings.get(client, LiveSettings())
        self.rows: list[dict] = []
        self.dropped = 0
        self.task: asyncio.Task | None = None
        self._next_due: dict[str, float] = {}
        self._last_sent = 0.0

    def _wanted(self, row: dict) -> bool:
        """Check if a point is part of the rate the client wants"""

        rate = self.settings.rate
        timestamp = row.get("timestamp")
        if rate is None or timestamp is None:
            return True
        source = str(row.get("source"))
        due = self._next_due.get(source)
        if due is not None and timestamp < due:
            return False
        following = (due if due is not None else timestamp) + 1 / rate
        # Do not try to catch up after a gap
        self._next_due[source] = (
            following if following > timestamp else timestamp + 1 / rate
        )
        return True

    def offer(
        self, rows: list[dict], measurement_state: MeasurementState
    ) -> None:
        """Queue points for the client"""

        self.rows.extend(row for row in rows if self._wanted(row))
        if len(self.rows) > MAX_PENDING_ROWS:
            if self.dropped == 0:
                logger.warning(
                    "Client <%s> is too slow for the live data: dropping"
                    " points (the file has all the data)",
                    getattr(self.client, "client", "?"),
                )
            self.dropped += len(self.rows) - MAX_PENDING_ROWS
            del self.rows[: len(self.rows) - MAX_PENDING_ROWS]
        if self.rows and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run(measurement_state))

    async def _run(self, measurement_state: MeasurementState) -> None:
        """Send until nothing is left"""

        while self.rows:
            wait = self._last_sent + self.settings.period() - monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            message, self.rows = self.rows, []
            self._last_sent = monotonic()
            try:
                await self.client.send_json(message)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to send data to client <%s>, dropping it",
                    getattr(self.client, "client", "?"),
                    exc_info=True,
                )
                self.rows = []
                if self.client in measurement_state.clients:
                    measurement_state.clients.remove(self.client)
                return


_senders: WeakKeyDictionary[Any, _ClientSender] = WeakKeyDictionary()
"""The sender of every client"""

# -- Functions ----------------------------------------------------------------


async def send_to_clients(
    measurement_state: MeasurementState, rows: list[dict]
) -> None:
    """Send points to the clients of the measurement (does not wait)"""

    for client in list(measurement_state.clients):
        sender = _senders.get(client)
        if sender is None:
            sender = _senders[client] = _ClientSender(client)
        sender.offer(rows, measurement_state)
    # Let the senders start
    await asyncio.sleep(0)


async def flush_clients(measurement_state: MeasurementState) -> None:
    """Wait (for a short time) until the clients got the queued points"""

    tasks = {
        sender.task
        for client in list(measurement_state.clients)
        if (sender := _senders.get(client)) is not None
        and sender.task is not None
        and not sender.task.done()
    }
    if tasks:
        await asyncio.wait(tasks, timeout=FLUSH_TIMEOUT)

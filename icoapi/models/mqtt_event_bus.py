"""Event bus that publishes to an MQTT broker

Topics below the configured base topic:

- ``<base>/State``: general state, retained
- ``<base>/Recording/Finished``: measurement finished, not retained
- ``<base>/Recording/Failed``: measurement failed, not retained

Publishing never blocks: the network connection is handled by the thread of
``paho-mqtt``, which also queues messages while the broker is unreachable.
"""

import asyncio
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt

from icoapi.models.event_bus import Channel, EventBus
from icoapi.models.models import SystemStateModel

logger = logging.getLogger(__name__)

# The state is “latest wins” and is published again after every (re)connect,
# so it does not need to be queued while the broker is unreachable. Queueing
# it would also use up the space for events.
STATE_QOS = 0
EVENT_QOS = 1

TRUE_VALUES = {"1", "true", "yes", "on"}


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    """Get optional setting, empty values are treated as not set"""

    value = environ.get(name, "").strip()
    return value if value else None


def _integer(environ: Mapping[str, str], name: str, default: int) -> int:
    """Get integer setting"""

    value = _optional(environ, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, not “{value}”") from error


@dataclass(frozen=True)
class MQTTSettings:  # pylint: disable=too-many-instance-attributes
    """Settings for the connection to the MQTT broker

    Read from the environment by :meth:`from_env`.
    """

    broker: str
    base_topic: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False
    tls_ca_certs: str | None = None
    tls_certfile: str | None = None
    tls_keyfile: str | None = None
    client_id: str = ""
    keepalive: int = 60
    buffer_size: int = 1000

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "MQTTSettings | None":
        """Read the settings from the environment

        Environment variables:

        - ``MQTT_BROKER``: host name of the broker
        - ``MQTT_BASE_TOPIC``: base topic, used exactly as given
        - ``MQTT_PORT``: port (default: 1883, or 8883 with TLS)
        - ``MQTT_USERNAME``, ``MQTT_PASSWORD``: credentials
        - ``MQTT_TLS``: use TLS if set to ``1`` (or ``true``, ``yes``, ``on``)
        - ``MQTT_TLS_CA_CERTS``, ``MQTT_TLS_CERTFILE``, ``MQTT_TLS_KEYFILE``:
          certificate files (default: the CA certificates of the system)
        - ``MQTT_CLIENT_ID``: client ID (default: chosen by the broker)
        - ``MQTT_KEEPALIVE``: keepalive in seconds (default: 60)
        - ``MQTT_BUFFER_SIZE``: maximum number of messages that are kept while
          the broker is unreachable (default: 1000)

        Returns:

            The settings, or ``None`` if neither ``MQTT_BROKER`` nor
            ``MQTT_BASE_TOPIC`` is set (MQTT is not used)

        Raises:

            ValueError if only one of broker and base topic is set or if a
            setting is invalid

        """

        if environ is None:
            environ = os.environ

        broker = _optional(environ, "MQTT_BROKER")
        base_topic = _optional(environ, "MQTT_BASE_TOPIC")
        if broker is None and base_topic is None:
            return None
        if broker is None:
            raise ValueError("MQTT_BASE_TOPIC is set but MQTT_BROKER is not")
        if base_topic is None:
            raise ValueError("MQTT_BROKER is set but MQTT_BASE_TOPIC is not")

        base_topic = base_topic.rstrip("/")
        if not base_topic:
            raise ValueError("MQTT_BASE_TOPIC must not be empty")
        if any(character in base_topic for character in ("+", "#", "\0")):
            raise ValueError(
                "MQTT_BASE_TOPIC must not contain wildcards (+, #)"
            )

        tls = environ.get("MQTT_TLS", "").strip().lower() in TRUE_VALUES

        return cls(
            broker=broker,
            base_topic=base_topic,
            port=_integer(environ, "MQTT_PORT", 8883 if tls else 1883),
            username=_optional(environ, "MQTT_USERNAME"),
            password=_optional(environ, "MQTT_PASSWORD"),
            tls=tls,
            tls_ca_certs=_optional(environ, "MQTT_TLS_CA_CERTS"),
            tls_certfile=_optional(environ, "MQTT_TLS_CERTFILE"),
            tls_keyfile=_optional(environ, "MQTT_TLS_KEYFILE"),
            client_id=_optional(environ, "MQTT_CLIENT_ID") or "",
            keepalive=_integer(environ, "MQTT_KEEPALIVE", 60),
            buffer_size=_integer(environ, "MQTT_BUFFER_SIZE", 1000),
        )


def create_client(settings: MQTTSettings) -> mqtt.Client:
    """Create MQTT client for the given settings"""

    return mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=settings.client_id
    )


# pylint: disable-next=too-many-instance-attributes
class MQTTEventBus(EventBus):
    """Event bus that publishes to an MQTT broker

    - The state is published retained (QoS 0) and again after every
      (re)connect. If the API stops, the broker removes the retained state
      (last will, or explicitly when the bus is closed), so an old state never
      claims that the API is still running.
    - Events are published not retained with QoS 1. While the broker is
      unreachable they are queued (up to ``buffer_size`` messages), later
      events are dropped with a warning.
    """

    def __init__(
        self,
        settings: MQTTSettings,
        client_factory: Callable[[MQTTSettings], mqtt.Client] = create_client,
    ) -> None:
        self._settings = settings
        self._client = client_factory(settings)
        base = settings.base_topic
        self._state_topic = f"{base}/State"
        self._topics = {
            Channel.RECORDING_FINISHED: f"{base}/Recording/Finished",
            Channel.RECORDING_FAILED: f"{base}/Recording/Failed",
        }
        # The callbacks of `paho-mqtt` run in its network thread. The lock
        # makes sure that the last state is always the last one published.
        self._lock = threading.Lock()
        self._state_payload: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False

    def _log(self, level: int, message: str, *arguments: Any) -> None:
        """Log message, also when called from the thread of `paho-mqtt`

        The log handlers of the API expect to be called from the event loop.
        """

        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(logger.log, level, message, *arguments)
                return
            except RuntimeError:  # Event loop is closed
                pass
        logger.log(level, message, *arguments)

    def _publish(
        self, topic: str, payload: str | bytes, qos: int, retain: bool
    ) -> mqtt.MQTTMessageInfo:
        """Publish message and log problems

        This never blocks: `paho-mqtt` sends (and queues) the message in its
        network thread.
        """

        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc == mqtt.MQTT_ERR_QUEUE_SIZE:
            # A dropped state is published again after connecting, so only a
            # dropped event is a problem
            self._log(
                logging.WARNING if qos > 0 else logging.DEBUG,
                "Dropped message for topic <%s>: buffer for %s messages is"
                " full while the MQTT broker is unreachable",
                topic,
                self._settings.buffer_size,
            )
        elif info.rc == mqtt.MQTT_ERR_NO_CONN:
            # Messages with a QoS above 0 are queued until the client
            # connects, others are skipped
            self._log(
                logging.DEBUG,
                "Not connected to MQTT broker, %s message for topic <%s>",
                "queued" if qos > 0 else "skipped",
                topic,
            )
        elif info.rc != mqtt.MQTT_ERR_SUCCESS:
            self._log(
                logging.WARNING,
                "Could not publish message for topic <%s>: %s",
                topic,
                mqtt.error_string(info.rc),
            )
        return info

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: mqtt.ReasonCode,
        _properties: Any,
    ) -> None:
        """Publish the last state after (re)connecting to the broker"""

        if reason_code.is_failure:
            self._log(
                logging.ERROR, "MQTT broker refused connection: %s", reason_code
            )
            return

        self._log(
            logging.INFO,
            "Connected to MQTT broker <%s:%s>",
            self._settings.broker,
            self._settings.port,
        )
        with self._lock:
            if self._state_payload is not None:
                self._publish(
                    self._state_topic, self._state_payload, STATE_QOS, True
                )

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: mqtt.ReasonCode,
        _properties: Any,
    ) -> None:
        """Log that the connection to the broker was lost"""

        if not self._closing:
            self._log(
                logging.WARNING,
                "Lost connection to MQTT broker <%s:%s>: %s",
                self._settings.broker,
                self._settings.port,
                reason_code,
            )

    async def start(self) -> None:
        """Start connecting to the broker

        This does not wait for the connection. `paho-mqtt` connects (and
        reconnects) in its own thread.
        """

        settings = self._settings
        client = self._client
        self._loop = asyncio.get_running_loop()

        if settings.username is not None:
            client.username_pw_set(settings.username, settings.password)
        if settings.tls:
            client.tls_set(
                ca_certs=settings.tls_ca_certs,
                certfile=settings.tls_certfile,
                keyfile=settings.tls_keyfile,
            )
        # An empty retained message removes the retained state from the broker
        # if the connection to the API is lost without disconnecting
        client.will_set(self._state_topic, payload=None, qos=1, retain=True)
        client.max_queued_messages_set(settings.buffer_size)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect

        client.connect_async(settings.broker, settings.port, settings.keepalive)
        client.loop_start()
        logger.info(
            "Started MQTT event bus for broker <%s:%s> with base topic <%s>",
            settings.broker,
            settings.port,
            settings.base_topic,
        )

    async def publish_state(self, state: SystemStateModel) -> None:
        """Publish the state retained, and again after reconnecting"""

        payload = state.model_dump_json()
        with self._lock:
            self._state_payload = payload
            self._publish(self._state_topic, payload, STATE_QOS, True)

    async def publish_event(
        self, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Publish an event, not retained"""

        topic = self._topics.get(channel)
        if topic is None:
            raise ValueError(
                f"Channel <{channel}> is not an event, use `publish_state`"
            )
        self._publish(topic, json.dumps(payload, default=str), EVENT_QOS, False)

    def _shutdown(self) -> None:
        """Remove the retained state and disconnect from the broker"""

        client = self._client
        self._closing = True
        with self._lock:
            self._state_payload = None
            # A regular disconnect does not trigger the last will
            info = self._publish(self._state_topic, b"", 1, True)

        # Without connection the message would never be published
        if client.is_connected():
            try:
                info.wait_for_publish(timeout=2)
            except (RuntimeError, ValueError):
                pass
        client.disconnect()
        client.loop_stop()
        self._log(logging.INFO, "Closed MQTT event bus")

    async def close(self) -> None:
        """Remove the retained state and disconnect from the broker"""

        await asyncio.to_thread(self._shutdown)


def create_mqtt_event_bus(
    environ: Mapping[str, str] | None = None,
) -> MQTTEventBus | None:
    """Create the MQTT event bus from the environment settings

    Returns:

        The event bus, or ``None`` if MQTT is not configured or the
        configuration is invalid

    """

    try:
        settings = MQTTSettings.from_env(environ)
    except ValueError as error:
        logger.error("MQTT is disabled: %s", error)
        return None

    if settings is None:
        logger.debug(
            "MQTT is disabled: MQTT_BROKER and MQTT_BASE_TOPIC are not set"
        )
        return None

    return MQTTEventBus(settings)

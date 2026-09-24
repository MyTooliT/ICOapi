"""Tests for the MQTT event bus with a real MQTT broker

The tests are marked with ``mqtt`` and are skipped, if no broker is
configured. Use the following environment variables to run them (e.g. with
``just test-mqtt``):

- ``TEST_MQTT_BROKER``: host name of the broker (required)
- ``TEST_MQTT_PORT``: port of the broker (default: 1883)
- ``TEST_MQTT_USERNAME``, ``TEST_MQTT_PASSWORD``: credentials (optional)

All tests publish below a unique topic that only exists for the duration of the
test, but they do publish (retained) messages to the broker.
"""

# -- Imports ------------------------------------------------------------------

import json
import os
from collections.abc import Callable, Iterator
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
from pytest import fixture, mark, skip

from icoapi.models.event_bus import Channel
from icoapi.models.globals import build_system_state
from icoapi.models.mqtt_event_bus import MQTTEventBus, create_mqtt_event_bus

pytestmark = mark.mqtt

# -- Classes and Functions ----------------------------------------------------


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Wait until a condition is true

    Returns:

        ``True`` if the condition became true, ``False`` if the timeout was
        reached

    """

    end = monotonic() + timeout
    while monotonic() < end:
        if condition():
            return True
        sleep(0.05)
    return condition()


# pylint: disable-next=too-few-public-methods
class Subscriber:
    """Client that collects the messages published to a topic"""

    def __init__(self, settings: dict[str, Any], topic: str) -> None:
        self.messages: list[mqtt.MQTTMessage] = []
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings["username"]:
            self._client.username_pw_set(
                settings["username"], settings["password"]
            )
        self._client.on_message = lambda _client, _userdata, message: (
            self.messages.append(message)
        )
        self._client.connect(settings["host"], settings["port"])
        self._client.loop_start()
        result, _message_id = self._client.subscribe(topic, qos=1)
        assert result == mqtt.MQTT_ERR_SUCCESS
        # Subscribing is finished, once the broker delivers retained messages
        # or (without retained messages) after a short delay
        sleep(0.3)

    def close(self) -> None:
        """Disconnect from broker"""

        self._client.disconnect()
        self._client.loop_stop()


@fixture(name="broker")
def fixture_broker() -> dict[str, Any]:
    """Settings of the MQTT broker used for testing"""

    host = os.getenv("TEST_MQTT_BROKER")
    if not host:
        skip("No MQTT broker configured (set TEST_MQTT_BROKER)")

    return {
        "host": host,
        "port": int(os.getenv("TEST_MQTT_PORT", "1883")),
        "username": os.getenv("TEST_MQTT_USERNAME"),
        "password": os.getenv("TEST_MQTT_PASSWORD"),
    }


@fixture(name="base_topic")
def fixture_base_topic() -> str:
    """Unique base topic for a test"""

    return f"icodaq-test/{uuid4()}"


@fixture(name="subscribe")
def fixture_subscribe(
    broker: dict[str, Any],
) -> Iterator[Callable[[str], Subscriber]]:
    """Create subscribers for topics, that are disconnected after the test"""

    subscribers: list[Subscriber] = []

    def subscribe(topic: str) -> Subscriber:
        subscribers.append(Subscriber(broker, topic))
        return subscribers[-1]

    yield subscribe

    for subscriber in subscribers:
        subscriber.close()


@fixture(name="create_bus")
def fixture_create_bus(
    broker: dict[str, Any], base_topic: str
) -> Iterator[Callable[[], MQTTEventBus]]:
    """Create event buses for the broker, that are closed after the test"""

    buses: list[MQTTEventBus] = []

    def create_bus() -> MQTTEventBus:
        environ = {
            "MQTT_BROKER": broker["host"],
            "MQTT_PORT": str(broker["port"]),
            "MQTT_BASE_TOPIC": base_topic,
            "MQTT_USERNAME": broker["username"] or "",
            "MQTT_PASSWORD": broker["password"] or "",
            "MQTT_KEEPALIVE": "10",
        }
        bus = create_mqtt_event_bus(environ)
        assert bus is not None
        buses.append(bus)
        return bus

    yield create_bus

    # Stop connections and remove retained messages that are still left
    for bus in buses:
        bus._shutdown()  # pylint: disable=protected-access


# -- Tests --------------------------------------------------------------------


class TestMQTTBroker:
    """Test the MQTT event bus with a real broker"""

    async def test_state_is_retained(self, base_topic, subscribe, create_bus):
        """The state should be delivered to current and later subscribers"""

        state_topic = f"{base_topic}/State"
        current = subscribe(state_topic)
        bus = create_bus()
        state = await build_system_state()

        await bus.start()
        # The client is (most likely) not connected yet. The state is
        # published as soon as the connection is established.
        await bus.publish_state(state)

        assert wait_until(lambda: len(current.messages) >= 1)
        assert current.messages[0].topic == state_topic
        assert current.messages[0].payload.decode() == state.model_dump_json()
        # A message that is delivered to an already subscribed client is not
        # marked as retained

        late = subscribe(state_topic)
        assert wait_until(lambda: len(late.messages) >= 1)
        assert late.messages[0].retain
        assert late.messages[0].payload.decode() == state.model_dump_json()

    async def test_latest_state_is_retained(
        self, base_topic, subscribe, create_bus
    ):
        """Only the latest state should be delivered to later subscribers"""

        bus = create_bus()
        first = await build_system_state()
        second = first.model_copy(update={"can_ready": not first.can_ready})

        await bus.start()
        await bus.publish_state(first)
        await bus.publish_state(second)
        sleep(1)

        late = subscribe(f"{base_topic}/State")
        assert wait_until(lambda: len(late.messages) >= 1)
        sleep(0.3)
        assert [message.payload.decode() for message in late.messages] == [
            second.model_dump_json()
        ]

    async def test_close_removes_retained_state(
        self, base_topic, subscribe, create_bus
    ):
        """Closing the bus should remove the retained state"""

        state_topic = f"{base_topic}/State"
        current = subscribe(state_topic)
        bus = create_bus()

        await bus.start()
        await bus.publish_state(await build_system_state())
        assert wait_until(lambda: len(current.messages) >= 1)

        await bus.close()

        # Subscribers get the empty message that removes the retained state
        assert wait_until(lambda: len(current.messages) >= 2)
        assert current.messages[-1].payload == b""
        late = subscribe(state_topic)
        sleep(0.5)
        assert not late.messages

    async def test_lost_connection_removes_retained_state(
        self, base_topic, subscribe, create_bus
    ):
        """The broker should remove the retained state (last will)

        This happens if the connection is lost without disconnecting.
        """

        state_topic = f"{base_topic}/State"
        current = subscribe(state_topic)
        bus = create_bus()

        await bus.start()
        await bus.publish_state(await build_system_state())
        assert wait_until(lambda: len(current.messages) >= 1)

        # Simulate a crash: The connection is closed without a disconnect
        # message. The network thread is stopped first, so the client does not
        # reconnect (and publish the state again).
        # pylint: disable=protected-access
        bus._client.loop_stop()
        bus._client._sock.close()  # type: ignore[union-attr]
        # pylint: enable=protected-access

        assert wait_until(lambda: len(current.messages) >= 2)
        assert current.messages[-1].payload == b""
        late = subscribe(state_topic)
        sleep(0.5)
        assert not late.messages

    async def test_events(self, base_topic, subscribe, create_bus):
        """Events should be delivered but not retained"""

        finished = subscribe(f"{base_topic}/Recording/Finished")
        failed = subscribe(f"{base_topic}/Recording/Failed")
        bus = create_bus()

        finished_payload = {
            "name": "Test Measurement.hdf5",
            "size": 1234,
            "url": "/api/v1/files/Test%20Measurement.hdf5",
        }
        failed_payload = {
            "name": "Test Measurement.hdf5",
            "size": None,
            "url": None,
            "error": {"type": "RuntimeError", "message": "Something broke"},
        }
        await bus.start()
        # The client is (most likely) not connected yet. The events are kept
        # until the connection is established.
        await bus.publish_event(Channel.RECORDING_FINISHED, finished_payload)
        await bus.publish_event(Channel.RECORDING_FAILED, failed_payload)

        assert wait_until(lambda: finished.messages and failed.messages)
        assert json.loads(finished.messages[0].payload) == finished_payload
        assert json.loads(failed.messages[0].payload) == failed_payload
        assert not finished.messages[0].retain
        assert not failed.messages[0].retain

        # Events are not replayed to later subscribers
        late = subscribe(f"{base_topic}/Recording/#")
        sleep(0.5)
        assert not late.messages

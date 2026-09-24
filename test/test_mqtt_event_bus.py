"""Tests for the MQTT event bus"""

# -- Imports ------------------------------------------------------------------

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

import paho.mqtt.client as mqtt
from pytest import LogCaptureFixture, MonkeyPatch, mark, raises

from icoapi import api
from icoapi.models.event_bus import Channel
from icoapi.models.globals import GeneralMessenger, build_system_state
from icoapi.models.mqtt_event_bus import (
    MQTTEventBus,
    MQTTSettings,
    create_mqtt_event_bus,
)

# -- Classes --------------------------------------------------------------------


# pylint: disable-next=too-few-public-methods
class FakePublishInfo:
    """Result of a publish request"""

    def __init__(self, rc: int) -> None:
        self.rc = rc
        self.waited_for: list[float | None] = []

    def wait_for_publish(self, timeout: float | None = None) -> None:
        """Record that the caller waited for the message to be published"""

        self.waited_for.append(timeout)


# pylint: disable-next=too-many-instance-attributes
class FakeMQTTClient:
    """Double for the MQTT client that records how it is used"""

    def __init__(self) -> None:
        self.published: list[tuple[str, Any, int, bool]] = []
        self.publish_rc = mqtt.MQTT_ERR_SUCCESS
        self.will: tuple[str, Any, int, bool] | None = None
        self.credentials: tuple[str, str | None] | None = None
        self.tls: dict[str, str | None] | None = None
        self.tls_error: Exception | None = None
        self.max_queued: int | None = None
        self.connection: tuple[str, int, int] | None = None
        self.loop_running = False
        self.connected = True
        self.disconnected = False
        self.on_connect: Any = None
        self.on_disconnect: Any = None

    def simulate_connect(self, reason_code: mqtt.ReasonCode) -> None:
        """Call the handler for a finished connection attempt"""

        assert self.on_connect is not None
        self.on_connect(  # pylint: disable=not-callable
            self, None, None, reason_code, None
        )

    def simulate_disconnect(self, reason_code: mqtt.ReasonCode) -> None:
        """Call the handler for a lost connection"""

        assert self.on_disconnect is not None
        self.on_disconnect(  # pylint: disable=not-callable
            self, None, None, reason_code, None
        )

    def username_pw_set(self, username: str, password: str | None) -> None:
        """Record credentials"""

        self.credentials = (username, password)

    def tls_set(self, **arguments: str | None) -> None:
        """Record TLS settings"""

        if self.tls_error is not None:
            raise self.tls_error
        self.tls = arguments

    def will_set(
        self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False
    ) -> None:
        """Record last will"""

        self.will = (topic, payload, qos, retain)

    def max_queued_messages_set(self, queue_size: int) -> None:
        """Record buffer size"""

        self.max_queued = queue_size

    def reconnect_delay_set(self, min_delay: int, max_delay: int) -> None:
        """Ignore reconnect delay"""

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        """Record connection settings"""

        self.connection = (host, port, keepalive)

    def loop_start(self) -> None:
        """Record that the network thread was started"""

        self.loop_running = True

    def loop_stop(self) -> None:
        """Record that the network thread was stopped"""

        self.loop_running = False

    def is_connected(self) -> bool:
        """Check if the client is connected"""

        return self.connected

    def disconnect(self) -> None:
        """Record that the connection was closed"""

        self.disconnected = True

    def publish(
        self, topic: str, payload: Any, qos: int = 0, retain: bool = False
    ) -> FakePublishInfo:
        """Record published message"""

        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo(self.publish_rc)


SUCCESS = mqtt.ReasonCode(mqtt.PacketTypes.CONNACK, "Success")
NOT_AUTHORIZED = mqtt.ReasonCode(mqtt.PacketTypes.CONNACK, "Not authorized")


def create_bus(
    fake: FakeMQTTClient, **settings: Any
) -> MQTTEventBus:
    """Create MQTT event bus that uses a fake client"""

    return MQTTEventBus(
        MQTTSettings(
            **{"broker": "broker.test", "base_topic": "icodaq/test", **settings}
        ),
        client_factory=lambda _settings: cast(mqtt.Client, fake),
    )


# -- Tests --------------------------------------------------------------------


class TestMQTTSettings:
    """Tests for reading the MQTT settings from the environment"""

    def test_not_configured(self) -> None:
        """MQTT is not used if no setting is given"""

        assert MQTTSettings.from_env({}) is None
        assert MQTTSettings.from_env({"MQTT_BROKER": " "}) is None

    def test_defaults(self) -> None:
        """Only broker and base topic are required"""

        settings = MQTTSettings.from_env({
            "MQTT_BROKER": "broker.test",
            "MQTT_BASE_TOPIC": "icodaq/line-3/",
        })

        assert settings == MQTTSettings(
            broker="broker.test", base_topic="icodaq/line-3"
        )
        assert settings.port == 1883
        assert not settings.tls

    def test_all_settings(self) -> None:
        """All settings should be read"""

        settings = MQTTSettings.from_env({
            "MQTT_BROKER": "broker.test",
            "MQTT_BASE_TOPIC": "icodaq",
            "MQTT_PORT": "1884",
            "MQTT_USERNAME": "user",
            "MQTT_PASSWORD": "secret",
            "MQTT_TLS": "True",
            "MQTT_TLS_CA_CERTS": "ca.pem",
            "MQTT_TLS_CERTFILE": "client.pem",
            "MQTT_TLS_KEYFILE": "client.key",
            "MQTT_CLIENT_ID": "icoapi-1",
            "MQTT_KEEPALIVE": "30",
            "MQTT_BUFFER_SIZE": "10",
        })

        assert settings == MQTTSettings(
            broker="broker.test",
            base_topic="icodaq",
            port=1884,
            username="user",
            password="secret",
            tls=True,
            tls_ca_certs="ca.pem",
            tls_certfile="client.pem",
            tls_keyfile="client.key",
            client_id="icoapi-1",
            keepalive=30,
            buffer_size=10,
        )

    def test_tls_default_port(self) -> None:
        """TLS should use the standard TLS port by default"""

        settings = MQTTSettings.from_env({
            "MQTT_BROKER": "broker.test",
            "MQTT_BASE_TOPIC": "icodaq",
            "MQTT_TLS": "1",
        })

        assert settings is not None
        assert settings.port == 8883

    @mark.parametrize(
        "environ",
        [
            {"MQTT_BROKER": "broker.test"},
            {"MQTT_BASE_TOPIC": "icodaq"},
            {"MQTT_BROKER": "broker.test", "MQTT_BASE_TOPIC": "/"},
            {"MQTT_BROKER": "broker.test", "MQTT_BASE_TOPIC": "icodaq/#"},
            {"MQTT_BROKER": "broker.test", "MQTT_BASE_TOPIC": "+/icodaq"},
            {
                "MQTT_BROKER": "broker.test",
                "MQTT_BASE_TOPIC": "icodaq",
                "MQTT_PORT": "port",
            },
        ],
    )
    def test_invalid(self, environ: dict[str, str]) -> None:
        """Incomplete or invalid settings should be rejected"""

        with raises(ValueError):
            MQTTSettings.from_env(environ)

    def test_create_bus(self, caplog: LogCaptureFixture) -> None:
        """The bus is only created for valid settings"""

        assert create_mqtt_event_bus({}) is None
        with caplog.at_level(logging.ERROR):
            assert create_mqtt_event_bus({"MQTT_BROKER": "broker.test"}) is None
        assert "MQTT is disabled" in caplog.text
        assert (
            create_mqtt_event_bus({
                "MQTT_BROKER": "broker.test",
                "MQTT_BASE_TOPIC": "icodaq",
            })
            is not None
        )


class TestMQTTEventBus:
    """Tests for ``MQTTEventBus``"""

    async def test_start(self) -> None:
        """Starting the bus should configure the client and connect"""

        fake = FakeMQTTClient()
        bus = create_bus(
            fake,
            port=8883,
            username="user",
            password="secret",
            tls=True,
            tls_ca_certs="ca.pem",
            keepalive=30,
            buffer_size=10,
        )

        await bus.start()

        assert fake.connection == ("broker.test", 8883, 30)
        assert fake.loop_running
        assert fake.credentials == ("user", "secret")
        assert fake.tls == {
            "ca_certs": "ca.pem",
            "certfile": None,
            "keyfile": None,
        }
        assert fake.max_queued == 10
        # Broker removes retained state if the connection is lost
        assert fake.will == ("icodaq/test/State", None, 1, True)

    async def test_publish_state(self) -> None:
        """The state should be published retained to the state topic"""

        fake = FakeMQTTClient()
        bus = create_bus(fake)
        state = await build_system_state()

        await bus.publish_state(state)

        assert fake.published == [
            ("icodaq/test/State", state.model_dump_json(), 0, True)
        ]

    async def test_publish_events(self) -> None:
        """Events should be published not retained with QoS 1"""

        fake = FakeMQTTClient()
        bus = create_bus(fake)

        await bus.publish_event(
            Channel.RECORDING_FINISHED,
            {"name": "test.hdf5", "size": 1234, "url": "/api/v1/files/test"},
        )
        await bus.publish_event(
            Channel.RECORDING_FAILED,
            {"name": None, "size": None, "url": None, "error": {"type": "X"}},
        )

        assert fake.published == [
            (
                "icodaq/test/Recording/Finished",
                '{"name": "test.hdf5", "size": 1234, "url": "/api/v1/files/test"}',
                1,
                False,
            ),
            (
                "icodaq/test/Recording/Failed",
                '{"name": null, "size": null, "url": null, "error": {"type": "X"}}',
                1,
                False,
            ),
        ]

    async def test_state_is_not_an_event(self) -> None:
        """The state channel must be published via ``publish_state``"""

        bus = create_bus(FakeMQTTClient())

        with raises(ValueError):
            await bus.publish_event(Channel.STATE, {})

    async def test_state_is_published_again_after_connect(self) -> None:
        """The last state should be published every time the client connects"""

        fake = FakeMQTTClient()
        bus = create_bus(fake)
        await bus.start()

        # Nothing to publish before the first state
        fake.simulate_connect(SUCCESS)
        assert not fake.published

        first = await build_system_state()
        second = first.model_copy(update={"can_ready": not first.can_ready})
        await bus.publish_state(first)
        await bus.publish_state(second)
        fake.published.clear()

        # Connection problems must not publish anything
        fake.simulate_connect(NOT_AUTHORIZED)
        assert not fake.published

        fake.simulate_connect(SUCCESS)
        assert fake.published == [
            ("icodaq/test/State", second.model_dump_json(), 0, True)
        ]

    async def test_full_buffer_drops_message_with_warning(
        self, caplog: LogCaptureFixture
    ) -> None:
        """Events that do not fit into the buffer should be dropped"""

        fake = FakeMQTTClient()
        fake.publish_rc = mqtt.MQTT_ERR_QUEUE_SIZE
        bus = create_bus(fake, buffer_size=5)
        await bus.start()

        with caplog.at_level(logging.WARNING):
            await bus.publish_event(Channel.RECORDING_FINISHED, {})
            # Logs from the thread of the client are handled by the event loop
            await asyncio.sleep(0.05)

        assert "Dropped message" in caplog.text
        assert "icodaq/test/Recording/Finished" in caplog.text

    async def test_full_buffer_does_not_warn_about_state(
        self, caplog: LogCaptureFixture
    ) -> None:
        """A dropped state is published again after connecting"""

        fake = FakeMQTTClient()
        fake.publish_rc = mqtt.MQTT_ERR_QUEUE_SIZE
        bus = create_bus(fake)
        await bus.start()

        with caplog.at_level(logging.WARNING):
            await bus.publish_state(await build_system_state())
            await asyncio.sleep(0.05)

        assert "Dropped message" not in caplog.text

    async def test_lost_connection_is_logged(
        self, caplog: LogCaptureFixture
    ) -> None:
        """Losing the connection should be logged as a warning"""

        fake = FakeMQTTClient()
        bus = create_bus(fake)
        await bus.start()

        with caplog.at_level(logging.WARNING):
            fake.simulate_disconnect(NOT_AUTHORIZED)
            await asyncio.sleep(0.05)

        assert "Lost connection" in caplog.text

    async def test_close_removes_retained_state(self) -> None:
        """Closing should remove the retained state and disconnect"""

        fake = FakeMQTTClient()
        bus = create_bus(fake)
        await bus.start()
        await bus.publish_state(await build_system_state())
        fake.published.clear()

        await bus.close()

        # Empty retained message removes state from broker
        assert fake.published == [("icodaq/test/State", b"", 1, True)]
        assert fake.disconnected
        assert not fake.loop_running

        # The old state must not come back if the client reconnects
        fake.published.clear()
        fake.simulate_connect(SUCCESS)
        assert not fake.published

    async def test_close_does_not_wait_without_connection(self) -> None:
        """Closing must not wait for a message that cannot be published"""

        fake = FakeMQTTClient()
        fake.connected = False
        infos: list[FakePublishInfo] = []
        original_publish = fake.publish

        def publish(*arguments: Any, **keywords: Any) -> FakePublishInfo:
            infos.append(original_publish(*arguments, **keywords))
            return infos[-1]

        fake.publish = publish  # type: ignore[method-assign]
        bus = create_bus(fake)
        await bus.start()

        await bus.close()

        assert len(infos) == 1
        assert not infos[0].waited_for
        assert fake.disconnected

    async def test_unreachable_broker(self) -> None:
        """Test real client without broker: events are queued, then dropped"""

        bus = MQTTEventBus(
            MQTTSettings(
                broker="127.0.0.1",
                port=1,
                base_topic="icodaq/test",
                buffer_size=2,
            )
        )
        await bus.start()
        # pylint: disable=protected-access
        try:
            codes = [
                bus._publish("icodaq/test/Recording/Finished", "{}", 1, False).rc
                for _ in range(4)
            ]
        finally:
            await bus.close()

        # The first messages are queued (but there is no connection), the
        # ones that do not fit into the buffer are dropped
        assert codes == [
            mqtt.MQTT_ERR_NO_CONN,
            mqtt.MQTT_ERR_NO_CONN,
            mqtt.MQTT_ERR_QUEUE_SIZE,
            mqtt.MQTT_ERR_QUEUE_SIZE,
        ]


class TestLifespan:
    """Test how the MQTT event bus is used by the application"""

    @staticmethod
    def disable_hardware(monkeypatch: MonkeyPatch) -> None:
        """Start the application without CAN connection and cloud"""

        async def nothing(*_arguments: Any) -> None:
            """Do nothing"""

        monkeypatch.setattr(
            api.ICOsystemSingleton, "create_instance_if_none", nothing
        )
        monkeypatch.setattr(api.ICOsystemSingleton, "close_instance", nothing)
        monkeypatch.setattr(
            api, "get_dataspace_config", lambda: SimpleNamespace(enabled=False)
        )

    async def test_state_published_and_cleared(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """The bus should get the state on startup and remove it on shutdown"""

        self.disable_hardware(monkeypatch)
        fake = FakeMQTTClient()
        bus = create_bus(fake)
        monkeypatch.setattr(api, "create_mqtt_event_bus", lambda: bus)

        async with api.lifespan(api.app):
            assert fake.loop_running
            assert [topic for topic, *_ in fake.published] == [
                "icodaq/test/State"
            ]

            fake.published.clear()
            await GeneralMessenger.push_messenger_update()
            assert [topic for topic, *_ in fake.published] == [
                "icodaq/test/State"
            ]

        assert fake.published[-1] == ("icodaq/test/State", b"", 1, True)
        assert not fake.loop_running

        # The bus must not be used after shutdown
        fake.published.clear()
        await GeneralMessenger.push_messenger_update()
        assert not fake.published

    async def test_start_failure_disables_mqtt(
        self, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
    ) -> None:
        """The application should start without MQTT if the bus cannot start"""

        self.disable_hardware(monkeypatch)
        fake = FakeMQTTClient()
        fake.tls_error = FileNotFoundError("ca.pem")
        bus = create_bus(fake, tls=True)
        monkeypatch.setattr(api, "create_mqtt_event_bus", lambda: bus)

        with caplog.at_level(logging.ERROR):
            async with api.lifespan(api.app):
                await GeneralMessenger.push_messenger_update()

        assert "cannot start MQTT" in caplog.text
        assert not fake.published
        assert not fake.loop_running

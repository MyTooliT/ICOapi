"""Keep track of global state of API"""

import asyncio
import logging
from typing import Any, List
from starlette.websockets import WebSocket

from icostate import CANInitError, ICOsystem
from icostate.state import State

from icoapi.models.event_bus import (
    Channel,
    CompositeEventBus,
    EventBus,
    WebSocketEventBus,
)
from icoapi.models.models import (
    Feature,
    MeasurementInstructions,
    MeasurementStatus,
    Metadata,
    SystemStateModel,
    CloudConfig,
)
from icoapi.models.trident import StorageClient
from icoapi.scripts.data_handling import read_and_parse_trident_config
from icoapi.scripts.file_handling import (
    get_dataspace_file_path,
    get_disk_space_in_gib,
)

logger = logging.getLogger(__name__)


class ICOsystemSingleton:
    """
    This class serves as a wrapper around the ICOsystem class. This is required
    as a REST API is inherently stateless and thus has to keep the connection
    to the ICOtronic system open, We need to pass it by reference to all
    functions. Otherwise, after every call to an endpoint, the connection is
    closed and the devices reset to their default parameters. This is intended
    behavior, but unintuitive for a dashboard where the user should feel like
    continuously working with devices.

    Dependency injection: See https://fastapi.tiangolo.com/tutorial/dependencies/
    """

    _instance: ICOsystem | None = None
    _lock = asyncio.Lock()
    _messengers: list[WebSocket] = []

    @classmethod
    async def create_instance_if_none(cls):
        """Create singleton if it does not exist already"""
        try:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = ICOsystem()
                    # STU Connection is required for any CAN communication
                    await cls._instance.connect_stu()
                    await get_messenger().push_messenger_update()
                    logger.info(
                        "Created ICOsystem instance with ID <%s>",
                        id(cls._instance),
                    )
        except CANInitError as error:
            logger.error("Cannot establish CAN connection: %s", error)

    @classmethod
    async def get_instance(cls):
        """Get singleton instance"""

        await cls.create_instance_if_none()
        return cls._instance

    @classmethod
    async def close_instance(cls):
        """Close singleton instance"""

        async with cls._lock:
            if cls._instance is not None:
                logger.debug(
                    "Trying to disconnect CAN connection with ID <%s>",
                    id(cls._instance),
                )
                if cls._instance.state == State.STU_CONNECTED:
                    await cls._instance.disconnect_stu()
                await get_messenger().push_messenger_update()
                logger.debug(
                    "Closing ICOsystem instance with ID <%s>",
                    id(cls._instance),
                )
                cls._instance = None

    @classmethod
    def has_instance(cls):
        """Check if singleton exists"""

        return cls._instance is not None


async def get_system() -> ICOsystem:
    """Get ICOsystem singleton instance"""

    icosystem = await ICOsystemSingleton.get_instance()
    return icosystem


# pylint: disable=too-many-instance-attributes


class MeasurementState:
    """
    This class serves as state management for keeping track of ongoing measurements.
    It should never be instantiated outside the corresponding singleton wrapper.
    """

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.clients: List[WebSocket] = []
        self.lock = asyncio.Lock()
        self.running = False
        self.name: str | None = None
        self.start_time: str | None = None
        self.tool_name: str | None = None
        self.start_supply_voltage: float | None = None
        self.instructions: MeasurementInstructions | None = None
        self.stop_flag = False
        self.pre_meta: Metadata | None = None

    async def reset(self) -> None:
        """Reset measurement"""

        self.task = None
        self.clients = []
        self.lock = asyncio.Lock()
        self.running = False
        self.name = None
        self.start_time = None
        self.tool_name = None
        self.start_supply_voltage = None
        self.instructions = None
        self.stop_flag = False
        self.pre_meta = None
        await get_messenger().push_messenger_update()

    def get_status(self) -> MeasurementStatus:
        """Get measurement status"""

        return MeasurementStatus(
            running=self.running,
            name=self.name,
            start_time=self.start_time,
            tool_name=self.tool_name,
            start_supply_voltage=self.start_supply_voltage,
            instructions=self.instructions,
        )


# pylint: enable=too-many-instance-attributes


class MeasurementSingleton:
    """
    This class serves as a singleton wrapper around the MeasurementState class
    """

    _instance: MeasurementState | None = None

    @classmethod
    def create_instance_if_none(cls):
        """Create singleton instance if it does not exist already"""

        if cls._instance is None:
            cls._instance = MeasurementState()
            logger.info(
                "Created Measurement instance with ID <%s>", id(cls._instance)
            )

    @classmethod
    def get_instance(cls):
        """Get singleton instance"""

        cls.create_instance_if_none()
        return cls._instance

    @classmethod
    def clear_clients(cls):
        """Clear list of WebSocket clients"""

        num_of_clients = len(cls._instance.clients)
        cls._instance.clients.clear()
        logger.info(
            "Cleared %s clients from measurement WebSocket list",
            num_of_clients,
        )


async def get_measurement_state():
    """Get measurement singleton"""

    return MeasurementSingleton().get_instance()


# pylint: disable=missing-function-docstring


class TridentHandler:
    """Singleton Wrapper for the Trident API client"""

    client: StorageClient | None = None
    feature = Feature(enabled=False, healthy=False)

    @classmethod
    async def reset(cls):
        cls.client = None
        cls.feature = Feature(enabled=False, healthy=False)
        await get_messenger().push_messenger_update()
        logger.info("Reset TridentHandler")

    @classmethod
    async def create_client(cls, config: CloudConfig):
        cls.client = StorageClient(
            config.service,
            config.username,
            config.password,
            config.domain,
        )
        if config.manage_assets_path:
            cls.feature.manage_url = f"{config.service}/{config.manage_assets_path}"
        await get_messenger().push_messenger_update()
        logger.info(
            "Created TridentClient for user <%s> at service <%s>",
            config.username,
            config.service,
        )

    @classmethod
    async def set_enabled(cls):
        cls.feature.enabled = True
        await get_messenger().push_messenger_update()
        logger.info("Enabled TridentHandler")

    @classmethod
    async def set_disabled(cls):
        cls.feature.enabled = False
        await get_messenger().push_messenger_update()
        logger.info("Disabled TridentHandler")

    @classmethod
    async def is_enabled(cls) -> bool:
        return cls.feature.enabled

    @classmethod
    async def set_health(cls, healthy: bool):
        cls.feature.healthy = healthy
        await get_messenger().push_messenger_update()
        logger.info("Set TridentHandler health to <%s>", healthy)

    @classmethod
    async def get_client(cls) -> StorageClient | None:
        return cls.client


async def get_trident_client() -> StorageClient | None:
    return await TridentHandler.get_client()


async def get_trident_feature() -> Feature:
    return TridentHandler.feature


def get_dataspace_config():
    return read_and_parse_trident_config(get_dataspace_file_path())


async def setup_trident():
    ds_path = get_dataspace_file_path()
    try:
        dataspace_config = read_and_parse_trident_config(ds_path)
        handler = TridentHandler
        await handler.reset()
        if dataspace_config.enabled:
            await handler.set_enabled()
            await TridentHandler.create_client(dataspace_config)
            client = await TridentHandler.get_client()
            if client is None:
                logger.exception("Failed at creating trident connection")
                await handler.set_health(False)
            else:
                client.get_client().authenticate()
                if client.is_authenticated():
                    await handler.set_health(True)

    except FileNotFoundError:
        logger.warning("Cannot find dataspace config file under %s", ds_path)
        await TridentHandler.reset()
    except KeyError as e:
        logger.exception("Cannot parse dataspace config file: %s", e)
        await TridentHandler.reset()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Cannot establish Trident connection: %s", e)
        await TridentHandler.reset()
        await TridentHandler.set_enabled()


# pylint: enable=missing-function-docstring


async def build_system_state() -> SystemStateModel:
    """Get the current general state of the API"""

    measurement_state = await get_measurement_state()
    cloud = await get_trident_feature()
    return SystemStateModel(
        can_ready=ICOsystemSingleton.has_instance(),
        disk_capacity=get_disk_space_in_gib(),
        cloud=cloud,
        measurement_status=measurement_state.get_status(),
    )


class GeneralMessenger:
    """Publish updates about the general state to all event buses

    The state is built once and then published on every enabled event bus.
    Clients only read from the buses, see :mod:`icoapi.models.event_bus`.
    """

    _websocket_bus = WebSocketEventBus()
    _bus = CompositeEventBus([_websocket_bus])

    @classmethod
    def websocket_bus(cls) -> WebSocketEventBus:
        """Get the event bus for clients connected via WebSocket"""

        return cls._websocket_bus

    @classmethod
    def add_bus(cls, bus: EventBus) -> None:
        """Publish everything to the given event bus too"""

        cls._bus.add_bus(bus)

    @classmethod
    def remove_bus(cls, bus: EventBus) -> None:
        """Stop publishing to the given event bus"""

        cls._bus.remove_bus(bus)

    @classmethod
    async def push_messenger_update(cls):
        """Publish the current general state on all event buses"""

        await cls._bus.publish_state(await build_system_state())

    @classmethod
    async def publish_event(
        cls, channel: Channel, payload: dict[str, Any]
    ) -> None:
        """Publish a one-shot event on all event buses"""

        await cls._bus.publish_event(channel, payload)

    @classmethod
    async def close(cls):
        """Close all event buses"""

        await cls._bus.close()


def get_messenger():
    """Get general messenger"""

    return GeneralMessenger()


def get_websocket_event_bus() -> WebSocketEventBus:
    """Get event bus for clients connected via WebSocket"""

    return GeneralMessenger.websocket_bus()

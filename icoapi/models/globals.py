"""Keep track of global state of API"""

import asyncio
import logging
from typing import List
from starlette.websockets import WebSocket

from icostate import CANInitError, ICOsystem

from icoapi.models.models import (
    Feature,
    MeasurementInstructions,
    MeasurementStatus,
    Metadata,
    SocketMessage,
    SystemStateModel,
    TridentConfig,
)
from icoapi.models.trident import StorageClient
from icoapi.scripts.data_handling import read_and_parse_trident_config
from icoapi.scripts.file_handling import get_dataspace_file_path, get_disk_space_in_gb

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
                    logger.info("Created ICOsystem instance with ID <%s>", id(cls._instance))
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
                await cls._instance.disconnect_stu()
                await get_messenger().push_messenger_update()
                logger.debug("Closing ICOsystem instance with ID <%s>", id(cls._instance))
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
        self.instructions: MeasurementInstructions | None = None
        self.stop_flag = False
        self.wait_for_post_meta = False
        self.pre_meta: Metadata | None = None
        self.post_meta: Metadata | None = None

    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        asyncio.create_task(get_messenger().push_messenger_update())

    async def reset(self) -> None:
        """Reset measurement"""

        self.task = None
        self.clients = []
        self.lock = asyncio.Lock()
        self.running = False
        self.name = None
        self.start_time = None
        self.tool_name = None
        self.instructions = None
        self.stop_flag = False
        self.wait_for_post_meta = False
        self.pre_meta = None
        self.post_meta = None
        await get_messenger().push_messenger_update()

    def get_status(self) -> MeasurementStatus:
        """Get measurement status"""

        return MeasurementStatus(
            running=self.running,
            name=self.name,
            start_time=self.start_time,
            tool_name=self.tool_name,
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
            logger.info("Created Measurement instance with ID <%s>", id(cls._instance))

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
        logger.info("Cleared %s clients from measurement WebSocket list", num_of_clients)


async def get_measurement_state():
    """Get measurement singleton"""

    # We need a coroutine here, since `Measurement.__setattr__`
    # uses `asyncio.create_task`, which requires a running event loop.
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
    async def create_client(cls, config: TridentConfig):
        cls.client = StorageClient(
            config.service,
            config.username,
            config.password,
            config.default_bucket,
            config.domain,
        )
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


class GeneralMessenger:
    """
    This class servers as a handler for all clients which connect to the general state WebSocket.
    """

    _clients: List[WebSocket] = []

    @classmethod
    def add_messenger(cls, messenger: WebSocket):
        """Add messenger client"""

        cls._clients.append(messenger)
        logger.info("Added WebSocket instance to general messenger list")

    @classmethod
    def remove_messenger(cls, messenger: WebSocket):
        """Remove messenger client"""

        try:
            cls._clients.remove(messenger)
            logger.info("Removed WebSocket instance from general messenger list")
        except ValueError:
            logger.warning(
                "Tried removing WebSocket instance from general messenger list but failed."
            )

    @classmethod
    async def push_messenger_update(cls):
        """Push updates about general state to messenger clients"""

        state = await get_measurement_state()
        cloud = await get_trident_feature()
        for client in cls._clients:
            await client.send_json(
                SocketMessage(
                    message="state",
                    data=SystemStateModel(
                        can_ready=ICOsystemSingleton.has_instance(),
                        disk_capacity=get_disk_space_in_gb(),
                        cloud=cloud,
                        measurement_status=state.get_status(),
                    ),
                ).model_dump()
            )

        if (len(cls._clients)) > 0:
            logger.info("Pushed SystemState to %s clients.", len(cls._clients))

    @classmethod
    async def send_post_meta_request(cls):
        """Send post measurement metadata"""

        for client in cls._clients:
            await client.send_json(SocketMessage(message="post_meta_request").model_dump())

    @classmethod
    async def send_post_meta_completed(cls):
        """Send post measurement metadata completed"""

        for client in cls._clients:
            await client.send_json(SocketMessage(message="post_meta_completed").model_dump())


def get_messenger():
    """Get general messenger singleton"""

    return GeneralMessenger()

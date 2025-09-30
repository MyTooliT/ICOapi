import asyncio
import logging
from typing import List
from mytoolit.can.network import CANInitError, Network
from starlette.websockets import WebSocket

from icoapi.models.models import Feature, MeasurementInstructions, MeasurementStatus, Metadata, SocketMessage, \
    SystemStateModel, \
    TridentConfig
from icoapi.models.trident import StorageClient
from icoapi.scripts.data_handling import read_and_parse_trident_config
from icoapi.scripts.file_handling import get_dataspace_file_path, get_disk_space_in_gb

logger = logging.getLogger(__name__)

class NetworkSingleton:
    """
    This class serves as a wrapper around the MyToolIt Network class.
    This is required as a REST API is inherently stateless and thus to stay within one Network,
    we need to pass it by reference to all functions. Otherwise, after every call to an endpoint,
    the network is closed and the devices reset to their default parameters. This is intended behavior,
    but unintuitive for a dashboard where the user should feel like continuously working with devices.

    Dependency injection: See https://fastapi.tiangolo.com/tutorial/dependencies/
    """
    _instance: Network | None = None
    _lock = asyncio.Lock()
    _messengers: list[WebSocket] = []

    @classmethod
    async def create_instance_if_none(cls):
        try:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = Network()
                    await cls._instance.__aenter__()
                    await get_messenger().push_messenger_update()
                    logger.info(f"Created CAN Network instance with ID <{id(cls._instance)}>")
        except CANInitError:
            logger.error("Cannot establish CAN connection")

    @classmethod
    async def get_instance(cls):
        await cls.create_instance_if_none()
        return cls._instance

    @classmethod
    async def close_instance(cls):
        async with cls._lock:
            if cls._instance is not None:
                logger.debug(f"Trying to shut down CAN Network instance with ID <{id(cls._instance)}>")
                await cls._instance.__aexit__(None, None, None)
                await get_messenger().push_messenger_update()
                logger.info(f"Successfully shut down CAN Network instance with ID <{id(cls._instance)}>")
                cls._instance = None

    @classmethod
    def has_instance(cls):
        return cls._instance is not None


async def get_network() -> Network:
    network = await NetworkSingleton.get_instance()
    return network


class MeasurementState:
    """
    This class serves as state management for keeping track of ongoing measurements.
    It should never be instantiated outside the corresponding singleton wrapper.
    """

    def __init__(self):
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

    def __setattr__(self, name: str, value):
        super().__setattr__(name, value)
        asyncio.create_task(get_messenger().push_messenger_update())

    async def reset(self):
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

    def get_status(self):
        return MeasurementStatus(
            running=self.running,
            name=self.name,
            start_time=self.start_time,
            tool_name=self.tool_name,
            instructions=self.instructions
        )


class MeasurementSingleton:
    """
    This class serves as a singleton wrapper around the MeasurementState class
    """

    _instance: MeasurementState | None = None

    @classmethod
    def create_instance_if_none(cls):
        if cls._instance is None:
            cls._instance = MeasurementState()
            logger.info(f"Created Measurement instance with ID <{id(cls._instance)}>")

    @classmethod
    def get_instance(cls):
        cls.create_instance_if_none()
        return cls._instance

    @classmethod
    def clear_clients(cls):
        num_of_clients = len(cls._instance.clients)
        cls._instance.clients.clear()
        logger.info(f"Cleared {num_of_clients} clients from measurement WebSocket list")


async def get_measurement_state():
    # We need a coroutine here, since `Measurement.__setattr__` 
    # uses `asyncio.create_task`, which requires a running event loop.
    return MeasurementSingleton().get_instance()


class TridentHandler:
    """Singleton Wrapper for the Trident API client"""

    client: StorageClient | None = None
    feature = Feature(
        enabled=False,
        healthy=False
    )

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
            config.domain
        )
        await get_messenger().push_messenger_update()
        logger.info(f"Created TridentClient for user <{config.username}> at service <{config.service}>")

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
        logger.info(f"Set TridentHandler health to <{healthy}>")

    @classmethod
    async def get_client(cls) -> StorageClient|None:
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
        logger.warning(f"Cannot find dataspace config file under {ds_path}")
        await TridentHandler.reset()
    except KeyError as e:
        logger.exception(f"Cannot parse dataspace config file: {e}")
        await TridentHandler.reset()
    except Exception as e:
        logger.error(f"Cannot establish Trident connection: {e}")
        await TridentHandler.reset()
        await TridentHandler.set_enabled()


class GeneralMessenger:
    """
    This class servers as a handler for all clients which connect to the general state WebSocket.
    """

    _clients: List[WebSocket] = []

    @classmethod
    def add_messenger(cls, messenger: WebSocket):
        cls._clients.append(messenger)
        logger.info("Added WebSocket instance to general messenger list")

    @classmethod
    def remove_messenger(cls, messenger: WebSocket):
        try:
            cls._clients.remove(messenger)
            logger.info("Removed WebSocket instance from general messenger list")
        except ValueError:
            logger.warning("Tried removing WebSocket instance from general messenger list but failed.")

    @classmethod
    async def push_messenger_update(cls):
        state = await get_measurement_state()
        cloud = await get_trident_feature()
        for client in cls._clients:
            await client.send_json(SocketMessage(
                message="state",
                data=SystemStateModel(
                    can_ready=NetworkSingleton.has_instance(),
                    disk_capacity=get_disk_space_in_gb(),
                    cloud=cloud,
                    measurement_status=state.get_status()
            )).model_dump())

        if(len(cls._clients)) > 0:
            logger.info(f"Pushed SystemState to {len(cls._clients)} clients.")


    @classmethod
    async def send_post_meta_request(cls):
        for client in cls._clients:
            await client.send_json(SocketMessage(
                message="post_meta_request"
            ).model_dump())


    @classmethod
    async def send_post_meta_completed(cls):
        for client in cls._clients:
            await client.send_json(SocketMessage(
                message="post_meta_completed"
            ).model_dump())


def get_messenger():
    return GeneralMessenger()
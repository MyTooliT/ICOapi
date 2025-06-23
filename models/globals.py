import asyncio
import logging
from os import getenv
from typing import List
from mytoolit.can.network import Network
from starlette.websockets import WebSocket

from models.models import MeasurementInstructions, MeasurementStatus, Metadata, SystemStateModel
from models.trident import BaseClient, NoopClient, StorageClient
from scripts.file_handling import get_disk_space_in_gb

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
        async with cls._lock:
            if cls._instance is None:
                cls._instance = Network()
                await cls._instance.__aenter__()
                await get_messenger().push_messenger_update()
                logger.info(f"Created CAN Network instance with ID <{id(cls._instance)}>")

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


def get_measurement_state():
    return MeasurementSingleton().get_instance()


class TridentHandler:
    """Singleton Wrapper for the Trident API client"""

    _client: StorageClient | None = None

    @classmethod
    async def get_client(cls) -> StorageClient:
        if cls._client is None:
            service = getenv("TRIDENT_API_BASE_URL")
            username = getenv("TRIDENT_API_USERNAME")
            password = getenv("TRIDENT_API_PASSWORD")
            default_bucket = getenv("TRIDENT_API_BUCKET")

            cls._client = StorageClient(service, username, password, default_bucket)
            await get_messenger().push_messenger_update()
            logger.info(f"Created TridentClient for service <{service}>")

        return cls._client


async def get_trident_client() -> BaseClient:
    if getenv("TRIDENT_API_ENABLED") == "True":
        client = TridentHandler.get_client()
        return await client
    else:
        return NoopClient()



class GeneralMessenger:
    """
    This class servers as a handler for all clients which connect to the general state WebSocket.
    """

    _clients: List[WebSocket] = []

    @classmethod
    def add_messenger(cls, messenger: WebSocket):
        logger.info("Added WebSocket instance to general messenger list")
        cls._clients.append(messenger)

    @classmethod
    def remove_messenger(cls, messenger: WebSocket):
        try:
            cls._clients.remove(messenger)
            logger.info("Removed WebSocket instance from general messenger list")
        except ValueError:
            logger.warning("Tried removing WebSocket instance from general messenger list but failed.")

    @classmethod
    async def push_messenger_update(cls):
        cloud = await get_trident_client()
        cloud_ready = cloud.is_authenticated()
        for client in cls._clients:
            await client.send_json(SystemStateModel(
                can_ready=NetworkSingleton.has_instance(),
                disk_capacity=get_disk_space_in_gb(),
                cloud_status=bool(cloud_ready),
                measurement_status=get_measurement_state().get_status()
            ).model_dump())

        if(len(cls._clients)) > 0:
            logger.info(f"Updated general messenger list with {len(cls._clients)} clients.")


    @classmethod
    async def send_post_meta_request(cls):
        for client in cls._clients:
            await client.send_text("post_meta_request")


    @classmethod
    async def send_post_meta_completed(cls):
        for client in cls._clients:
            await client.send_text("post_meta_completed")


def get_messenger():
    return GeneralMessenger()
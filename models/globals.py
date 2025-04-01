import asyncio
from os import getenv
from typing import List
from mytoolit.can.network import Network
from starlette.websockets import WebSocket

from models.models import MeasurementInstructions, MeasurementStatus
from models.trident import BaseClient, NoopClient, StorageClient


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

    @classmethod
    async def create_instance_if_none(cls):
        async with cls._lock:
            if cls._instance is None:
                cls._instance = Network()
                await cls._instance.__aenter__()
                print(f"Created Network instance with ID <{id(cls._instance)}>")

    @classmethod
    async def get_instance(cls):
        await cls.create_instance_if_none()
        print(f"Using Network instance with ID <{id(cls._instance)}>")
        return cls._instance

    @classmethod
    async def close_instance(cls):
        async with cls._lock:
            if cls._instance is not None:
                print(f"Shutting down Network instance with ID <{id(cls._instance)}>")
                await cls._instance.__aexit__(None, None, None)
                print(f"Shut down Network instance with ID <{id(cls._instance)}>")
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

    def reset(self):
        self.task = None
        self.clients = []
        self.lock = asyncio.Lock()
        self.running = False
        self.name = None
        self.start_time = None
        self.tool_name = None
        self.instructions = None

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
            print(f"Created Measurement instance with ID <{id(cls._instance)}>")

    @classmethod
    def get_instance(cls):
        cls.create_instance_if_none()
        return cls._instance

    @classmethod
    def clear_clients(cls):
        cls._instance.clients.clear()
        print("Cleared clients")


def get_measurement_state():
    return MeasurementSingleton().get_instance()


class TridentHandler:
    """Singleton Wrapper for the Trident API client"""

    client: StorageClient | None = None

    @classmethod
    async def create_client(cls, service: str, username: str, password: str, default_bucket: str):
        if cls.client is None:
            cls.client = StorageClient(service, username, password, default_bucket)
            print(f"Created Trident Client for service <{service}>")
        return cls.client

    @classmethod
    async def get_client(cls):
        if cls.client is None:
            await cls.create_client(
                service=getenv("TRIDENT_API_BASE_URL"),
                username=getenv("TRIDENT_API_USERNAME"),
                password=getenv("TRIDENT_API_PASSWORD"),
                default_bucket=getenv("TRIDENT_API_BUCKET"))
        return cls.client


async def get_trident_client() -> BaseClient:
    if getenv("TRIDENT_API_ENABLED") == "True":
        client = await TridentHandler.get_client()
        return client
    else:
        return NoopClient()
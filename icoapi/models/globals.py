"""Keep track of global state of API"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated, Any, List
from fastapi import Query
from starlette.websockets import WebSocket

from icostate import CANInitError, ICOsystem
from icostate.state import State
from icotronic.can.error import ErrorResponseError, NoResponseError

from icoapi.models.event_bus import (
    Channel,
    CompositeEventBus,
    EventBus,
    WebSocketEventBus,
)
from icoapi.models.models import (
    CANNetwork,
    CANStatus,
    ConnectedSTHModel,
    Feature,
    MeasurementInstructions,
    MeasurementStatus,
    Metadata,
    MeasurementUnit,
    SystemStateModel,
    CloudConfig,
    UnitStateModel,
)
from icoapi.models.trident import StorageClient
from icoapi.scripts.data_handling import read_and_parse_trident_config
from icoapi.scripts.can_scripts import (
    UnknownCANNetworkError,
    discover_can_networks,
    get_default_can_configuration,
    is_can_autoconnect,
    select_can_network,
)
from icoapi.scripts.errors import (
    HTTP_404_UNIT_NOT_FOUND_EXCEPTION,
    HTTP_409_MEASUREMENT_RUNNING_EXCEPTION,
    HTTP_503_CAN_NOT_CONNECTED_EXCEPTION,
)
from icoapi.scripts.features import multi_stu_support
from icoapi.scripts.simulation import SIMULATED_INTERFACE, SimulatedICOsystem
from icoapi.scripts.file_handling import (
    get_dataspace_file_path,
    get_disk_space_in_gib,
)

logger = logging.getLogger(__name__)


async def _release_connection(system: Any) -> None:
    """Release the CAN notifier and bus of a system, whatever its state

    ``ICOsystem.disconnect_stu`` stops the notifier first and only then shuts
    down the bus. If stopping the notifier fails (e.g. because the adapter was
    unplugged) the bus is never shut down and the PCAN channel stays
    initialized. Opening the channel again then fails until the adapter is
    replugged. Thus we release both resources independently.
    """

    connection = getattr(system, "connection", None)
    notifier = getattr(connection, "notifier", None)
    bus = getattr(connection, "bus", None)

    if notifier is not None:
        try:
            await asyncio.to_thread(notifier.stop)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.warning("Error while stopping CAN notifier: %s", error)
    if bus is not None:
        try:
            await asyncio.to_thread(bus.shutdown)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.warning("Error while shutting down CAN bus: %s", error)
    if connection is not None:
        connection.notifier = None
        connection.bus = None


async def _flush_bus(system: Any) -> None:
    """Drop stale frames in the driver queues, if the interface supports it"""

    bus = getattr(getattr(system, "connection", None), "bus", None)
    reset = getattr(bus, "reset", None)  # PCAN: ``PCAN_Reset`` clears queues
    if reset is None:
        return
    try:
        await asyncio.to_thread(reset)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.warning("Cannot flush CAN buffers: %s", error)


async def _disconnect_system(system: Any) -> None:
    """Close the connection of a system (even if closing it cleanly fails)"""

    logger.debug("Trying to disconnect CAN connection with ID <%s>", id(system))
    try:
        if system.state == State.STU_CONNECTED:
            await system.disconnect_stu()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.warning("Error while disconnecting from STU: %s", error)
    # Make sure the adapter is released, even if the clean shutdown failed
    await _release_connection(system)
    logger.debug("Closed ICOsystem instance with ID <%s>", id(system))


async def open_system(network: CANNetwork) -> ICOsystem:
    """Connect to the STU in a CAN network and check that it responds

    Everything that was opened is released again, if this fails.

    Args:

        network:
            The network to connect to

    Raises:

        CANInitError: If opening the network failed
        NoResponseError: If the STU did not respond

    """

    system = (
        SimulatedICOsystem()
        if network.interface == SIMULATED_INTERFACE
        else ICOsystem()
    )
    configuration = get_default_can_configuration()
    configuration.update(
        interface=network.interface,
        channel=network.channel,
    )
    if network.bitrate is not None:
        configuration["bitrate"] = network.bitrate
    system.connection.configuration = configuration

    try:
        await system.connect_stu()
    except CANInitError as error:
        await _release_connection(system)
        logger.error("Cannot open CAN network: %s", error)
        raise

    await _flush_bus(system)
    try:
        await system.get_stu_mac_address()
    except (NoResponseError, ErrorResponseError) as error:
        logger.error("STU does not respond: %s", error)
        try:
            await system.disconnect_stu()
        except Exception as close_error:  # pylint: disable=broad-exception-caught
            logger.warning("Error while closing network: %s", close_error)
        await _release_connection(system)
        raise

    return system


@dataclass
class Unit:
    """A CAN network with its STU (and the sensor device that is connected)

    Only used with multi STU support: Every STU has a CAN network of its own.
    """

    network: CANNetwork
    system: ICOsystem
    stu_connected: bool = True

    @property
    def key(self) -> str:
        """The name of the unit"""

        return self.network.key

    def connected_sth(self) -> ConnectedSTHModel | None:
        """Get the sensor device the STU is connected to (if any)"""

        attributes = getattr(self.system, "sensor_node_attributes", None)
        if attributes is None:
            return None
        return ConnectedSTHModel(
            name=attributes.name, mac_address=attributes.mac_address.format()
        )

    def state(self) -> UnitStateModel:
        """Get the state of the unit"""

        return UnitStateModel(
            unit=self.key,
            network=self.network,
            stu_connected=self.stu_connected,
            sth_connected=self.connected_sth(),
        )


class ICOsystemSingleton:
    """
    This class serves as a wrapper around the ICOsystem class. This is required
    as a REST API is inherently stateless and thus has to keep the connection
    to the ICOtronic system open, We need to pass it by reference to all
    functions. Otherwise, after every call to an endpoint, the connection is
    closed and the devices reset to their default parameters. This is intended
    behavior, but unintuitive for a dashboard where the user should feel like
    continuously working with devices.

    The wrapper also keeps track of the available CAN networks. Searching for
    networks (:meth:`scan`) and connecting to one (:meth:`connect`) are
    separate steps. A connection is only established on request or at startup
    in headless mode (see :meth:`startup`).

    Dependency injection: See https://fastapi.tiangolo.com/tutorial/dependencies/
    """

    _instance: ICOsystem | None = None
    _lock = asyncio.Lock()
    _messengers: list[WebSocket] = []

    status = CANStatus.NO_NETWORK
    networks: list[CANNetwork] = []
    selected: CANNetwork | None = None
    error: str | None = None
    stu_connected = False

    # Multi STU support: Every connected network is a unit. The attributes
    # above and the instance describe the first unit, which is used by every
    # operation that does not name a unit.
    _units: dict[str, Unit] = {}

    @classmethod
    async def _scan(cls) -> None:
        """Search for CAN networks (caller must hold the lock)"""

        cls.networks = await discover_can_networks()
        logger.info("Found CAN networks: %s", cls.networks)
        if cls._instance is None and cls.status != CANStatus.ERROR:
            cls.status = (
                CANStatus.NETWORK_FOUND
                if cls.networks
                else CANStatus.NO_NETWORK
            )

    @classmethod
    async def scan(cls) -> list[CANNetwork]:
        """Search for CAN networks"""

        async with cls._lock:
            if cls.status == CANStatus.ERROR:
                cls.status = CANStatus.NO_NETWORK
            await cls._scan()
        await get_messenger().push_messenger_update()
        return list(cls.networks)

    @classmethod
    async def _teardown(cls) -> None:
        """Close the connection (caller must hold the lock)

        With multi STU support the connections of all units are closed.
        """

        systems = [unit.system for unit in cls._units.values()]
        if cls._instance is not None and cls._instance not in systems:
            systems.append(cls._instance)
        cls._instance = None
        cls._units = {}
        cls.stu_connected = False
        cls.selected = None
        for system in systems:
            await _disconnect_system(system)

    @classmethod
    def _resolve_network(cls, network: CANNetwork | None) -> CANNetwork:
        """Find the network to connect to (caller must hold the lock)

        Raises:

            NoCANNetworkError: If there is no network to connect to
            UnknownCANNetworkError: If the network was not found
        """

        if network is None:
            return select_can_network(cls.networks)

        for known in cls.networks:
            if (known.interface, known.channel) == (
                network.interface,
                network.channel,
            ):
                return known

        cls.status = (
            CANStatus.NETWORK_FOUND if cls.networks else CANStatus.NO_NETWORK
        )
        raise UnknownCANNetworkError(
            f"CAN network <{network.interface}:{network.channel}> not found"
        )

    @classmethod
    async def connect(cls, network: CANNetwork | None = None) -> None:
        """Connect to a CAN network and check that the STU responds

        Without multi STU support the connection to another network is
        closed first. With it the network becomes another unit (and the
        connection to the network is replaced, if it already is one).

        Args:

            network:
                The network to connect to. If not given, the network matching
                the default configuration is used, or else the first one found.

        Raises:

            NoCANNetworkError: If there is no network to connect to
            UnknownCANNetworkError: If the network was not found
            CANInitError: If opening the network failed
            NoResponseError: If the STU did not respond
        """

        async with cls._lock:
            if multi_stu_support():
                await cls._connect_unit(network)
            else:
                await cls._connect_single(network)
        await get_messenger().push_messenger_update()

    @classmethod
    async def _connect_single(cls, network: CANNetwork | None) -> None:
        """Connect to a network and close the connection to any other"""

        if cls._instance is not None:
            await cls._teardown()

        if not cls.networks:
            await cls._scan()
        network = cls._resolve_network(network)

        cls.status = CANStatus.CONNECTING
        cls.selected = network
        cls.error = None
        await get_messenger().push_messenger_update()

        try:
            system = await open_system(network)
        except CANInitError as error:
            cls.status = CANStatus.ERROR
            cls.error = str(error)
            cls.selected = None
            await get_messenger().push_messenger_update()
            raise
        except (NoResponseError, ErrorResponseError):
            cls.status = CANStatus.NETWORK_FOUND
            cls.error = "The STU did not respond"
            cls.selected = None
            await get_messenger().push_messenger_update()
            raise

        cls._instance = system
        cls.stu_connected = True
        cls.status = CANStatus.CONNECTED
        logger.info(
            "Created ICOsystem instance with ID <%s> on <%s:%s>",
            id(system),
            network.interface,
            network.channel,
        )

    @classmethod
    async def _connect_unit(cls, network: CANNetwork | None) -> None:
        """Add a network as unit (caller must hold the lock)"""

        if not cls.networks:
            await cls._scan()
        network = cls._resolve_network(network)

        previous = cls._units.pop(network.key, None)
        if previous is not None:
            await _disconnect_system(previous.system)
            cls._update_primary_unit()

        first = not cls._units
        if first:
            cls.status = CANStatus.CONNECTING
            cls.selected = network
            cls.error = None
            await get_messenger().push_messenger_update()

        try:
            system = await open_system(network)
        except (CANInitError, NoResponseError, ErrorResponseError) as error:
            if first:
                cls.status = (
                    CANStatus.ERROR
                    if isinstance(error, CANInitError)
                    else CANStatus.NETWORK_FOUND
                )
                cls.error = (
                    str(error)
                    if isinstance(error, CANInitError)
                    else "The STU did not respond"
                )
                cls.selected = None
                await get_messenger().push_messenger_update()
            else:
                # The other units keep working
                cls._update_primary_unit()
            raise

        cls._units[network.key] = Unit(network, system)
        cls._update_primary_unit()
        cls.error = None
        cls.status = CANStatus.CONNECTED
        logger.info(
            "Added unit <%s> with ICOsystem instance with ID <%s>",
            network.key,
            id(system),
        )

    @classmethod
    def _update_primary_unit(cls) -> None:
        """Make the first unit the one the singleton describes"""

        unit = next(iter(cls._units.values()), None)
        cls._instance = None if unit is None else unit.system
        cls.selected = None if unit is None else unit.network
        cls.stu_connected = unit is not None and unit.stu_connected

    @classmethod
    async def disconnect(cls, unit: str | None = None) -> None:
        """Disconnect from the CAN network

        Args:

            unit:
                With multi STU support the name of the unit that should be
                disconnected. Without it all units are disconnected.

        Raises:

            KeyError: If there is no such unit
        """

        async with cls._lock:
            if unit is not None and multi_stu_support():
                if unit not in cls._units:
                    raise KeyError(unit)
                await _disconnect_system(cls._units.pop(unit).system)
                cls._update_primary_unit()
                if not cls._units:
                    cls.status = (
                        CANStatus.NETWORK_FOUND
                        if cls.networks
                        else CANStatus.NO_NETWORK
                    )
            else:
                await cls._teardown()
                cls.status = (
                    CANStatus.NETWORK_FOUND
                    if cls.networks
                    else CANStatus.NO_NETWORK
                )
            cls.error = None
        await get_messenger().push_messenger_update()

    @classmethod
    async def reset(cls) -> None:
        """Release the adapter, flush buffers and reconnect

        Does in software what replugging the adapter does: the previous
        connection is released completely, the driver gets a moment to free the
        channel, networks are searched again and the previously selected
        network is opened again (if there was one).
        """

        previous = [unit.network for unit in cls._units.values()] or (
            [cls.selected] if cls.selected is not None else []
        )
        await cls.disconnect()
        await asyncio.sleep(0.5)
        if not previous:
            await cls.startup(autoconnect=is_can_autoconnect())
            return
        await cls.scan()
        # With several units a unit that is gone does not keep the others
        # from reconnecting
        failure: Exception | None = None
        for network in previous:
            try:
                await cls.connect(network)
            except Exception as error:  # pylint: disable=broad-exception-caught
                if len(previous) == 1:
                    raise
                logger.error("Cannot reconnect unit <%s>: %s", network.key, error)
                failure = failure or error
        if failure is not None and not cls._units:
            raise failure

    @classmethod
    async def startup(cls, autoconnect: bool = False) -> None:
        """Search for CAN networks and connect once, if requested"""

        try:
            await cls.scan()
            if autoconnect:
                if cls.networks and multi_stu_support():
                    # Every STU has a CAN network of its own
                    for network in list(cls.networks):
                        try:
                            await cls.connect(network)
                        except Exception as error:  # pylint: disable=broad-exception-caught
                            logger.warning(
                                "Autoconnect: cannot use network <%s>: %s",
                                network.key,
                                error,
                            )
                elif cls.networks:
                    await cls.connect()
                else:
                    logger.warning("Autoconnect: no CAN network found")
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error("Cannot connect to CAN network: %s", error)

    @classmethod
    async def refresh_stu_connected(cls, connected: bool) -> None:
        """Update whether the STU responds"""

        if cls._instance is None or cls.stu_connected == connected:
            return
        cls.stu_connected = connected
        unit = next(iter(cls._units.values()), None)
        if unit is not None:
            unit.stu_connected = connected
        await get_messenger().push_messenger_update()

    @classmethod
    async def refresh_unit_stu_connected(
        cls, unit: str, connected: bool
    ) -> None:
        """Update whether the STU of a unit responds"""

        found = cls._units.get(unit)
        if found is None or found.stu_connected == connected:
            return
        found.stu_connected = connected
        cls._update_primary_unit()
        await get_messenger().push_messenger_update()

    @classmethod
    async def refresh_system_stu_connected(
        cls, system: Any, connected: bool
    ) -> None:
        """Update whether the STU of the unit that uses the system responds"""

        for unit in cls._units.values():
            if unit.system is system:
                await cls.refresh_unit_stu_connected(unit.key, connected)
                return
        await cls.refresh_stu_connected(connected)

    @classmethod
    def units(cls) -> list[Unit]:
        """Get all units

        Without multi STU support the connected network is the only unit.
        """

        if cls._units:
            return list(cls._units.values())
        if cls._instance is not None and cls.selected is not None:
            return [Unit(cls.selected, cls._instance, cls.stu_connected)]
        return []

    @classmethod
    def get_unit(cls, unit: str) -> Unit | None:
        """Get the unit with the given name (if there is one)"""

        return next((found for found in cls.units() if found.key == unit), None)

    @classmethod
    async def get_instance(cls):
        """Get singleton instance (``None`` if not connected)"""

        return cls._instance

    @classmethod
    async def close_instance(cls):
        """Close singleton instance on shutdown"""

        async with cls._lock:
            await cls._teardown()
            cls.status = (
                CANStatus.NETWORK_FOUND if cls.networks else CANStatus.NO_NETWORK
            )
        await get_messenger().push_messenger_update()

    @classmethod
    def connected_sth(cls) -> ConnectedSTHModel | None:
        """Get the sensor device the STU is connected to (if any)"""

        attributes = getattr(cls._instance, "sensor_node_attributes", None)
        if attributes is None:
            return None
        return ConnectedSTHModel(
            name=attributes.name, mac_address=attributes.mac_address.format()
        )

    @classmethod
    def has_instance(cls):
        """Check if singleton exists"""

        return cls._instance is not None


async def get_system(
    unit: Annotated[
        str | None,
        Query(
            description=(
                "Name of the unit (`interface:channel` of its CAN network) "
                "the request is for. Only needed with multi STU support, "
                "otherwise the first unit is used."
            )
        ),
    ] = None,
) -> ICOsystem:
    """Get ICOsystem singleton instance

    Args:

        unit:
            The name of the unit to use (default: The first unit)

    Raises:

        HTTPException:
            If there is no connection to a CAN network (503) or no such unit
            (404)
    """

    icosystem = await ICOsystemSingleton.get_instance()
    if unit is not None:
        found = ICOsystemSingleton.get_unit(unit)
        if found is None:
            raise HTTP_404_UNIT_NOT_FOUND_EXCEPTION
        return found.system
    if icosystem is None:
        raise HTTP_503_CAN_NOT_CONNECTED_EXCEPTION
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
        self.units: list[MeasurementUnit] | None = None
        self.stop_flag = False
        self.pre_meta: Metadata | None = None

    async def reset(self) -> None:
        """Reset measurement"""

        self.task = None
        self.clients = []
        # Keep the lock: replacing it would let a waiting caller and a new one
        # hold "the" lock at the same time
        self.running = False
        self.name = None
        self.start_time = None
        self.tool_name = None
        self.start_supply_voltage = None
        self.instructions = None
        self.units = None
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
            units=self.units,
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


async def require_no_measurement() -> None:
    """Reject a request while a measurement is running

    Use as dependency of routes that would interfere with a running
    measurement, e.g. by closing the CAN connection or by scanning the CAN
    bus. Several clients can use the API at the same time, so the UI of one
    client disabling such actions is not enough.

    Raises:

        HTTPException: 409, if a measurement is running

    """

    if MeasurementSingleton.get_instance().running:
        raise HTTP_409_MEASUREMENT_RUNNING_EXCEPTION


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
        can_network_found=len(ICOsystemSingleton.networks) > 0,
        stu_connected=(
            ICOsystemSingleton.has_instance()
            and ICOsystemSingleton.stu_connected
        ),
        can_status=ICOsystemSingleton.status,
        can_networks=list(ICOsystemSingleton.networks),
        can_selected=ICOsystemSingleton.selected,
        can_error=ICOsystemSingleton.error,
        sth_connected=ICOsystemSingleton.connected_sth(),
        disk_capacity=get_disk_space_in_gib(),
        cloud=cloud,
        measurement_status=measurement_state.get_status(),
        units=(
            [unit.state() for unit in ICOsystemSingleton.units()]
            if multi_stu_support()
            else None
        ),
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

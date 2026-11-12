"""Tests for CAN network discovery and connection handling"""

# -- Imports ------------------------------------------------------------------

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, ClassVar

from conftest import RecordingEventBus
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from icostate import CANInitError
from icostate.state import State
from icotronic.can.error import NoResponseError
from netaddr import EUI
from pytest import MonkeyPatch, fixture, mark, raises

from icoapi.api import app
from icoapi.models import globals as globals_module
from icoapi.models.globals import (
    GeneralMessenger,
    ICOsystemSingleton,
    build_system_state,
    get_system,
)
from icoapi.models.models import CANNetwork, CANStatus
from icoapi.scripts import can_scripts
from icoapi.scripts.can_scripts import (
    NoCANNetworkError,
    UnknownCANNetworkError,
    discover_can_networks,
    select_can_network,
)

# -- Classes ------------------------------------------------------------------


class FakeSystem:
    """Replacement for ``ICOsystem`` that does not need hardware"""

    init_error: Exception | None = None
    probe_error: Exception | None = None
    created: ClassVar[list["FakeSystem"]] = []

    def __init__(self) -> None:
        self.connection = SimpleNamespace(configuration={})
        self.state = State.DISCONNECTED
        self.disconnected = False
        self.sensor_node_attributes = None
        FakeSystem.created.append(self)

    async def connect_stu(self) -> None:
        """Connect to STU"""

        if FakeSystem.init_error is not None:
            raise FakeSystem.init_error
        self.state = State.STU_CONNECTED

    async def get_stu_mac_address(self) -> str:
        """Probe STU"""

        if FakeSystem.probe_error is not None:
            raise FakeSystem.probe_error
        return "00:00:00:00:00:00"

    async def disconnect_stu(self) -> None:
        """Disconnect from STU"""

        self.disconnected = True
        self.state = State.DISCONNECTED


# -- Fixtures -----------------------------------------------------------------

# pylint: disable=redefined-outer-name,unused-argument

NETWORK_1 = CANNetwork(interface="pcan", channel="PCAN_USBBUS1", bitrate=1000000)
NETWORK_2 = CANNetwork(interface="pcan", channel="PCAN_USBBUS2", bitrate=1000000)


@fixture
def networks(monkeypatch: MonkeyPatch) -> list[CANNetwork]:
    """Networks returned by the (mocked) discovery"""

    found: list[CANNetwork] = []

    async def discover() -> list[CANNetwork]:
        return list(found)

    monkeypatch.setattr(globals_module, "discover_can_networks", discover)
    return found


@fixture(autouse=True)
def reset_singleton(monkeypatch: MonkeyPatch) -> Iterator[None]:
    """Use fake system and reset the singleton around each test"""

    FakeSystem.init_error = None
    FakeSystem.probe_error = None
    FakeSystem.created = []
    monkeypatch.setattr(globals_module, "ICOsystem", FakeSystem)

    def reset() -> None:
        ICOsystemSingleton._instance = None  # pylint: disable=protected-access
        ICOsystemSingleton.status = CANStatus.NO_NETWORK
        ICOsystemSingleton.networks = []
        ICOsystemSingleton.selected = None
        ICOsystemSingleton.error = None
        ICOsystemSingleton.stu_connected = False

    reset()
    yield
    reset()


@fixture
def bus() -> Iterator[RecordingEventBus]:
    """Record published states"""

    recording_bus = RecordingEventBus()
    GeneralMessenger.add_bus(recording_bus)
    yield recording_bus
    GeneralMessenger.remove_bus(recording_bus)


@fixture
async def http() -> Any:
    """HTTP client that does not run the application lifespan"""

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1/"
    ) as http_client:
        yield http_client


# -- Tests --------------------------------------------------------------------


class TestDiscovery:
    """Test discovery helpers"""

    async def test_no_networks(self, monkeypatch: MonkeyPatch) -> None:
        """Finding nothing returns an empty list"""

        monkeypatch.setattr(can_scripts.can, "detect_available_configs", lambda **_: [])
        assert await discover_can_networks() == []

    async def test_backend_error_means_no_networks(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """Backend errors are no reason to fail"""

        def fail(**_: Any) -> None:
            raise OSError("PCBUSB missing")

        monkeypatch.setattr(can_scripts.can, "detect_available_configs", fail)
        assert await discover_can_networks() == []

    async def test_duplicates_removed(self, monkeypatch: MonkeyPatch) -> None:
        """Equal configurations are only listed once"""

        configuration = {"interface": "pcan", "channel": "PCAN_USBBUS1"}
        monkeypatch.setattr(
            can_scripts.can,
            "detect_available_configs",
            lambda **_: [configuration, dict(configuration)],
        )
        assert len(await discover_can_networks()) == 1

    def test_select_empty(self) -> None:
        """Selecting from nothing fails"""

        with raises(NoCANNetworkError):
            select_can_network([])

    def test_select_prefers_default(self, monkeypatch: MonkeyPatch) -> None:
        """The default channel wins over the first network"""

        monkeypatch.setattr(can_scripts, "get_default_can_network", lambda: NETWORK_2)
        assert select_can_network([NETWORK_1, NETWORK_2]) == NETWORK_2


class TestSingleton:
    """Test the CAN lifecycle of the singleton"""

    async def test_no_network(self, networks, bus) -> None:
        """Without network the state says so and routes return 503"""

        await ICOsystemSingleton.scan()

        state = await build_system_state()
        assert state.can_network_found is False
        assert state.stu_connected is False
        assert state.can_status == CANStatus.NO_NETWORK
        assert len(bus.states) == 1
        with raises(HTTPException) as error:
            await get_system()
        assert error.value.status_code == 503

    async def test_scan_only(self, networks, bus) -> None:
        """Without autoconnect, startup does not connect"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.startup(autoconnect=False)

        state = await build_system_state()
        assert state.can_network_found is True
        assert state.stu_connected is False
        assert state.can_status == CANStatus.NETWORK_FOUND
        assert FakeSystem.created == []

    async def test_autoconnect(self, networks, bus) -> None:
        """Autoconnect connects once and uses the network configuration"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.startup(autoconnect=True)

        assert len(FakeSystem.created) == 1
        system = FakeSystem.created[0]
        assert system.connection.configuration["channel"] == "PCAN_USBBUS1"
        assert await get_system() is system
        state = await build_system_state()
        assert state.can_status == CANStatus.CONNECTED
        assert state.stu_connected is True
        assert state.can_selected == NETWORK_1
        assert [s.can_status for s in bus.states] == [
            CANStatus.NETWORK_FOUND,
            CANStatus.CONNECTING,
            CANStatus.CONNECTED,
        ]

    async def test_autoconnect_probe_failure_no_stale_instance(
        self, networks, bus
    ) -> None:
        """A failed STU probe leaves no instance behind"""

        networks.append(NETWORK_1)
        FakeSystem.probe_error = NoResponseError("no answer")
        await ICOsystemSingleton.startup(autoconnect=True)

        assert not ICOsystemSingleton.has_instance()
        assert FakeSystem.created[0].disconnected
        state = await build_system_state()
        assert state.stu_connected is False
        assert state.can_network_found is True
        assert state.can_status == CANStatus.NETWORK_FOUND
        assert state.can_error is not None
        with raises(HTTPException):
            await get_system()

    async def test_init_error(self, networks, bus) -> None:
        """A network that cannot be opened results in an error state"""

        networks.append(NETWORK_1)
        FakeSystem.init_error = CANInitError("interface down")
        await ICOsystemSingleton.scan()
        with raises(CANInitError):
            await ICOsystemSingleton.connect()

        state = await build_system_state()
        assert state.can_status == CANStatus.ERROR
        assert state.can_error == "interface down"
        assert state.can_network_found is True

    async def test_unknown_network(self, networks, bus) -> None:
        """Connecting to a network that was not found fails"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.scan()
        with raises(UnknownCANNetworkError):
            await ICOsystemSingleton.connect(NETWORK_2)
        assert not ICOsystemSingleton.has_instance()

    async def test_stu_connected_refresh(self, networks, bus) -> None:
        """STU connection loss keeps the network but is pushed"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.startup(autoconnect=True)
        count = len(bus.states)

        await ICOsystemSingleton.refresh_stu_connected(False)
        state = await build_system_state()
        assert state.stu_connected is False
        assert state.can_network_found is True
        assert len(bus.states) == count + 1

        await ICOsystemSingleton.refresh_stu_connected(False)
        assert len(bus.states) == count + 1

    async def test_disconnect(self, networks, bus) -> None:
        """Disconnecting closes the system and resets the status"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.startup(autoconnect=True)
        system = FakeSystem.created[0]

        await ICOsystemSingleton.disconnect()

        assert system.disconnected
        assert ICOsystemSingleton.status == CANStatus.NETWORK_FOUND
        assert ICOsystemSingleton.selected is None
        assert bus.states[-1].can_status == CANStatus.NETWORK_FOUND


class TestRoutes:
    """Test the ``/can`` endpoints"""

    async def test_networks(self, networks, http) -> None:
        """Listing networks triggers a scan"""

        networks.append(NETWORK_1)
        response = await http.get("can/networks")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "NETWORK_FOUND"
        assert body["networks"][0]["channel"] == "PCAN_USBBUS1"
        assert body["selected"] is None

    async def test_connect_and_disconnect(self, networks, http) -> None:
        """Connect to a named network and disconnect again"""

        networks.extend([NETWORK_1, NETWORK_2])
        response = await http.put(
            "can/connect",
            json={"interface": "pcan", "channel": "PCAN_USBBUS2"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "CONNECTED"
        assert response.json()["selected"]["channel"] == "PCAN_USBBUS2"

        response = await http.put("can/disconnect")
        assert response.status_code == 200
        assert response.json()["status"] == "NETWORK_FOUND"

    async def test_connect_default(self, networks, http) -> None:
        """Connecting without body uses a found network"""

        networks.append(NETWORK_1)
        response = await http.put("can/connect")
        assert response.status_code == 200
        assert response.json()["status"] == "CONNECTED"

    async def test_connect_unknown(self, networks, http) -> None:
        """Unknown networks return 404"""

        networks.append(NETWORK_1)
        response = await http.put(
            "can/connect", json={"interface": "pcan", "channel": "nope"}
        )
        assert response.status_code == 404

    async def test_connect_no_network(self, networks, http) -> None:
        """No networks at all return 404"""

        response = await http.put("can/connect")
        assert response.status_code == 404

    async def test_connect_probe_failure(self, networks, http) -> None:
        """A silent STU returns 502"""

        networks.append(NETWORK_1)
        FakeSystem.probe_error = NoResponseError("no answer")
        response = await http.put("can/connect")
        assert response.status_code == 502

    async def test_connect_init_failure(self, networks, http) -> None:
        """A network that cannot be opened returns 502 with the reason"""

        networks.append(NETWORK_1)
        FakeSystem.init_error = CANInitError("interface down")
        response = await http.put("can/connect")
        assert response.status_code == 502
        assert "interface down" in response.json()["detail"]

    @mark.parametrize("path", ["stu", "sth"])
    async def test_routes_without_connection(self, networks, http, path) -> None:
        """Routes needing the CAN connection return 503"""

        response = await http.get(path)
        assert response.status_code == 503


class TestPlatformDiscovery:
    """Test which interfaces are searched"""

    async def test_linux_searches_socketcan_and_pcan(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """Both interfaces are probed on Linux, one failure is tolerated"""

        monkeypatch.setattr(can_scripts, "platform", "linux")
        probed = []

        def detect(interfaces: list[str]) -> list[dict[str, str]]:
            probed.extend(interfaces)
            if interfaces == ["pcan"]:
                raise OSError("no pcan")
            return [{"interface": "socketcan", "channel": "can0"}]

        monkeypatch.setattr(can_scripts.can, "detect_available_configs", detect)
        networks = await discover_can_networks()
        assert probed == ["socketcan", "pcan"]
        assert [n.channel for n in networks] == ["can0"]

    async def test_other_platforms_only_pcan(self, monkeypatch: MonkeyPatch) -> None:
        """SocketCAN is not probed outside of Linux"""

        monkeypatch.setattr(can_scripts, "platform", "darwin")
        assert can_scripts.get_discovery_interfaces() == ["pcan"]


class TestConnectedSTH:
    """Test that the state reports the connected sensor device"""

    async def test_state_reports_connected_sth(self, networks) -> None:
        """A page reload must be able to learn about the STH from the state"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.connect()
        assert (await build_system_state()).sth_connected is None

        system = FakeSystem.created[-1]
        system.sensor_node_attributes = SimpleNamespace(
            name="Test-STH", mac_address=EUI("14-2D-41-D7-77-7D")
        )
        state = await build_system_state()

        assert state.sth_connected is not None
        assert state.sth_connected.name == "Test-STH"
        assert state.sth_connected.mac_address == "14-2D-41-D7-77-7D"

    async def test_no_sth_without_connection(self) -> None:
        """Without CAN connection there is no sensor device"""

        assert (await build_system_state()).sth_connected is None


class TestResetCAN:
    """Test ``PUT /reset-can``"""

    async def test_reconnects_to_previous_network(self, networks, http) -> None:
        """A connected API reconnects to the same network"""

        networks.extend([NETWORK_1, NETWORK_2])
        await ICOsystemSingleton.connect(NETWORK_2)

        response = await http.put("reset-can")

        assert response.status_code == 200
        assert ICOsystemSingleton.status == CANStatus.CONNECTED
        assert ICOsystemSingleton.selected == NETWORK_2

    async def test_no_reconnect_if_not_connected(
        self, networks, http, monkeypatch: MonkeyPatch
    ) -> None:
        """Without connection and autoconnect only a scan happens"""

        monkeypatch.delenv("ICOAPI_CAN_AUTOCONNECT", raising=False)
        networks.append(NETWORK_1)

        response = await http.put("reset-can")

        assert response.status_code == 200
        assert ICOsystemSingleton.status == CANStatus.NETWORK_FOUND
        assert FakeSystem.created == []


class TestSTUConnectedTracking:
    """Test that lost STU responses are reflected in the state"""

    async def test_no_response_in_route_clears_stu_connected(
        self, networks, http, monkeypatch: MonkeyPatch
    ) -> None:
        """A ``NoResponseError`` in an STH route sets ``stu_connected``"""

        networks.append(NETWORK_1)
        await ICOsystemSingleton.connect()
        assert ICOsystemSingleton.stu_connected

        async def fail(*_: Any) -> None:
            raise NoResponseError("no answer")

        monkeypatch.setattr(
            "icoapi.routers.sth_routes.get_sth_devices_from_network", fail
        )
        response = await http.get("sth")

        assert response.status_code == 502
        state = await build_system_state()
        assert state.stu_connected is False
        assert state.can_network_found is True

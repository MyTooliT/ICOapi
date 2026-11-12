"""Tests for the simulated ICOtronic hardware

These tests do not need any hardware.
"""

# -- Imports ------------------------------------------------------------------

from collections.abc import Iterator
from typing import Any

from httpx import AsyncClient
from icostate import ICOsystem
from icostate.error import IncorrectStateError
from icotronic.can.error import NoResponseError
from icotronic.can.sensor import SensorConfiguration
from icotronic.can.streaming import StreamingConfiguration
from pytest import MonkeyPatch, fixture, mark, raises

from icoapi.models.models import CANNetwork
from icoapi.scripts import can_scripts
from icoapi.scripts.can_scripts import discover_can_networks
from icoapi.scripts.simulation import (
    SIMULATED_CHANNEL,
    SIMULATED_INTERFACE,
    SimulatedICOsystem,
    get_simulated_hardware,
    reset_simulated_hardware,
    simulation_mode,
)

# -- Fixtures -----------------------------------------------------------------

# pylint: disable=redefined-outer-name

SIMULATED = CANNetwork(
    interface=SIMULATED_INTERFACE, channel=SIMULATED_CHANNEL, bitrate=1000000
)


@fixture(autouse=True)
def simulation(
    monkeypatch: MonkeyPatch, isolated_can_state: None
) -> Iterator[None]:
    """Only offer the simulated network, without delays, and start fresh"""

    del isolated_can_state

    monkeypatch.setenv("ICOAPI_SIMULATE", "only")
    monkeypatch.setenv("ICOAPI_SIMULATE_LATENCY", "0")
    monkeypatch.delenv("ICOAPI_SIMULATE_DATALOSS", raising=False)
    reset_simulated_hardware()

    yield
    reset_simulated_hardware()


@fixture
async def system() -> Any:
    """Simulated system, connected to the STU"""

    simulated = SimulatedICOsystem()
    await simulated.connect_stu()
    yield simulated
    if simulated.state.name == "SENSOR_NODE_CONNECTED":
        await simulated.disconnect_sensor_node()
    await simulated.disconnect_stu()


# -- Tests --------------------------------------------------------------------


class TestDiscovery:
    """Test that the simulated network is offered"""

    def test_mode(self, monkeypatch: MonkeyPatch) -> None:
        """``ICOAPI_SIMULATE`` selects the mode"""

        for value, mode in (
            ("only", "only"),
            ("ONLY", "only"),
            ("1", "on"),
            ("true", "on"),
            ("", ""),
            ("0", ""),
            ("nonsense", ""),
        ):
            monkeypatch.setenv("ICOAPI_SIMULATE", value)
            assert simulation_mode() == mode

    async def test_only_simulated(self, monkeypatch: MonkeyPatch) -> None:
        """Real adapters are not searched in mode ``only``"""

        def detect(**_: Any) -> list[dict[str, Any]]:
            raise AssertionError("Searched for real adapters")

        monkeypatch.setattr(can_scripts.can, "detect_available_configs", detect)

        assert await discover_can_networks() == [SIMULATED]

    async def test_added_to_real_networks(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """In mode ``on`` the simulated network comes after the real ones"""

        monkeypatch.setenv("ICOAPI_SIMULATE", "1")
        monkeypatch.setattr(
            can_scripts.can,
            "detect_available_configs",
            lambda **_: [{"interface": "pcan", "channel": "PCAN_USBBUS1"}],
        )
        networks = await discover_can_networks()

        assert [network.interface for network in networks] == [
            "pcan",
            SIMULATED_INTERFACE,
        ]

    async def test_off(self, monkeypatch: MonkeyPatch) -> None:
        """Without ``ICOAPI_SIMULATE`` there is no simulated network"""

        monkeypatch.delenv("ICOAPI_SIMULATE")
        monkeypatch.setattr(
            can_scripts.can, "detect_available_configs", lambda **_: []
        )

        assert await discover_can_networks() == []


class TestDevices:
    """Test which devices are simulated"""

    @staticmethod
    def devices() -> list[tuple[str, str]]:
        """Get name and MAC address of the simulated devices"""

        return [
            (device.name, device.mac_address.format())
            for device in get_simulated_hardware().devices
        ]

    def test_defaults(self) -> None:
        """The development board of the platform's examples is there"""

        assert self.devices()[0] == ("Test-STH", "14-2D-41-D7-77-7D")

    def test_configured(self, monkeypatch: MonkeyPatch) -> None:
        """``ICOAPI_SIMULATE_DEVICES`` replaces the devices"""

        monkeypatch.setenv(
            "ICOAPI_SIMULATE_DEVICES",
            "Tool-A=BC:33:AC:CA:CD:A2, Tool-B=3C-2E-F5-68-19-11",
        )
        reset_simulated_hardware()

        assert self.devices() == [
            ("Tool-A", "BC-33-AC-CA-CD-A2"),
            ("Tool-B", "3C-2E-F5-68-19-11"),
        ]

    def test_invalid_entries_are_ignored(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """Entries that are no ``Name=MAC`` are skipped"""

        monkeypatch.setenv("ICOAPI_SIMULATE_DEVICES", "nonsense,Tool-A=xyz")
        reset_simulated_hardware()

        # Nothing valid is left, so the defaults are used
        assert self.devices()[0][0] == "Test-STH"


class TestSystem:
    """Test the simulated ``ICOsystem``"""

    async def test_is_real_system(self, system: SimulatedICOsystem) -> None:
        """The simulation is an ``ICOsystem``, including its state checks"""

        assert isinstance(system, ICOsystem)
        with raises(IncorrectStateError):
            await system.connect_stu()
        with raises(IncorrectStateError):
            await system.get_sensor_configuration()

    async def test_scan_and_connect(self, system: SimulatedICOsystem) -> None:
        """Sensor devices are found and can be connected"""

        nodes = await system.collect_sensor_nodes()
        assert [node.name for node in nodes] == ["Test-STH", "Sim-STH2"]

        mac_address = nodes[0].mac_address.format()
        await system.connect_sensor_node_mac(mac_address)

        assert await system.is_sensor_node_connected()
        assert system.sensor_node_attributes is not None
        assert system.sensor_node_attributes.name == "Test-STH"
        assert system.sensor_node_attributes.mac_address == nodes[0].mac_address
        assert await system.sensor_node.get_supply_voltage() > 3

        await system.disconnect_sensor_node()
        assert not await system.is_sensor_node_connected()

    async def test_unreachable_sensor_node(
        self, system: SimulatedICOsystem
    ) -> None:
        """Devices out of range are neither found nor connectable"""

        device = get_simulated_hardware().devices[1]
        device.in_range = False

        nodes = await system.collect_sensor_nodes()
        assert [node.name for node in nodes] == ["Test-STH"]
        with raises(TimeoutError):
            await system.connect_sensor_node_mac(device.mac_address.format())

    async def test_rename_is_kept(self, system: SimulatedICOsystem) -> None:
        """A new name is still there after reconnecting"""

        mac_address = (await system.collect_sensor_nodes())[0].mac_address
        old_name = await system.rename("Renamed", mac_address.format())

        assert old_name == "Test-STH"
        nodes = await system.collect_sensor_nodes()
        assert nodes[0].name == "Renamed"

    async def test_adc_configuration(self, system: SimulatedICOsystem) -> None:
        """The ADC configuration can be written and read back"""

        mac_address = (await system.collect_sensor_nodes())[0].mac_address
        await system.connect_sensor_node_mac(mac_address.format())

        default = await system.get_adc_configuration()
        assert round(default.sample_rate()) == 9524

        await system.set_adc_configuration(
            type(default)(
                prescaler=8,
                acquisition_time=8,
                oversampling_rate=64,
                reference_voltage=3.3,
            )
        )
        assert (await system.get_adc_configuration()).prescaler == 8

    async def test_sensor_configuration(
        self, system: SimulatedICOsystem
    ) -> None:
        """Slots set to ``0`` keep their sensor, as on the hardware"""

        mac_address = (await system.collect_sensor_nodes())[0].mac_address
        await system.connect_sensor_node_mac(mac_address.format())

        await system.set_sensor_configuration(SensorConfiguration(5, 0, 7))
        configuration = await system.get_sensor_configuration()

        assert (
            configuration.first,
            configuration.second,
            configuration.third,
        ) == (5, 2, 7)

    async def test_reset_stu(self, system: SimulatedICOsystem) -> None:
        """Resetting the STU works and disconnects the sensor device"""

        await system.reset_stu()

        assert get_simulated_hardware().connected is None

    async def test_unresponsive_stu(self, system: SimulatedICOsystem) -> None:
        """An STU that does not answer raises the real error"""

        get_simulated_hardware().stu_responsive = False

        with raises(NoResponseError):
            await system.get_stu_mac_address()
        with raises(NoResponseError):
            await system.collect_sensor_nodes()


class TestStreaming:
    """Test the simulated measurement data"""

    async def read(
        self, system: SimulatedICOsystem, channels: StreamingConfiguration
    ) -> tuple[list[Any], Any]:
        """Connect to the first sensor device and read some messages"""

        mac_address = (await system.collect_sensor_nodes())[0].mac_address
        await system.connect_sensor_node_mac(mac_address.format())
        messages: list[Any] = []
        async with system.sensor_node.open_data_stream(channels) as stream:
            async for data, lost in stream:
                messages.append((data, lost))
                if len(messages) == 60:
                    break
            dataloss = stream.dataloss()
        return messages, dataloss

    @mark.parametrize(
        ("channels", "values"),
        [
            (StreamingConfiguration(first=True), 3),
            (StreamingConfiguration(first=True, second=True), 2),
            (StreamingConfiguration(first=True, second=True, third=True), 3),
        ],
    )
    async def test_messages(
        self,
        system: SimulatedICOsystem,
        channels: StreamingConfiguration,
        values: int,
    ) -> None:
        """Messages have the shape the API expects"""

        messages, dataloss = await self.read(system, channels)

        assert dataloss == 0
        previous = None
        for data, lost in messages:
            assert lost == 0
            assert len(data.values) == values
            assert all(0 <= value <= 0xFFFF for value in data.values)
            if previous is not None:
                assert data.counter == (previous.counter + 1) % 256
                assert data.timestamp > previous.timestamp
            previous = data

        # The signal moves around the middle of the ADC range
        average = sum(sum(data.values) for data, _ in messages) / (
            values * len(messages)
        )
        assert 0.4 * 0xFFFF < average < 0.6 * 0xFFFF

    async def test_dataloss(
        self, system: SimulatedICOsystem, monkeypatch: MonkeyPatch
    ) -> None:
        """Lost messages show in the counter and in the statistics"""

        monkeypatch.setenv("ICOAPI_SIMULATE_DATALOSS", "0.5")

        messages, dataloss = await self.read(
            system, StreamingConfiguration(first=True)
        )

        assert dataloss > 0
        assert any(lost > 0 for _, lost in messages)


class TestAPI:
    """Test the API with the simulated hardware"""

    async def test_whole_flow(self, http: AsyncClient) -> None:
        """Search, connect, scan, connect to a sensor device, reset"""

        response = await http.get("can/networks")
        assert response.json()["networks"] == [
            {
                "interface": SIMULATED_INTERFACE,
                "channel": SIMULATED_CHANNEL,
                "bitrate": 1000000,
            }
        ]

        response = await http.put("can/connect")
        assert response.status_code == 200
        assert response.json()["status"] == "CONNECTED"

        response = await http.get("stu")
        assert response.json()[0]["mac_address"] == "02-1C-05-51-FF-01"

        response = await http.get("sth")
        devices = response.json()
        assert [device["name"] for device in devices] == [
            "Test-STH",
            "Sim-STH2",
        ]

        mac_address = devices[0]["mac_address"]
        response = await http.put("sth/connect", json={"mac_address": mac_address})
        assert response.status_code == 200
        response = await http.get("state")
        assert response.json()["sth_connected"] == {
            "name": "Test-STH",
            "mac_address": mac_address,
        }

        # Also works while connected (the API disconnects the sensor device)
        response = await http.put("stu/reset")
        assert response.status_code == 200
        response = await http.get("state")
        assert response.json()["sth_connected"] is None

        response = await http.put("can/disconnect")
        assert response.json()["status"] == "NETWORK_FOUND"

    async def test_unreachable_sth(self, http: AsyncClient) -> None:
        """Connecting to a device out of range is a 404"""

        await http.put("can/connect")
        device = get_simulated_hardware().devices[0]
        device.in_range = False

        response = await http.put(
            "sth/connect", json={"mac_address": device.mac_address.format()}
        )

        assert response.status_code == 404

    async def test_unresponsive_stu(self, http: AsyncClient) -> None:
        """A silent STU is a 502 and shows in the state"""

        await http.put("can/connect")
        get_simulated_hardware().stu_responsive = False

        response = await http.get("sth")

        assert response.status_code == 502
        response = await http.get("state")
        assert response.json()["stu_connected"] is False

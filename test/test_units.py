"""Tests for multi STU support: Several units and measurements with all of them

Every unit is a (simulated) CAN network with an STU and sensor devices. The
tests use two simulated networks.
"""

# -- Imports ------------------------------------------------------------------

import asyncio
from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from icoschema import DatasetBundle
from icotronic.can.streaming import StreamingTimeoutError
from pytest import MonkeyPatch, fixture, mark

from icoapi.models.event_bus import Channel
from icoapi.models.globals import (
    ICOsystemSingleton,
    MeasurementSingleton,
    get_system,
)
from icoapi.models.models import CANNetwork
from icoapi.scripts import group_measurement, measurement, simulation
from icoapi.scripts.data_handling import (
    get_active_sensor_configuration,
    get_file_data,
)
from icoapi.scripts.features import MULTI_STU_SUPPORT_VARIABLES
from icoapi.scripts.simulation import (
    SIMULATED_INTERFACE,
    get_simulated_hardware,
    reset_simulated_hardware,
)

# pylint: disable=redefined-outer-name,duplicate-code

# -- Globals ------------------------------------------------------------------

UNITS = ["simulated:SIM1", "simulated:SIM2"]
NETWORKS = [
    CANNetwork(interface=SIMULATED_INTERFACE, channel="SIM1", bitrate=1000000),
    CANNetwork(interface=SIMULATED_INTERFACE, channel="SIM2", bitrate=1000000),
]

# -- Fixtures -----------------------------------------------------------------


@fixture
def simulated_units(
    monkeypatch: MonkeyPatch, isolated_can_state: None
) -> Generator[None, None, None]:
    """Switch on multi STU support and simulate two networks"""

    del isolated_can_state
    monkeypatch.setenv(MULTI_STU_SUPPORT_VARIABLES[0], "1")
    monkeypatch.setenv("ICOAPI_SIMULATE", "only")
    monkeypatch.setenv("ICOAPI_SIMULATE_LATENCY", "0")
    monkeypatch.setenv("ICOAPI_SIMULATE_NETWORKS", "2")
    monkeypatch.delenv("ICOAPI_SIMULATE_DATALOSS", raising=False)
    reset_simulated_hardware()
    yield
    reset_simulated_hardware()


@fixture
async def connected(simulated_units: None) -> AsyncGenerator[None, None]:
    """Connect both networks"""

    del simulated_units
    await ICOsystemSingleton.scan()
    for network in NETWORKS:
        await ICOsystemSingleton.connect(network)
    yield
    await ICOsystemSingleton.disconnect()


@fixture
async def with_sensor_nodes(connected: None) -> None:
    """Connect the first sensor device of every unit"""

    del connected
    for unit in ICOsystemSingleton.units():
        hardware = get_simulated_hardware(unit.network.channel)
        await unit.system.connect_sensor_node_mac(
            hardware.devices[0].mac_address.format()
        )


@fixture
def files(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Directory of the measurement files"""

    from icoapi.routers import (  # pylint: disable=import-outside-toplevel
        measurement_routes,
    )

    monkeypatch.setattr(
        measurement_routes, "get_measurement_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        group_measurement, "get_measurement_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        measurement, "get_measurement_dir", lambda: str(tmp_path)
    )
    return tmp_path


class Client:  # pylint: disable=too-few-public-methods
    """WebSocket client that collects everything it gets"""

    client = "test"

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def send_json(self, data: Any) -> None:
        """Receive message"""

        self.messages.append(data)

    async def close(self) -> None:
        """Close connection"""


def instructions(**changes: Any) -> dict[str, Any]:
    """Get instructions for a measurement with one channel"""

    sensor = next(
        iter(get_active_sensor_configuration(None).channels.values())
    )
    return {
        "name": "Units",
        "mac_address": "00-00-00-00-00-00",
        "time": 1,
        "first": {"sensor_id": sensor.sensor_id},
        "second": {"sensor_id": None},
        "third": {"sensor_id": None},
        "ift_requested": False,
        "ift_channel": "",
        "ift_window_width": 50,
        "adc": {
            "prescaler": 2,
            "acquisition_time": 8,
            "oversampling_rate": 64,
            "reference_voltage": 3.3,
        },
        "meta": {"version": "1", "profile": "milling", "parameters": {}},
        **changes,
    }


async def wait_until_stopped(timeout: float = 20) -> None:
    """Wait until the measurement has ended"""

    state = MeasurementSingleton.get_instance()
    for _ in range(int(timeout * 20)):
        if not state.running and state.task is None:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("The measurement did not end")


def read_sources(path: Path) -> dict[str, Any]:
    """Read the sources of a measurement file"""

    recording: Any = DatasetBundle.from_hdf5(str(path)).recording
    return dict(recording.sources)


def measurement_files(directory: Path) -> list[Path]:
    """Get the measurement files of a directory"""

    return sorted(directory.glob("*.hdf5"))


# -- Tests --------------------------------------------------------------------


class TestUnits:
    """Test connecting to several CAN networks"""

    async def test_every_network_is_a_unit(self, connected: None) -> None:
        """Connecting a network does not disconnect the others"""

        del connected
        units = ICOsystemSingleton.units()

        assert [unit.key for unit in units] == UNITS
        assert units[0].system is not units[1].system
        # The first unit is the one that is used by default
        assert ICOsystemSingleton.selected == NETWORKS[0]
        assert await get_system() is units[0].system
        assert await get_system(UNITS[1]) is units[1].system

    async def test_without_the_feature_networks_are_replaced(
        self, simulated_units: None, monkeypatch: MonkeyPatch
    ) -> None:
        """Only one network is connected at a time without multi STU support"""

        del simulated_units
        for name in MULTI_STU_SUPPORT_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        await ICOsystemSingleton.scan()

        await ICOsystemSingleton.connect(NETWORKS[0])
        await ICOsystemSingleton.connect(NETWORKS[1])

        assert [unit.key for unit in ICOsystemSingleton.units()] == [UNITS[1]]
        await ICOsystemSingleton.disconnect()

    async def test_units_have_their_own_devices(
        self, with_sensor_nodes: None
    ) -> None:
        """Every unit has its own STU and its own sensor device"""

        del with_sensor_nodes
        first, second = ICOsystemSingleton.units()

        assert (
            (await first.system.get_stu_mac_address()).format()
            != (await second.system.get_stu_mac_address()).format()
        )
        assert (
            first.connected_sth().mac_address  # type: ignore[union-attr]
            != second.connected_sth().mac_address  # type: ignore[union-attr]
        )

    async def test_state(self, with_sensor_nodes: None, http: AsyncClient):
        """The state and the route list all units"""

        del with_sensor_nodes
        state = (await http.get("state")).json()
        units = (await http.get("can/units")).json()

        assert [unit["unit"] for unit in state["units"]] == UNITS
        assert state["units"] == units
        assert all(unit["stu_connected"] for unit in units)
        assert all(unit["sth_connected"] is not None for unit in units)
        # The old fields describe the first unit
        assert state["sth_connected"] == units[0]["sth_connected"]
        assert state["can_selected"]["channel"] == "SIM1"

    async def test_state_without_feature(
        self, simulated_units: None, monkeypatch: MonkeyPatch, http
    ) -> None:
        """Without multi STU support the state has no units"""

        del simulated_units
        for name in MULTI_STU_SUPPORT_VARIABLES:
            monkeypatch.delenv(name, raising=False)

        assert (await http.get("state")).json()["units"] is None

    async def test_requests_for_a_unit(
        self, with_sensor_nodes: None, http: AsyncClient
    ) -> None:
        """The parameter ``unit`` selects the unit"""

        del with_sensor_nodes
        names = []
        for unit in UNITS:
            response = await http.get("stu", params={"unit": unit})
            assert response.status_code == 200
            names.append(response.json()[0]["mac_address"])
            connected = await http.get("stu/connected", params={"unit": unit})
            assert connected.json() is True

        assert names[0] != names[1]
        assert (
            await http.get("stu", params={"unit": "pcan:PCAN_USBBUS9"})
        ).status_code == 404

    async def test_disconnect_a_unit(
        self, connected: None, http: AsyncClient
    ) -> None:
        """Disconnecting a unit leaves the other ones alone"""

        del connected
        response = await http.put("can/disconnect", params={"unit": UNITS[0]})

        assert response.status_code == 200
        # The remaining unit is the first one now
        assert [unit.key for unit in ICOsystemSingleton.units()] == [UNITS[1]]
        assert ICOsystemSingleton.selected == NETWORKS[1]
        assert (
            await http.put("can/disconnect", params={"unit": UNITS[0]})
        ).status_code == 404

        await http.put("can/disconnect")
        assert not ICOsystemSingleton.units()

    async def test_failing_unit_keeps_the_others(
        self, connected: None
    ) -> None:
        """A network without answering STU does not disturb working units"""

        del connected
        await ICOsystemSingleton.disconnect(UNITS[1])
        get_simulated_hardware("SIM2").stu_responsive = False

        try:
            await ICOsystemSingleton.connect(NETWORKS[1])
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        else:
            raise AssertionError("Connecting should have failed")

        assert [unit.key for unit in ICOsystemSingleton.units()] == [UNITS[0]]
        assert ICOsystemSingleton.status.name == "CONNECTED"

    async def test_reset_reconnects_all_units(self, connected: None) -> None:
        """Resetting reconnects every unit"""

        del connected
        await ICOsystemSingleton.reset()

        assert [unit.key for unit in ICOsystemSingleton.units()] == UNITS


class TestPreflight:
    """Test the check that all units are ready"""

    async def test_ready(
        self, with_sensor_nodes: None, http: AsyncClient
    ) -> None:
        """Units with sensor device are ready"""

        del with_sensor_nodes
        response = await http.get("measurement/preflight")

        assert response.status_code == 200
        result = response.json()
        assert result["ready"] is True
        assert [unit["unit"] for unit in result["units"]] == UNITS
        for unit in result["units"]:
            assert unit["problems"] == []
            assert unit["tool_name"].startswith("Test-STH")
            assert unit["rssi"] < 0
            assert unit["supply_voltage"] > 0
            assert unit["sample_rate"] > 0

    async def test_every_problem_is_reported(
        self, connected: None, http: AsyncClient
    ) -> None:
        """Units without sensor device are not ready"""

        del connected
        unit = ICOsystemSingleton.units()[0]
        await unit.system.connect_sensor_node_mac(
            get_simulated_hardware("SIM1").devices[0].mac_address.format()
        )

        result = (await http.get("measurement/preflight")).json()

        assert result["ready"] is False
        assert [u["problems"] for u in result["units"]][0] == []
        assert "No sensor device" in result["units"][1]["problems"][0]

    async def test_weak_connection(
        self,
        with_sensor_nodes: None,
        http: AsyncClient,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """A weak connection to a sensor device is a problem"""

        del with_sensor_nodes
        get_simulated_hardware("SIM2").devices[0].rssi = -95

        result = (await http.get("measurement/preflight")).json()

        assert [unit["ok"] for unit in result["units"]] == [True, False]
        assert "RSSI -95" in result["units"][1]["problems"][0]
        monkeypatch.setenv("ICOAPI_MIN_RSSI", "-100")
        assert (await http.get("measurement/preflight")).json()["ready"]

    async def test_unresponsive_stu(
        self, with_sensor_nodes: None, http: AsyncClient
    ) -> None:
        """An STU that does not answer is a problem"""

        del with_sensor_nodes
        get_simulated_hardware("SIM1").stu_responsive = False

        result = (await http.get("measurement/preflight")).json()

        assert [unit["ok"] for unit in result["units"]] == [False, True]
        assert "response" in result["units"][0]["problems"][0]


class TestMeasurement:
    """Test measurements with all units"""

    async def test_measurement(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """All units measure and the file has a source for every unit"""

        del with_sensor_nodes
        client = Client()
        MeasurementSingleton.get_instance().clients.append(client)

        response = await http.post("measurement/start", json=instructions())
        assert response.status_code == 200, response.text
        await wait_until_stopped()

        (path,) = measurement_files(files)
        recording: Any = DatasetBundle.from_hdf5(str(path)).recording
        sources = list(recording.sources.values())

        assert [source.name for source in sources] == [
            "Test-STH",
            "Test-STH-2",
        ]
        assert len({source.stu_mac for source in sources}) == 2
        assert len({source.sth_mac for source in sources}) == 2
        for source in sources:
            assert len(source.timestamps) > 1000
            assert source.timestamps[0] == 0
            assert (source.timestamps[1:] >= source.timestamps[:-1]).all()
            assert source.timestamps[-1] >= 900_000  # about one second
            assert source.recording_metadata.start_time is not None
            assert source.signal_loss_percentage == 0
            assert source.recording_metadata.pre_metadata is not None

        # Every source has its own clock: The start times place them
        offsets = recording.start_offsets()
        assert min(offsets.values()) == 0
        assert max(offsets.values()) < 1.0

        # Both streams were sent to the client
        sent = {
            item["source"]
            for message in client.messages
            if isinstance(message, list)
            for item in message
        }
        assert sent == {"Test-STH", "Test-STH-2"}

    async def test_data_of_every_source(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """The data of every source can be shown"""

        del with_sensor_nodes
        await http.post("measurement/start", json=instructions())
        await wait_until_stopped()
        (path,) = measurement_files(files)

        first = get_file_data(str(path), "Test-STH")
        second = get_file_data(str(path), "Test-STH-2")

        assert [info.name for info in first.sources] == [
            "Test-STH",
            "Test-STH-2",
        ]
        assert len(first.acceleration_df) > 1000
        assert (
            first.acceleration_meta.attributes["sth_mac_address"]
            != second.acceleration_meta.attributes["sth_mac_address"]
        )

    async def test_stop(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """Stopping a measurement stops all units"""

        del with_sensor_nodes
        response = await http.post(
            "measurement/start", json=instructions(time=None)
        )
        assert response.status_code == 200
        await asyncio.sleep(0.5)

        assert (await http.post("measurement/stop")).status_code == 200
        await wait_until_stopped()

        (path,) = measurement_files(files)
        sources = read_sources(path)
        assert len(sources) == 2

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    async def test_one_failing_unit_stops_all(
        self,
        with_sensor_nodes: None,
        http: AsyncClient,
        files: Path,
        recording_event_bus,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """If one unit fails, the whole measurement fails (and is kept)"""

        del with_sensor_nodes
        original = simulation.SimulatedStream.__anext__

        async def fail_after_a_while(self):
            if self._device.name.endswith("-2") and self._index > 200:
                raise StreamingTimeoutError("No data for 5 seconds")
            return await original(self)

        monkeypatch.setattr(
            simulation.SimulatedStream, "__anext__", fail_after_a_while
        )
        client = Client()
        MeasurementSingleton.get_instance().clients.append(client)

        await http.post("measurement/start", json=instructions(time=None))
        await wait_until_stopped()

        assert [channel for channel, _ in recording_event_bus.events] == [
            Channel.RECORDING_FAILED
        ]
        payload = recording_event_bus.events[0][1]
        assert payload["error"]["type"] == "StreamingTimeoutError"
        assert payload["size"] > 0
        assert any(
            isinstance(message, dict) and message.get("error")
            for message in client.messages
        )

        # What was recorded is in the file, and the file is closed
        (path,) = measurement_files(files)
        sources = read_sources(path)
        assert len(sources["Test-STH-2"].timestamps) < len(
            sources["Test-STH"].timestamps
        ) or len(sources["Test-STH"].timestamps) < 1000
        assert not MeasurementSingleton.get_instance().running

    async def test_not_started_if_one_unit_is_not_ready(
        self, connected: None, http: AsyncClient, files: Path
    ) -> None:
        """Nothing starts, if a unit has no sensor device"""

        del connected
        await ICOsystemSingleton.units()[0].system.connect_sensor_node_mac(
            get_simulated_hardware("SIM1").devices[0].mac_address.format()
        )

        response = await http.post("measurement/start", json=instructions())

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "simulated:SIM2" in detail["message"]
        assert detail["ready"] is False
        assert detail["units"][1]["problems"]
        assert measurement_files(files) == []
        assert not MeasurementSingleton.get_instance().running
        # The unit that was ready is not left with a started measurement
        assert MeasurementSingleton.get_instance().task is None

    async def test_ift_needs_a_single_unit(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """IFT values can not be calculated for several units"""

        del with_sensor_nodes
        response = await http.post(
            "measurement/start",
            json=instructions(ift_requested=True, ift_channel="first"),
        )

        assert response.status_code == 422
        assert measurement_files(files) == []

    async def test_bus_load(
        self,
        with_sensor_nodes: None,
        http: AsyncClient,
        files: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """The CAN bus of a unit has to be able to transport the data"""

        del with_sensor_nodes
        monkeypatch.setenv("ICOAPI_MAX_MESSAGES_PER_SECOND", "1000")

        response = await http.post("measurement/start", json=instructions())

        assert response.status_code == 502
        problems = response.json()["detail"]["units"][0]["problems"]
        assert "messages per second" in problems[0]
        assert measurement_files(files) == []

    async def test_second_measurement_is_refused(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """A measurement can only start, if none is running"""

        del with_sensor_nodes, files
        await http.post("measurement/start", json=instructions(time=None))

        response = await http.post("measurement/start", json=instructions())

        assert response.status_code == 400
        await http.post("measurement/stop")
        await wait_until_stopped()

    async def test_single_unit_is_unchanged(
        self, with_sensor_nodes: None, http: AsyncClient, files: Path
    ) -> None:
        """A measurement of one unit is stored like before"""

        del with_sensor_nodes
        await ICOsystemSingleton.disconnect(UNITS[1])

        response = await http.post("measurement/start", json=instructions())
        assert response.status_code == 200, response.text
        await wait_until_stopped()

        (path,) = measurement_files(files)
        sources = read_sources(path)
        assert list(sources) == ["Test-STH"]


class TestExecute:
    """Test connecting and measuring in one step"""

    @staticmethod
    def addresses() -> dict[str, str]:
        """Get the MAC addresses of the first sensor device of every unit"""

        return {
            unit: get_simulated_hardware(unit.split(":")[1])
            .devices[0]
            .mac_address.format()
            for unit in UNITS
        }

    async def test_execute(
        self, connected: None, http: AsyncClient, files: Path
    ) -> None:
        """Every unit connects its sensor device, then all measure"""

        del connected
        response = await http.post(
            "measurement/execute",
            json=instructions(unit_mac_addresses=self.addresses()),
        )

        assert response.status_code == 200, response.text
        await wait_until_stopped()
        (path,) = measurement_files(files)
        assert (
            len(read_sources(path)) == 2
        )

    async def test_every_unit_needs_an_address(
        self, connected: None, http: AsyncClient
    ) -> None:
        """The address of every unit is required"""

        del connected
        addresses = self.addresses()
        del addresses[UNITS[1]]

        response = await http.post(
            "measurement/execute",
            json=instructions(unit_mac_addresses=addresses),
        )

        assert response.status_code == 422
        assert UNITS[1] in response.json()["detail"]

    async def test_all_or_nothing(
        self, connected: None, http: AsyncClient, files: Path
    ) -> None:
        """If one unit can not connect, no unit stays connected"""

        del connected
        addresses = self.addresses()
        addresses[UNITS[1]] = "00-11-22-33-44-55"

        response = await http.post(
            "measurement/execute",
            json=instructions(unit_mac_addresses=addresses),
        )

        assert response.status_code >= 400
        assert UNITS[1] in json.dumps(response.json())
        for unit in ICOsystemSingleton.units():
            assert unit.system.sensor_node_attributes is None
        assert measurement_files(files) == []

    async def test_execute_disconnects_after_failed_check(
        self,
        connected: None,
        http: AsyncClient,
        files: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """A failed check leaves no half configured unit connected"""

        del connected, files
        monkeypatch.setenv("ICOAPI_MIN_RSSI", "-30")

        response = await http.post(
            "measurement/execute",
            json=instructions(unit_mac_addresses=self.addresses()),
        )

        assert response.status_code == 502
        for unit in ICOsystemSingleton.units():
            assert unit.system.sensor_node_attributes is None


@mark.parametrize("flag", [False])
async def test_without_the_feature_all_units_are_not_used(
    flag: bool,
    simulated_units: None,
    monkeypatch: MonkeyPatch,
    http: AsyncClient,
    files: Path,
) -> None:
    """Without multi STU support a measurement uses the connected network"""

    del simulated_units, flag
    for name in MULTI_STU_SUPPORT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    await ICOsystemSingleton.scan()
    await ICOsystemSingleton.connect(NETWORKS[0])
    unit = ICOsystemSingleton.units()[0]
    await unit.system.connect_sensor_node_mac(
        get_simulated_hardware("SIM1").devices[0].mac_address.format()
    )

    response = await http.post("measurement/start", json=instructions())
    assert response.status_code == 200, response.text
    await wait_until_stopped()

    assert len(measurement_files(files)) == 1
    await ICOsystemSingleton.disconnect()

"""Simulated ICOtronic hardware (STU and sensor devices)

Makes it possible to run and test the whole software without CAN adapter, STU
or STH. Set ``ICOAPI_SIMULATE`` to enable it:

- ``ICOAPI_SIMULATE=1`` adds the CAN network ``simulated:SIM1`` to the
  networks that are found. Connecting to it works like connecting to a real
  network.
- ``ICOAPI_SIMULATE=only`` offers only the simulated network (no search for
  real adapters). Useful for tests.

The simulation sits just below ``ICOsystem``: :class:`SimulatedICOsystem` is an
``ICOsystem`` that opens a :class:`SimulatedSTU` instead of a CAN connection.
Everything above it (state handling, renaming, ADC and sensor configuration,
errors, the API itself, measurement files, events) is the real code. What is
simulated, and how closely:

=========================  ==================================================
Real hardware              Simulation
=========================  ==================================================
STU MAC address, reset     fixed MAC; reset takes a moment and disconnects
                           the sensor device
Scan for sensor devices    fixed list of devices (name, MAC, RSSI); renaming
                           is kept while the API runs
Connect to sensor device   works for devices in range, otherwise
                           ``TimeoutError`` (as in the real code)
Name, supply voltage, ADC  per device, writable where the hardware allows it
and sensor configuration
Streaming                  sine waves (a different frequency per slot) plus
                           noise as raw 16 bit ADC values, paced in real
                           time; message rate and values per message follow
                           the ADC and channel configuration
Data loss                  none by default, ``ICOAPI_SIMULATE_DATALOSS``
                           (probability per message) adds some
Devices                    ``Test-STH`` (``14-2D-41-D7-77-7D``, the MAC of the
                           development board the platform's examples use)
                           and ``Sim-STH2``; ``ICOAPI_SIMULATE_DEVICES``
                           (``Name=MAC,Name=MAC``) replaces them
Latency                    ``ICOAPI_SIMULATE_LATENCY`` seconds (default 0.2)
                           for scanning, connecting and resetting
=========================  ==================================================

The simulated hardware is a module level object (:func:`get_simulated_hardware`)
so that renamed devices survive a reconnect, and so that tests can break
things on purpose (``stu_responsive``, ``in_range``).
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from os import getenv
from time import monotonic, time
from types import TracebackType
from typing import Any

from icostate import ICOsystem, SensorNodeInfo
from icostate.state import State
from icotronic.can.adc import ADCConfiguration
from icotronic.can.dataloss import MessageStats
from icotronic.can.error import NoResponseError
from icotronic.can.node.sensor import SensorNode
from icotronic.can.node.stu import AsyncSensorNodeManager, STU
from icotronic.can.sensor import SensorConfiguration
from icotronic.can.status import State as NodeState
from icotronic.can.streaming import StreamingConfiguration, StreamingData
from netaddr import EUI

logger = logging.getLogger(__name__)

# -- Settings -----------------------------------------------------------------

SIMULATED_INTERFACE = "simulated"
"""Interface name of the simulated CAN network"""

SIMULATED_CHANNEL = "SIM1"
"""Channel name of the simulated CAN network"""

ENABLED = "on"
ONLY = "only"

# Frequencies (Hz) of the simulated signal in the first, second, third slot
SIGNAL_FREQUENCIES = (50.0, 120.0, 310.0)
# Amplitude (V) of the simulated signal and of the noise on top of it
SIGNAL_AMPLITUDE = 0.2
NOISE_AMPLITUDE = 0.005


def simulation_mode() -> str:
    """Get the simulation mode set by ``ICOAPI_SIMULATE``

    Returns:

        ``""`` (off), ``"on"`` (simulated network added to the real ones) or
        ``"only"`` (only the simulated network)
    """

    value = getenv("ICOAPI_SIMULATE", "").strip().lower()
    if value == ONLY:
        return ONLY
    if value in {"1", "true", "yes", "on"}:
        return ENABLED
    return ""


def _latency() -> float:
    """Get the simulated duration of scanning, connecting and resetting"""

    try:
        return max(0.0, float(getenv("ICOAPI_SIMULATE_LATENCY", "0.2")))
    except ValueError:
        return 0.2


def _configured_devices() -> list[SimulatedSTH]:
    """Get the simulated devices (``ICOAPI_SIMULATE_DEVICES`` or defaults)"""

    devices: list[SimulatedSTH] = []
    for number, entry in enumerate(
        getenv("ICOAPI_SIMULATE_DEVICES", "").split(",")
    ):
        name, _, mac_address = entry.partition("=")
        if not entry.strip():
            continue
        try:
            devices.append(
                SimulatedSTH(
                    name.strip(),
                    EUI(mac_address.strip()),
                    rssi=-40 - 6 * number,
                    supply_voltage=4.1 - 0.05 * number,
                )
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Ignoring invalid simulated device <%s> (expected Name=MAC)",
                entry,
            )
    return devices or [
        SimulatedSTH(
            "Test-STH",
            EUI("14-2D-41-D7-77-7D"),
            rssi=-42,
            supply_voltage=4.12,
        ),
        SimulatedSTH(
            "Sim-STH2",
            EUI("02-1C-05-51-00-02"),
            rssi=-58,
            supply_voltage=3.96,
        ),
    ]


def _dataloss() -> float:
    """Get the simulated probability that a streaming message is lost"""

    try:
        return min(1.0, max(0.0, float(getenv("ICOAPI_SIMULATE_DATALOSS", "0"))))
    except ValueError:
        return 0.0


# -- Simulated devices --------------------------------------------------------


@dataclass
class SimulatedSTH:
    """A simulated sensor device"""

    name: str
    mac_address: EUI
    rssi: int = -45
    supply_voltage: float = 4.1
    in_range: bool = True
    """Devices that are not in range are not found and cannot be connected"""
    adc: ADCConfiguration = field(
        default_factory=lambda: ADCConfiguration(
            reference_voltage=3.3,
            prescaler=2,
            acquisition_time=8,
            oversampling_rate=64,
        )
    )
    sensors: list[int] = field(default_factory=lambda: [1, 2, 3])
    """Channel number in the first, second and third slot"""


class SimulatedHardware:  # pylint: disable=too-few-public-methods
    """The simulated hardware: one STU and some sensor devices"""

    def __init__(self) -> None:
        self.stu_mac_address = EUI("02-1C-05-51-FF-01")
        self.stu_responsive = True
        """If ``False`` the STU does not answer (``NoResponseError``)"""
        self.devices: list[SimulatedSTH] = _configured_devices()
        self.connected: SimulatedSTH | None = None
        """The sensor device the STU is connected to"""

    def find(self, identifier: int | str | EUI) -> SimulatedSTH | None:
        """Find a sensor device that is in range by number, name or MAC"""

        in_range = [device for device in self.devices if device.in_range]
        if isinstance(identifier, int):
            return (
                in_range[identifier] if 0 <= identifier < len(in_range) else None
            )
        for device in in_range:
            if identifier in (device.name, device.mac_address):
                return device
            if isinstance(identifier, str):
                try:
                    if EUI(identifier) == device.mac_address:
                        return device
                except Exception:  # pylint: disable=broad-exception-caught
                    continue
        return None


@lru_cache(maxsize=1)
def get_simulated_hardware() -> SimulatedHardware:
    """Get the simulated hardware (created on first use)"""

    return SimulatedHardware()


def reset_simulated_hardware() -> None:
    """Forget all changes made to the simulated hardware"""

    get_simulated_hardware.cache_clear()


# -- Streaming ----------------------------------------------------------------


class SimulatedStream:  # pylint: disable=too-many-instance-attributes
    """Replacement for the buffer that streaming data is read from

    Yields ``(StreamingData, lost_messages)`` in real time.
    """

    def __init__(
        self,
        device: SimulatedSTH,
        channels: StreamingConfiguration,
        dataloss: float,
    ) -> None:
        self._device = device
        self._channels = channels
        self._dataloss = dataloss
        self._stats = MessageStats()
        self._closed = False

        self._slots = [
            slot
            for slot, enabled in enumerate(
                (channels.first, channels.second, channels.third)
            )
            if enabled
        ]
        sample_rate = device.adc.sample_rate()
        # One enabled channel: every message carries three samples of it.
        # Otherwise every message carries one sample per enabled channel.
        self._samples_per_message = 3 if len(self._slots) == 1 else 1
        self._interval = self._samples_per_message * len(self._slots) / sample_rate

        self._index = 0
        self._counter = 0
        self._started = monotonic()
        self._start_time = time()

    def __aiter__(self) -> SimulatedStream:
        return self

    def _volts(self, slot: int, at: float) -> float:
        """Get the simulated sensor voltage of a slot at a time"""

        signal = math.sin(2 * math.pi * SIGNAL_FREQUENCIES[slot] * at)
        noise = random.gauss(0, NOISE_AMPLITUDE)
        return (
            self._device.adc.reference_voltage / 2
            + SIGNAL_AMPLITUDE * signal
            + noise
        )

    def _raw(self, volts: float) -> int:
        """Convert a voltage to a raw 16 bit ADC value"""

        raw = round(volts / self._device.adc.reference_voltage * 0xFFFF)
        return min(0xFFFF, max(0, raw))

    async def __anext__(self) -> tuple[StreamingData, int]:
        if self._closed:
            raise StopAsyncIteration

        # Messages that are lost still take their time
        missed = 0
        while missed < 5 and random.random() < self._dataloss:
            missed += 1
        self._index += missed
        index = self._index
        self._index += 1

        delay = self._started + index * self._interval - monotonic()
        # Always give other tasks (WebSocket, API) a chance to run
        await asyncio.sleep(max(delay, 0))
        if self._closed:
            raise StopAsyncIteration

        at = index * self._interval
        if self._samples_per_message == 3:
            slot = self._slots[0]
            step = self._interval / 3
            values = [
                self._raw(self._volts(slot, at + number * step))
                for number in range(3)
            ]
        else:
            values = [self._raw(self._volts(slot, at)) for slot in self._slots]
        # Three channels is the only case with as many values as channels, for
        # two the hardware sends two values, so nothing is missing here
        assert len(values) == self._channels.data_length()

        self._counter = (self._counter + 1 + missed) % 256
        self._stats.retrieved += 1
        self._stats.lost += missed
        return (
            StreamingData(self._counter, self._start_time + at, values),
            missed,
        )

    def stop(self) -> None:
        """Stop the stream"""

        self._closed = True

    def reset_stats(self) -> None:
        """Reset the message statistics"""

        self._stats.reset()

    def dataloss(self) -> float:
        """Get the share of lost messages since the last reset"""

        return self._stats.dataloss()


class SimulatedStreamContext:  # pylint: disable=too-few-public-methods
    """Replacement for the context manager that opens a data stream"""

    def __init__(
        self, device: SimulatedSTH, channels: StreamingConfiguration
    ) -> None:
        self._stream = SimulatedStream(device, channels, _dataloss())

    async def __aenter__(self) -> SimulatedStream:
        return self._stream

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stream.stop()


# -- Nodes --------------------------------------------------------------------


class SimulatedSensorNode(SensorNode):  # type: ignore[misc]
    """A connected simulated sensor device (replacement for ``SensorNode``)"""

    # pylint: disable=super-init-not-called,too-many-public-methods

    def __init__(self, hardware: SimulatedHardware, device: SimulatedSTH):
        self._hardware = hardware
        self._device = device

    def _check(self) -> None:
        if not self._hardware.stu_responsive:
            raise NoResponseError("Simulated STU does not respond")

    async def get_name(self) -> str:
        self._check()
        return self._device.name

    async def set_name(self, name: str) -> None:
        self._check()
        self._device.name = name

    async def get_rssi(self) -> int:
        self._check()
        return self._device.rssi

    async def get_mac_address(self) -> EUI:
        self._check()
        return self._device.mac_address

    async def get_supply_voltage(self) -> float:
        self._check()
        return self._device.supply_voltage + random.gauss(0, 0.005)

    async def get_adc_configuration(self) -> ADCConfiguration:
        self._check()
        adc = self._device.adc
        return ADCConfiguration(
            reference_voltage=adc.reference_voltage,
            prescaler=adc.prescaler,
            acquisition_time=adc.acquisition_time,
            oversampling_rate=adc.oversampling_rate,
        )

    async def set_adc_configuration(  # type: ignore[override]
        self,
        reference_voltage: float = 3.3,
        prescaler: int = 2,
        acquisition_time: int = 8,
        oversampling_rate: int = 64,
    ) -> None:
        self._check()
        self._device.adc = ADCConfiguration(
            reference_voltage=reference_voltage,
            prescaler=prescaler,
            acquisition_time=acquisition_time,
            oversampling_rate=oversampling_rate,
        )

    async def get_sensor_configuration(self) -> SensorConfiguration:
        self._check()
        first, second, third = self._device.sensors
        return SensorConfiguration(first, second, third)

    async def set_sensor_configuration(
        self, sensors: SensorConfiguration
    ) -> None:
        self._check()
        # As on the hardware, `0` leaves the sensor of that slot unchanged
        for slot, channel in enumerate(
            (sensors.first, sensors.second, sensors.third)
        ):
            if channel != 0:
                self._device.sensors[slot] = channel

    def open_data_stream(  # type: ignore[override]
        self, channels: StreamingConfiguration, timeout: float = 5
    ) -> SimulatedStreamContext:
        del timeout
        return SimulatedStreamContext(self._device, channels)


class SimulatedNodeManager(AsyncSensorNodeManager):  # type: ignore[misc]
    """Connects to a simulated sensor device (as ``AsyncSensorNodeManager``)"""

    # pylint: disable=super-init-not-called

    def __init__(
        self, hardware: SimulatedHardware, identifier: int | str | EUI
    ) -> None:
        self._hardware = hardware
        self._identifier = identifier

    async def __aenter__(self) -> SensorNode:
        hardware = self._hardware
        if not hardware.stu_responsive:
            raise NoResponseError("Simulated STU does not respond")
        await asyncio.sleep(_latency())
        device = hardware.find(self._identifier)
        if device is None:
            raise TimeoutError(
                f"Sensor device {self._identifier} not found (simulated)"
            )
        hardware.connected = device
        logger.debug("Connected to simulated sensor device <%s>", device.name)
        return SimulatedSensorNode(hardware, device)

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._hardware.connected = None


class SimulatedSTU(STU):  # type: ignore[misc]
    """A simulated STU (replacement for ``STU``)"""

    # pylint: disable=super-init-not-called

    def __init__(self, hardware: SimulatedHardware) -> None:
        self._hardware = hardware

    def _check(self) -> None:
        if not self._hardware.stu_responsive:
            raise NoResponseError("Simulated STU does not respond")

    async def get_mac_address(  # type: ignore[override]
        self, sensor_node_number: int = 0
    ) -> EUI:
        self._check()
        if sensor_node_number == 0:
            return self._hardware.stu_mac_address
        device = self._hardware.find(sensor_node_number - 1)
        if device is None:
            raise NoResponseError(
                f"No sensor device with number {sensor_node_number}"
            )
        return device.mac_address

    async def reset(self) -> None:
        self._check()
        await asyncio.sleep(_latency())
        self._hardware.connected = None

    def release(self) -> None:
        """Release the sensor device when the connection to the STU closes"""

        self._hardware.connected = None

    async def get_state(self) -> NodeState:
        self._check()
        return NodeState(location="Application", state="Operating")

    async def activate_bluetooth(self) -> None:
        self._check()

    async def deactivate_bluetooth(self) -> None:
        self._check()
        self._hardware.connected = None

    async def is_connected(self) -> bool:
        self._check()
        return self._hardware.connected is not None

    async def collect_sensor_nodes(  # type: ignore[override]
        self, timeout: float = 5
    ) -> list[SensorNodeInfo]:
        del timeout
        self._check()
        await asyncio.sleep(_latency())
        return [
            SensorNodeInfo(
                name=device.name,
                sensor_node_number=number,
                mac_address=device.mac_address,
                rssi=device.rssi,
            )
            for number, device in enumerate(
                device for device in self._hardware.devices if device.in_range
            )
        ]

    def connect_sensor_node(  # type: ignore[override]
        self, identifier: int | str | EUI, *_: Any, **__: Any
    ) -> SimulatedNodeManager:
        return SimulatedNodeManager(self._hardware, identifier)


# -- System -------------------------------------------------------------------


class SimulatedICOsystem(ICOsystem):  # type: ignore[misc]
    """``ICOsystem`` that uses the simulated hardware instead of CAN

    Only the connection to the STU differs, all the other methods are those of
    ``ICOsystem``.
    """

    stu: STU | None

    async def connect_stu(self) -> None:
        self.check_in_state({State.DISCONNECTED}, "Connecting to STU")
        self.stu = SimulatedSTU(get_simulated_hardware())
        self.state = State.STU_CONNECTED
        logger.info("Connected to simulated STU")

    async def disconnect_stu(self) -> None:
        self.check_in_state({State.STU_CONNECTED}, "Disconnecting from STU")
        if isinstance(self.stu, SimulatedSTU):
            self.stu.release()
        self.stu = None
        self.state = State.DISCONNECTED

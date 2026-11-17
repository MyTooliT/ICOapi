"""Tests for instructions that differ between units"""

# -- Imports ------------------------------------------------------------------

from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from pytest import mark, raises

from icoapi.models.models import (
    ADCValues,
    MeasurementInstructionChannel,
    MeasurementInstructions,
    UnitInstructions,
)
from icoapi.scripts.unit_instructions import (
    check_unit_names,
    instructions_for_unit,
    mac_address_of_unit,
)

# -- Globals ------------------------------------------------------------------

FIRST = "simulated:SIM1"
SECOND = "simulated:SIM2"


def channel(sensor_id: str | None) -> MeasurementInstructionChannel:
    """Create channel instructions"""

    return MeasurementInstructionChannel(sensor_id=sensor_id)


def adc(oversampling: int) -> ADCValues:
    """Create ADC values"""

    return ADCValues(
        prescaler=2,
        acquisition_time=8,
        oversampling_rate=oversampling,
        reference_voltage=3.3,
    )


def instructions(**changes: Any) -> MeasurementInstructions:
    """Create instructions with three channels"""

    values: dict[str, Any] = {
        "name": "Test",
        "mac_address": "00-00-00-00-00-00",
        "time": 3,
        "first": channel("a"),
        "second": channel("b"),
        "third": channel("c"),
        "ift_requested": False,
        "ift_channel": "",
        "ift_window_width": 50,
        "adc": adc(64),
    }
    values.update(changes)
    return MeasurementInstructions(**values)


def units(*names: str) -> list[Any]:
    """Create fake units"""

    return [SimpleNamespace(key=name) for name in names]


# -- Tests --------------------------------------------------------------------


class TestInstructionsForUnit:
    """Test combining the instructions of a measurement with a unit's own"""

    def test_nothing_set(self) -> None:
        """Units without own instructions use the ones of the measurement"""

        base = instructions(
            units={SECOND: UnitInstructions(first=channel("x"))},
            unit_mac_addresses={FIRST: "11"},
        )

        own = instructions_for_unit(base, FIRST)

        assert (own.first, own.second, own.third) == (
            base.first,
            base.second,
            base.third,
        )
        assert own.adc == base.adc
        assert own.units is None
        assert own.unit_mac_addresses is None
        # The instructions of the measurement are not changed
        assert base.units is not None and base.unit_mac_addresses is not None

    def test_only_what_is_set_is_replaced(self) -> None:
        """Channels that are not set keep the value of the measurement"""

        base = instructions(
            units={SECOND: UnitInstructions(first=channel("x"), adc=adc(32))}
        )

        own = instructions_for_unit(base, SECOND)

        assert own.first.sensor_id == "x"
        assert own.second.sensor_id == "b"
        assert own.third.sensor_id == "c"
        assert own.adc == adc(32)
        assert own.name == "Test" and own.time == 3

    def test_disable_channel(self) -> None:
        """A channel is disabled by setting it to no sensor"""

        base = instructions(
            units={SECOND: UnitInstructions(third=channel(None))}
        )

        own = instructions_for_unit(base, SECOND)

        assert own.third.sensor_id is None
        assert own.first.sensor_id == "a"

    def test_sensor_configuration_and_mac_address(self) -> None:
        """The sensor configuration and the MAC address can be replaced"""

        configuration: Any = SimpleNamespace(name="inline")
        base = instructions(
            units={
                SECOND: UnitInstructions(
                    sensor_configuration=configuration, mac_address="22"
                )
            }
        )

        own = instructions_for_unit(base, SECOND)

        assert own.sensor_configuration is configuration
        assert own.mac_address == "22"
        assert instructions_for_unit(base, FIRST).sensor_configuration is None

    def test_everything_else_is_shared(self) -> None:
        """Name, time and metadata can not differ"""

        base = instructions(
            units={SECOND: UnitInstructions(first=channel("x"))},
            disconnect_after_measurement=True,
        )

        own = instructions_for_unit(base, SECOND)

        assert own.disconnect_after_measurement is True
        assert (own.name, own.time, own.meta) == ("Test", 3, None)


class TestMacAddress:
    """Test the MAC address of the sensor device of a unit"""

    def test_precedence(self) -> None:
        """The address of the unit's instructions wins"""

        base = instructions(
            units={SECOND: UnitInstructions(mac_address="own")},
            unit_mac_addresses={FIRST: "listed", SECOND: "listed"},
        )

        assert mac_address_of_unit(base, FIRST) == "listed"
        assert mac_address_of_unit(base, SECOND) == "own"

    def test_none(self) -> None:
        """Without address there is none"""

        assert mac_address_of_unit(instructions(), FIRST) is None


class TestUnitNames:
    """Test that instructions are only given to existing units"""

    def test_known(self) -> None:
        """Instructions for existing units are fine"""

        check_unit_names(
            instructions(
                units={FIRST: UnitInstructions()},
                unit_mac_addresses={SECOND: "1"},
            ),
            units(FIRST, SECOND),
        )

    @mark.parametrize(
        "changes",
        [
            {"units": {"pcan:PCAN_USBBUS9": UnitInstructions()}},
            {"unit_mac_addresses": {"pcan:PCAN_USBBUS9": "1"}},
        ],
    )
    def test_unknown(self, changes: dict[str, Any]) -> None:
        """Instructions for units that do not exist are refused"""

        with raises(HTTPException) as error:
            check_unit_names(instructions(**changes), units(FIRST, SECOND))

        assert error.value.status_code == 422
        assert "pcan:PCAN_USBBUS9" in error.value.detail
        assert FIRST in error.value.detail

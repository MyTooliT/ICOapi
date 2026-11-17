"""Instructions of a measurement with several units

A measurement has one set of instructions. With multi STU support some of
them can differ between the units (see
:class:`icoapi.models.models.UnitInstructions`): the channels and sensors, the
ADC settings, the inline sensor configuration and the sensor device. This
module combines the instructions of the measurement with what is set for a
unit.

Everything else (name, time, metadata, …) is the same for all units.
"""

# -- Imports ------------------------------------------------------------------

from dataclasses import dataclass, replace

from fastapi import HTTPException
from starlette import status

from icoapi.models.globals import Unit
from icoapi.models.models import (
    MeasurementInstructions,
    ResolvedMeasurementChannels,
)
from icoapi.scripts.data_handling import resolve_measurement_channels

# -- Classes ------------------------------------------------------------------


@dataclass
class UnitSetup:
    """What a unit does in a measurement"""

    unit: Unit
    instructions: MeasurementInstructions
    """The instructions for this unit (see :func:`instructions_for_unit`)"""
    resolved_channels: ResolvedMeasurementChannels
    """The sensors of the channels of the unit"""


# -- Functions ----------------------------------------------------------------


def instructions_for_unit(
    instructions: MeasurementInstructions, unit: str
) -> MeasurementInstructions:
    """Get the instructions of a measurement for one unit

    Args:

        instructions:
            The instructions of the measurement

        unit:
            The name of the unit

    Returns:

        The instructions of the measurement, with everything replaced that is
        set for the unit in ``instructions.units``. The result does not have
        instructions for units of its own.

    """

    own = (instructions.units or {}).get(unit)
    if own is None:
        return replace(instructions, units=None, unit_mac_addresses=None)

    return replace(
        instructions,
        first=own.first or instructions.first,
        second=own.second or instructions.second,
        third=own.third or instructions.third,
        adc=own.adc or instructions.adc,
        sensor_configuration=(
            own.sensor_configuration or instructions.sensor_configuration
        ),
        mac_address=own.mac_address or instructions.mac_address,
        units=None,
        unit_mac_addresses=None,
    )


def mac_address_of_unit(
    instructions: MeasurementInstructions, unit: str
) -> str | None:
    """Get the MAC address of the sensor device of a unit (if there is one)

    The address set for the unit in ``units`` takes precedence over the one in
    ``unit_mac_addresses``.
    """

    own = (instructions.units or {}).get(unit)
    if own is not None and own.mac_address:
        return own.mac_address
    return (instructions.unit_mac_addresses or {}).get(unit)


def check_unit_names(
    instructions: MeasurementInstructions, units: list[Unit]
) -> None:
    """Check that instructions are only given for units that exist

    Raises:

        HTTPException:
            If ``units`` or ``unit_mac_addresses`` of the instructions
            contain a name that is not the name of one of the units (422)

    """

    names = [unit.key for unit in units]
    unknown = sorted(
        (set(instructions.units or {}) | set(instructions.unit_mac_addresses or {}))
        - set(names)
    )
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Instructions for unknown units: {', '.join(unknown)}. "
                f"Units: {', '.join(names)}"
            ),
        )


def unit_setups(
    instructions: MeasurementInstructions, units: list[Unit]
) -> list[UnitSetup]:
    """Get what every unit does in a measurement

    Raises:

        HTTPException:
            If there are instructions for a unit that does not exist, or if
            the sensors of the instructions of a unit can not be resolved
            (422). The error names the unit.

    """

    check_unit_names(instructions, units)

    setups = []
    for unit in units:
        own = instructions_for_unit(instructions, unit.key)
        try:
            resolved = resolve_measurement_channels(own)
        except HTTPException as error:
            if isinstance(error.detail, str):
                error.detail = f"Unit {unit.key}: {error.detail}"
            raise
        setups.append(UnitSetup(unit, own, resolved))
    return setups

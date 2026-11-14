"""Check that all units are ready for a measurement

With multi STU support a measurement uses all units (a CAN network with its
STU and sensor device each). Starting it is all-or-nothing: If one unit is not
ready, nothing starts. The checks run for all units at the same time and
report every problem, not only the first.

A unit is ready, if

- the STU answers,
- a sensor device (STH) is connected to it,
- the connection to the sensor device is good enough (RSSI),
- the sensor device answers and accepts the configuration of the measurement
  (ADC and sensor channels) and
- the CAN bus of the unit can transport the data of the measurement.
"""

# -- Imports ------------------------------------------------------------------

import asyncio
from dataclasses import asdict, dataclass, field
import logging
import os
from typing import Any

from fastapi import HTTPException
from icostate import State
from icostate.error import IncorrectStateError
from icotronic.can.error import (
    ErrorResponseError,
    NoResponseError,
    UnsupportedFeatureException,
)
from icotronic.can.sensor import SensorConfiguration

from icoapi.models.globals import Unit
from icoapi.models.models import (
    MeasurementInstructions,
    ResolvedMeasurementChannels,
)
from icoapi.scripts.measurement import (
    measurement_preparations,
    verify_sensor_configuration_applied,
)

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 20.0
"""Time (in seconds) a unit has to be ready"""

# -- Classes ------------------------------------------------------------------


@dataclass
class UnitCheck:  # pylint: disable=too-many-instance-attributes
    """Result of the preflight check of a unit"""

    unit: str
    """Name of the unit"""
    problems: list[str] = field(default_factory=list)
    """What keeps the unit from measuring (empty, if it is ready)"""
    tool_name: str | None = None
    stu_mac_address: str | None = None
    sth_mac_address: str | None = None
    rssi: int | None = None
    supply_voltage: float | None = None
    sample_rate: float | None = None
    messages_per_second: float | None = None
    """Number of streaming messages per second on the CAN bus of the unit"""

    @property
    def ok(self) -> bool:
        """Check if the unit is ready"""

        return not self.problems


# -- Functions ----------------------------------------------------------------


def minimum_rssi() -> int:
    """Get the lowest RSSI a connection to a sensor device may have

    The value is set with the environment variable ``ICOAPI_MIN_RSSI``.
    """

    try:
        return int(os.getenv("ICOAPI_MIN_RSSI", "-90"))
    except ValueError:
        return -90


def maximum_messages_per_second() -> float:
    """Get the number of streaming messages one CAN bus can transport

    A CAN bus with 1 Mbit/s transports about 7000 to 8000 extended frames per
    second. The value is set with the environment variable
    ``ICOAPI_MAX_MESSAGES_PER_SECOND``.
    """

    try:
        return float(os.getenv("ICOAPI_MAX_MESSAGES_PER_SECOND", "7000"))
    except ValueError:
        return 7000.0


def messages_per_second(
    sample_rate: float, resolved_channels: ResolvedMeasurementChannels
) -> float:
    """Get the number of streaming messages per second of a measurement

    A message contains one value for each of the two or three enabled
    channels or, if only one channel is enabled, three values of that channel.
    """

    enabled = sum(
        getattr(resolved_channels, slot).channel_number != 0
        for slot in ("first", "second", "third")
    )
    return sample_rate / (3 if enabled <= 1 else enabled)


async def _check(
    unit: Unit,
    check: UnitCheck,
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    configure: bool,
) -> None:
    """Run the checks of a unit (raises exceptions for failed requests)"""

    system = unit.system

    check.stu_mac_address = (await system.get_stu_mac_address()).format()
    if not await system.is_sensor_node_connected():
        check.problems.append("No sensor device (STH) is connected")
        return
    if system.state != State.SENSOR_NODE_CONNECTED:
        check.problems.append(
            f"The unit is in state {system.state.name}, but a sensor device"
            " has to be connected"
        )
        return

    node = system.sensor_node
    assert system.sensor_node_attributes is not None
    check.sth_mac_address = system.sensor_node_attributes.mac_address.format()
    check.tool_name = await node.get_name()

    check.rssi = await node.get_rssi()
    if check.rssi < minimum_rssi():
        check.problems.append(
            f"The connection to the sensor device is too weak (RSSI"
            f" {check.rssi}, at least {minimum_rssi()} is required)"
        )

    try:
        check.supply_voltage = await node.get_supply_voltage()
    except NoResponseError:
        # Like a measurement without the check: Only the information is missing
        logger.warning("Could not read supply voltage of unit <%s>", unit.key)

    if configure:
        await measurement_preparations(system, instructions, resolved_channels)
        await verify_sensor_configuration_applied(
            system,
            SensorConfiguration(
                resolved_channels.first.channel_number,
                resolved_channels.second.channel_number,
                resolved_channels.third.channel_number,
            ),
        )

    adc = await system.get_adc_configuration()
    check.sample_rate = adc.sample_rate()
    if not any(
        getattr(resolved_channels, slot).channel_number != 0
        for slot in ("first", "second", "third")
    ):
        # Without channels there is nothing to transport (yet)
        return
    check.messages_per_second = messages_per_second(
        check.sample_rate, resolved_channels
    )
    if check.messages_per_second > maximum_messages_per_second():
        check.problems.append(
            f"The measurement needs {check.messages_per_second:.0f} messages"
            " per second on the CAN bus, but it can transport about"
            f" {maximum_messages_per_second():.0f}: Use fewer channels or a"
            " lower sample rate"
        )


async def check_unit(
    unit: Unit,
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    *,
    configure: bool,
) -> UnitCheck:
    """Check if a unit is ready for a measurement

    Args:

        unit:
            The unit to check

        instructions:
            The instructions of the measurement

        resolved_channels:
            The sensors of the channels of the measurement

        configure:
            Write the configuration of the measurement (ADC and sensor
            channels) to the sensor device and check that it was applied.
            Without it nothing is changed.

    Returns:

        The result of the check. Failures of the unit are problems of the
        result, they are not raised.

    """

    check = UnitCheck(unit=unit.key)
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            await _check(unit, check, instructions, resolved_channels, configure)
    except TimeoutError:
        check.problems.append(
            f"The unit did not answer in {CHECK_TIMEOUT:.0f} seconds"
        )
    except (NoResponseError, ErrorResponseError) as error:
        check.problems.append(f"No (correct) response: {error}")
    except UnsupportedFeatureException as error:
        check.problems.append(f"Unsupported feature: {error}")
    except IncorrectStateError as error:
        check.problems.append(f"Incorrect state: {error}")
    except HTTPException as error:
        check.problems.append(str(error.detail))
    except AssertionError:
        check.problems.append("Invalid ADC configuration")
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.exception("Check of unit <%s> failed", unit.key)
        check.problems.append(f"{type(error).__name__}: {error}")

    if not check.ok:
        logger.warning(
            "Unit <%s> is not ready: %s", unit.key, "; ".join(check.problems)
        )
    return check


async def check_units(
    units: list[Unit],
    instructions: MeasurementInstructions,
    resolved_channels: ResolvedMeasurementChannels,
    *,
    configure: bool,
) -> list[UnitCheck]:
    """Check all units at the same time (see :func:`check_unit`)"""

    return list(
        await asyncio.gather(*(
            check_unit(
                unit, instructions, resolved_channels, configure=configure
            )
            for unit in units
        ))
    )


def describe_checks(checks: list[UnitCheck]) -> dict[str, Any]:
    """Describe the result of the checks of all units (for responses)"""

    return {
        "ready": all(check.ok for check in checks),
        "units": [{**asdict(check), "ok": check.ok} for check in checks],
    }


def raise_for_failed_checks(checks: list[UnitCheck]) -> None:
    """Raise an error that lists all problems of all units

    Raises:

        HTTPException:
            If at least one unit is not ready (status 502, the detail
            contains all units, see :func:`describe_checks`)

    """

    failed = [check for check in checks if not check.ok]
    if not failed:
        return

    raise HTTPException(
        status_code=502,
        detail={
            "message": (
                "The measurement was not started, since "
                f"{len(failed)} of {len(checks)} units are not ready: "
                + "; ".join(
                    f"{check.unit}: {', '.join(check.problems)}"
                    for check in failed
                )
            ),
            **describe_checks(checks),
        },
    )

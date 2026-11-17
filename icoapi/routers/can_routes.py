"""Routes for CAN network discovery and connection"""

from fastapi import APIRouter, Depends, HTTPException
from icostate import CANInitError
from icotronic.can.error import ErrorResponseError, NoResponseError

from icoapi.models.globals import ICOsystemSingleton, require_no_measurement
from icoapi.models.models import CANNetwork, CANNetworksModel, UnitStateModel
from icoapi.scripts.can_scripts import (
    NoCANNetworkError,
    UnknownCANNetworkError,
)
from icoapi.scripts.errors import (
    HTTP_404_CAN_NETWORK_NOT_FOUND_EXCEPTION,
    HTTP_404_CAN_NETWORK_NOT_FOUND_SPEC,
    HTTP_404_UNIT_NOT_FOUND_EXCEPTION,
    HTTP_404_UNIT_NOT_FOUND_SPEC,
    HTTP_409_MEASUREMENT_RUNNING_SPEC,
    HTTP_502_CAN_INIT_EXCEPTION,
    HTTP_502_CAN_INIT_SPEC,
    HTTP_502_CAN_NO_RESPONSE_EXCEPTION,
)

router = APIRouter(prefix="/can", tags=["CAN Network"])


def get_networks_model() -> CANNetworksModel:
    """Get the current CAN network information"""

    return CANNetworksModel(
        status=ICOsystemSingleton.status,
        networks=list(ICOsystemSingleton.networks),
        selected=ICOsystemSingleton.selected,
        error=ICOsystemSingleton.error,
    )


@router.get("/networks")
async def can_networks() -> CANNetworksModel:
    """Search for available CAN networks"""

    await ICOsystemSingleton.scan()
    return get_networks_model()


@router.get("/units")
async def can_units() -> list[UnitStateModel]:
    """Get the units: the connected CAN networks with their STUs

    Without multi STU support there is at most one unit. With it every
    connected network is a unit, and measurements use all of them.
    """

    return [unit.state() for unit in ICOsystemSingleton.units()]


@router.put(
    "/connect",
    responses={
        404: HTTP_404_CAN_NETWORK_NOT_FOUND_SPEC,
        409: HTTP_409_MEASUREMENT_RUNNING_SPEC,
        502: HTTP_502_CAN_INIT_SPEC,
    },
    dependencies=[Depends(require_no_measurement)],
)
async def can_connect(network: CANNetwork | None = None) -> CANNetworksModel:
    """Connect to a CAN network

    If no network is given, the default network is used (or else the first
    network that was found).

    With multi STU support the network becomes another unit. Connecting to a
    network that is a unit already, connects it again. The other units are
    not changed.
    """

    try:
        await ICOsystemSingleton.connect(network)
    except (NoCANNetworkError, UnknownCANNetworkError) as error:
        raise HTTP_404_CAN_NETWORK_NOT_FOUND_EXCEPTION from error
    except CANInitError as error:
        raise HTTPException(
            status_code=HTTP_502_CAN_INIT_EXCEPTION.status_code,
            detail=f"{HTTP_502_CAN_INIT_EXCEPTION.detail} {error}",
        ) from error
    except (NoResponseError, ErrorResponseError) as error:
        raise HTTP_502_CAN_NO_RESPONSE_EXCEPTION from error
    return get_networks_model()


@router.put(
    "/disconnect",
    responses={
        404: HTTP_404_UNIT_NOT_FOUND_SPEC,
        409: HTTP_409_MEASUREMENT_RUNNING_SPEC,
    },
    dependencies=[Depends(require_no_measurement)],
)
async def can_disconnect(unit: str | None = None) -> CANNetworksModel:
    """Disconnect from the CAN network

    With multi STU support only the given unit (the name of the unit is the
    `interface:channel` of its network) is disconnected. Without a unit all
    units are disconnected.
    """

    try:
        await ICOsystemSingleton.disconnect(unit)
    except KeyError as error:
        raise HTTP_404_UNIT_NOT_FOUND_EXCEPTION from error
    return get_networks_model()

"""Routes for CAN network discovery and connection"""

from fastapi import APIRouter, HTTPException
from icostate import CANInitError
from icotronic.can.error import ErrorResponseError, NoResponseError

from icoapi.models.globals import ICOsystemSingleton
from icoapi.models.models import CANNetwork, CANNetworksModel
from icoapi.scripts.can_scripts import (
    NoCANNetworkError,
    UnknownCANNetworkError,
)
from icoapi.scripts.errors import (
    HTTP_404_CAN_NETWORK_NOT_FOUND_EXCEPTION,
    HTTP_404_CAN_NETWORK_NOT_FOUND_SPEC,
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


@router.put(
    "/connect",
    responses={
        404: HTTP_404_CAN_NETWORK_NOT_FOUND_SPEC,
        502: HTTP_502_CAN_INIT_SPEC,
    },
)
async def can_connect(network: CANNetwork | None = None) -> CANNetworksModel:
    """Connect to a CAN network

    If no network is given, the default network is used (or else the first
    network that was found).
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


@router.put("/disconnect")
async def can_disconnect() -> CANNetworksModel:
    """Disconnect from the CAN network"""

    await ICOsystemSingleton.disconnect()
    return get_networks_model()

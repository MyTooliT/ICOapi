from fastapi import APIRouter, status

from ..models.models import STHDeviceResponseModel
from ..scripts.sth_scripts import get_sth_devices_from_network

router = APIRouter(
    prefix="/sth",
    tags=["devices"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    '', status_code=status.HTTP_200_OK)
async def sth() -> list[STHDeviceResponseModel]:
    devices = await get_sth_devices_from_network()
    return [STHDeviceResponseModel.from_network(device) for device in devices]


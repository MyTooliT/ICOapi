from fastapi import APIRouter, status
from fastapi.params import Depends

from models.globals import MeasurementState, NetworkSingleton, get_measurement_state, get_trident_client
from models.models import SystemStateModel
from models.trident import StorageClient
from scripts.file_handling import get_disk_space_in_gb

router = APIRouter(
    tags=["General"]
)


@router.get("/state", status_code=status.HTTP_200_OK)
def state(measurement_state: MeasurementState = Depends(get_measurement_state), storage: StorageClient = Depends(get_trident_client)) -> SystemStateModel:
    return SystemStateModel(
        can_ready=NetworkSingleton.has_instance(),
        disk_capacity=get_disk_space_in_gb(),
        measurement_status=measurement_state.get_status(),
        cloud_status=storage.is_authenticated()
    )


@router.put("/reset-can", status_code=status.HTTP_200_OK)
async def reset_can():
    await NetworkSingleton.close_instance()
    await NetworkSingleton.create_instance_if_none()

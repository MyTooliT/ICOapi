from fastapi import APIRouter, status

from icoapi.models.models import AvailableSensorInformation
from icoapi.scripts.data_handling import get_sensor_config_data

router = APIRouter(
    prefix="/sensor",
    tags=["Sensor"]
)

@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_model=AvailableSensorInformation,
)
def query_sensors():
    sensors, configs, default = get_sensor_config_data()
    return AvailableSensorInformation(
        sensors=sensors,
        configurations=configs,
        default_configuration_id=default
    )
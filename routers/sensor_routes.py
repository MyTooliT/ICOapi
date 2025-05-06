from typing import List

from fastapi import APIRouter, status

from models.models import Sensor
from scripts.data_handling import get_sensors

router = APIRouter(
    prefix="/sensor",
    tags=["Sensor"]
)

@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_model=List[Sensor],
    responses={
        200: {
            "content": "application/json",
            "description": "Available sensors for platform."
        },
        500: {
            "content": "application/json",
            "description": "Can't find sensor declaration."
        }
    }
)
def query_sensors():
    return get_sensors()
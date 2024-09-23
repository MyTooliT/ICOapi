import time

from fastapi import APIRouter, status

from ..models.GlobalNetwork import NetworkSingleton

router = APIRouter()


@router.get("/ping", status_code=status.HTTP_200_OK)
def ping():
    return "OK"


@router.get("/delay", status_code=status.HTTP_200_OK)
def delay():
    time.sleep(1)
    return "OK"


@router.put("/reset-can", status_code=status.HTTP_200_OK)
async def reset_can():
    await NetworkSingleton.close_instance()
    await NetworkSingleton.create_instance_if_none()


@router.options("*", status_code=status.HTTP_200_OK)
def options():
    return "OK"

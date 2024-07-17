import time

from fastapi import APIRouter, status

router = APIRouter()


@router.get("/ping", status_code=status.HTTP_200_OK)
def ping():
    return "OK"


@router.get("/delay", status_code=status.HTTP_200_OK)
def delay():
    time.sleep(1)
    return "OK"

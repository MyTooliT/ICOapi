from fastapi import APIRouter

from ..types.types import Device

router = APIRouter(
    prefix="/devices",
    tags=["devices"],
    responses={404: {"description": "Not found"}},
)

mock_data: list[Device] = [
    Device(id=1, name='STH 1', mac='AA:BB:CC:DD:EE:FF'),
    Device(id=2, name='Messerkopf', mac='AA:00:CC:DD:EE:FF'),
    Device(id=2, name='Mini Mill', mac='DD:00:CC:DD:EE:FF'),
]


@router.get('/')
async def index() -> list[Device]:
    return mock_data

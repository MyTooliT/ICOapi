from pydantic import BaseModel


class Device(BaseModel):
    id: int
    name: str
    mac: str


class STHDevice(Device):
    rssi: float


class STUDevice(Device):
    pass


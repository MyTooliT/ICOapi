from typing import Optional
from json import JSONEncoder
from pydantic import BaseModel
from dataclasses import dataclass
from mytoolit.can.network import STHDeviceInfo


class STHDeviceResponseModel(BaseModel):
    """Wrapper for STH Device class implementing Pydantic features"""

    name: str  # The (Bluetooth advertisement) name of the STH
    device_number: int  # The device number of the STH
    mac_address: str  # The (Bluetooth) MAC address of the STH
    rssi: int  # The RSSI of the STH

    @classmethod
    def from_network(cls, original_object: STHDeviceInfo):
        return STHDeviceResponseModel(
            name=original_object.name,
            device_number=original_object.device_number,
            mac_address=original_object.mac_address.format(),
            rssi=original_object.rssi)


class STHRenameRequestModel(BaseModel):
    mac_address: str
    new_name: str


class STHRenameResponseModel(BaseModel):
    """Response Model for renaming a STH device"""
    name: str
    old_name: str
    mac_address: str


@dataclass
class STUDeviceResponseModel:
    """Response Model for STU devices"""

    name: str
    device_number: int
    mac_address: str


class STUName(BaseModel):
    name: str


@dataclass
class WSMetaData:
    """Data model for measurement WS"""

    mac: str
    time: int
    first: int
    second: int
    third: int


@dataclass
class ADCValues:
    """Data model for ADC values"""

    prescaler: Optional[int]
    acquisition_time: Optional[int]
    oversampling_rate: Optional[int]
    reference_voltage: Optional[float]


class DataValueModel(BaseModel, JSONEncoder):
    """Data model for sending measured data"""

    timestamp: float
    first: float | None
    second: float | None
    third: float | None
    counter: int

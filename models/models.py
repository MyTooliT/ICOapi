from typing import Optional, Union
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
    """
    Data model for measurement WS

    Attributes:
        mac (str): MAC address
        time (int): Measurement time
        first (int): First measurement channel number
        second (int): Second measurement channel number
        third (int): Third measurement channel number
        ift_requested (bool): IFT value should be calculated
        ift_channel: which channel should be used for IFT value
        ift_window_width (int): IFT window width
    """

    mac: str
    time: int | None
    first: int
    second: int
    third: int
    ift_requested: bool
    ift_channel: Union["first", "second", "third"]
    ift_window_width: int


@dataclass
class ADCValues:
    """Data model for ADC values"""

    prescaler: Optional[int]
    acquisition_time: Optional[int]
    oversampling_rate: Optional[int]
    reference_voltage: Optional[float]


class DataValueModel(BaseModel, JSONEncoder):
    """Data model for sending measured data"""

    timestamp: float | None
    first: float | None
    second: float | None
    third: float | None
    ift: list | None
    counter: int | None
    dataloss: float | None


@dataclass
class MeasurementFileDetails:
    """Data model for measurement files"""

    name: str
    created: str
    size: int


@dataclass
class APIStateModel:
    """Data model for API state"""
    can_ready: bool


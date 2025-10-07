from enum import unique, StrEnum
from typing import Any, Dict, List, Optional
from json import JSONEncoder

import pandas
from pydantic import BaseModel, model_validator
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
class ADCValues:
    """Data model for ADC values"""

    prescaler: Optional[int]
    acquisition_time: Optional[int]
    oversampling_rate: Optional[int]
    reference_voltage: Optional[float]


@dataclass
class MeasurementInstructionChannel:
    """Data model for measurement instruction channel definition"""

    channel_number: int
    sensor_id: Optional[str]


@dataclass
class Quantity:
    value: float|int
    unit: str

@unique
class MetadataPrefix(StrEnum):
    """Enum for metadata prefixes"""
    PRE = "pre"
    POST = "post"


@dataclass
class Metadata:
    version: str
    profile: str
    parameters: Dict[str, Quantity|Any]


@dataclass
class MeasurementInstructions:
    """
    Data model for measurement WS

    Attributes:
        name (str): Custom name
        mac_address (str): MAC address
        time (int): Measurement time
        first (MeasurementInstructionChannel): First measurement channel number
        second (MeasurementInstructionChannel): Second measurement channel number
        third (MeasurementInstructionChannel): Third measurement channel number
        ift_requested (bool): IFT value should be calculated
        ift_channel: which channel should be used for IFT value
        ift_window_width (int): IFT window width
        adc (ADCValues): ADC settings
        meta (Metadata): Pre-measurement metadata
    """

    name: str | None
    mac_address: str
    time: int | None
    first: MeasurementInstructionChannel
    second: MeasurementInstructionChannel
    third: MeasurementInstructionChannel
    ift_requested: bool
    ift_channel: str
    ift_window_width: int
    adc: ADCValues | None
    meta: Metadata | None
    wait_for_post_meta: bool = False
    disconnect_after_measurement: bool = False


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
class FileCloudDetails:
    """Data model for details of file on cloud"""
    is_uploaded: bool
    upload_timestamp: str | None


@dataclass
class MeasurementFileDetails:
    """Data model for measurement files"""

    name: str
    created: str
    size: int
    cloud: FileCloudDetails


@dataclass
class DiskCapacity:
    """Data model for disk capacity"""

    total: float | None
    available: float | None


@dataclass
class FileListResponseModel:
    """Data model for file list response"""

    capacity: DiskCapacity
    files: list[MeasurementFileDetails]
    directory: str


class Dataset(BaseModel, JSONEncoder):
    data: list[float]
    name: str


class ParsedMeasurement(BaseModel, JSONEncoder):
    """Data model for parsed measurement for analyze tab"""

    name: str
    counter: list[int]
    timestamp: list[float]
    datasets: list[Dataset]


@dataclass
class MeasurementStatus:
    running: bool
    name: Optional[str] = None
    start_time: Optional[str] = None
    tool_name: Optional[str] = None
    instructions: Optional[MeasurementInstructions] = None


@dataclass
class ControlResponse:
    message: str
    data: MeasurementStatus


@dataclass
class Feature:
    enabled: bool
    healthy: bool


class SystemStateModel(BaseModel, JSONEncoder):
    """Data model for API state"""
    can_ready: bool
    disk_capacity: DiskCapacity
    measurement_status: MeasurementStatus
    cloud: Feature


class SocketMessage(BaseModel, JSONEncoder):
    """Data model for websocket message"""
    message: str
    data: Optional[Any] = None


@dataclass
class TridentConfig:
    protocol: str
    domain: str
    base_path: str
    service: str
    username: str
    password: str
    default_bucket: str
    enabled: bool


@dataclass
class TridentBucketMeta:
    Name: str
    CreationDate: str


@dataclass
class TridentBucketObject:
    Key: str
    LastModified: str
    ETag: str
    Size: int
    StorageClass: str


@dataclass
class LogResponse:
    filename: str
    content: str


@dataclass
class LogFileMeta:
    name: str
    size: int
    first_timestamp: Optional[str]
    last_timestamp: Optional[str]


@dataclass
class LogListResponse:
    files: List[LogFileMeta]
    directory: str
    max_bytes: int
    backup_count: int


class Sensor(BaseModel):
    name: str
    sensor_type: str | None
    sensor_id: str
    unit: str
    dimension: str
    phys_min: float
    phys_max: float
    volt_min: float
    volt_max: float
    scaling_factor: float = 1
    offset: float = 0

    # This will be called after the model is initialized
    @model_validator(mode="before")
    def calculate_scaling_factor_and_offset(cls, values):
        phys_min = values.get('phys_min')
        phys_max = values.get('phys_max')
        volt_min = values.get('volt_min')
        volt_max = values.get('volt_max')

        scaling_factor = (phys_max - phys_min) / (volt_max - volt_min)
        offset = phys_max - scaling_factor * volt_max

        values['scaling_factor'] = scaling_factor
        values['offset'] = offset
        return values


    def convert_to_phys(self, volt_value: float) -> float:
        return volt_value * self.scaling_factor + self.offset


@dataclass
class PCBSensorConfiguration:
    configuration_id: str
    configuration_name: str
    channels: dict[int, Sensor]


@dataclass
class AvailableSensorInformation:
    sensors: list[Sensor]
    configurations: list[PCBSensorConfiguration]
    default_configuration_id: str


class HDF5NodeInfo(BaseModel, JSONEncoder):
    name: str
    type: str
    path: str
    attributes: dict[str, Any]

@dataclass
class ParsedHDF5FileContent(JSONEncoder):
    acceleration_df: pandas.DataFrame
    sensor_df: pandas.DataFrame
    acceleration_meta: HDF5NodeInfo
    pictures: dict[str, list[str]]


class ParsedMetadata(BaseModel, JSONEncoder):
    acceleration: HDF5NodeInfo
    pictures: dict[str, list[str]]
    sensors: list[Sensor]


@dataclass
class ConfigFileInfoHeader:
    schema_name: str
    schema_version: str
    config_name: str
    config_version: str
    config_date: str


@dataclass
class ConfigFileBackup:
    filename: str
    timestamp: str
    info_header: ConfigFileInfoHeader


@dataclass
class ConfigFile:
    name: str
    filename: str
    backup: list[ConfigFileBackup]
    endpoint: str
    timestamp: str
    description: str
    info_header: ConfigFileInfoHeader


@dataclass
class ConfigResponse:
    files: list[ConfigFile]


class ConfigRestoreRequest(BaseModel):
    filename: str
    backup_filename: str


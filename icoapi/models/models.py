"""Data Model Information"""

from enum import unique, StrEnum
from dataclasses import dataclass
from json import JSONEncoder
from typing import Any, Dict, List, Optional

import pandas
from pydantic import BaseModel, model_validator

from icostate import ADCConfiguration, SensorNodeInfo


class STHDeviceResponseModel(BaseModel):
    """Wrapper for STH Device class implementing Pydantic features"""

    name: str  # The (Bluetooth advertisement) name of the STH
    device_number: int  # The device number of the STH
    mac_address: str  # The (Bluetooth) MAC address of the STH
    rssi: int  # The RSSI of the STH

    @classmethod
    def from_network(cls, original_object: SensorNodeInfo):
        """Convert sensor node information to STH device response model"""
        return STHDeviceResponseModel(
            name=original_object.name,
            device_number=original_object.sensor_node_number,
            mac_address=original_object.mac_address.format(),
            rssi=original_object.rssi,
        )


class STHRenameRequestModel(BaseModel):
    """Data model for renaming sensor nodes"""

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
    """STU name information"""

    name: str


@dataclass
class ADCValues:
    """Data model for ADC values"""

    prescaler: Optional[int]
    acquisition_time: Optional[int]
    oversampling_rate: Optional[int]
    reference_voltage: Optional[float]

    def to_adc_configuration(self) -> ADCConfiguration:
        """Get the ADC configuration of this object

        Returns:

            The ADC configuration that corresponds to the current

        Examples:

            Get ADC configuration to calculate default sample rate

            >>> adc_values = ADCValues(prescaler=None,
            ...                        acquisition_time=None,
            ...                        oversampling_rate=None,
            ...                        reference_voltage=None)
            >>> round(adc_values.to_adc_configuration().sample_rate())
            9524

            Get sample rate for custom ADC values

            >>> adc_values = ADCValues(prescaler=2,
            ...                        acquisition_time=8,
            ...                        oversampling_rate=256,
            ...                        reference_voltage=None)
            >>> round(adc_values.to_adc_configuration().sample_rate())
            2381

        """

        return ADCConfiguration(
            prescaler=self.prescaler,
            acquisition_time=self.acquisition_time,
            oversampling_rate=self.oversampling_rate,
            reference_voltage=self.reference_voltage,
        )


@dataclass
class MeasurementInstructionChannel:
    """Data model for measurement instruction channel definition"""

    channel_number: int
    sensor_id: Optional[str]


@dataclass
class Quantity:
    """Data model for measurement value including unit information"""

    value: float | int
    unit: str


@unique
class MetadataPrefix(StrEnum):
    """Enum for metadata prefixes"""

    PRE = "pre"
    POST = "post"


@dataclass
class Metadata:
    """Metadata model"""

    version: str
    profile: str
    parameters: Dict[str, Quantity | Any]


# pylint: disable=too-many-instance-attributes


@dataclass
class MeasurementInstructions:
    """
    Data model for measurement WS

    Attributes:
        name (str): Custom name for measurement
        mac_address (str): MAC address
        time (int): Measurement time in seconds
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


# pylint: enable=too-many-instance-attributes


class DataValueModel(BaseModel, JSONEncoder):
    """Data model for sending measured data"""

    timestamp: float | None
    first: float | None
    second: float | None
    third: float | None
    ift: list | None
    counter: int | None
    dataloss: float | None


@unique
class FileCloudStatus(StrEnum):
    """Sync status of a local measurement file relative to cloud"""

    NOT_UPLOADED = "not_uploaded"
    OUTDATED = "outdated"
    UPDATING = "updating"
    UP_TO_DATE = "up_to_date"
    ERROR = "error"
    CREATED = "created"


@dataclass
class FileCloudDetails:
    """Data model for details of file on cloud"""
    status: FileCloudStatus
    id: int | None
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


@dataclass
class EmbeddedFileUploadResponse:
    """Data model for embedded file upload response"""

    dataset_name: str
    original_name: str
    mime: str
    size: int


@dataclass
class EmbeddedFileContent:
    """Embedded file payload and metadata"""

    content: bytes
    original_name: str
    mime: str


class EmbeddedFileInfo(BaseModel, JSONEncoder):
    """Embedded file information for clients"""

    dataset_name: str
    original_name: str
    mime: str
    size: int
    download_path: str


class EmbeddedFileDeleteResponse(BaseModel, JSONEncoder):
    """Response for embedded file deletion"""
    file_name: str
    dataset_name: str


class Dataset(BaseModel, JSONEncoder):
    """Measurement data"""

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
    """Measurement status information"""

    running: bool
    name: Optional[str] = None
    start_time: Optional[str] = None
    tool_name: Optional[str] = None
    instructions: Optional[MeasurementInstructions] = None


@dataclass
class ControlResponse:
    """Response to measurement start request"""

    message: str
    data: MeasurementStatus


@dataclass
class Feature:
    """Trident feature"""

    enabled: bool
    healthy: bool
    manage_url: str | None = None


class SystemStateModel(BaseModel, JSONEncoder):
    """Data model for API state"""

    can_ready: bool
    disk_capacity: DiskCapacity
    measurement_status: MeasurementStatus
    cloud: Feature


class SocketMessage(BaseModel, JSONEncoder):
    """Data model for WebSocket message"""

    message: str
    data: Optional[Any] = None


# pylint: disable=too-many-instance-attributes


@dataclass
class CloudConfig:
    """Trident configuration data"""
    connector: str
    protocol: str
    domain: str
    base_path: str
    service: str
    username: str
    password: str
    default_bucket: str
    enabled: bool
    manage_assets_path: str | None = None
    virtual_group_root: str | None = None


# pylint: enable=too-many-instance-attributes

# pylint: disable=invalid-name, missing-class-docstring


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


# pylint: enable=invalid-name, missing-class-docstring


@dataclass
class LogResponse:
    """Response to log requests"""

    filename: str
    content: str


@dataclass
class LogFileMeta:
    """Log file metadata"""

    name: str
    size: int
    first_timestamp: Optional[str]
    last_timestamp: Optional[str]


@dataclass
class LogListResponse:
    """Response for multiple log files"""

    files: List[LogFileMeta]
    directory: str
    max_bytes: int
    backup_count: int


class Sensor(BaseModel):
    """Sensor attributes"""

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

    @model_validator(mode="before")
    @classmethod
    def calculate_scaling_factor_and_offset(cls, values):
        """This will be called after the model is initialized"""
        phys_min = values.get("phys_min")
        phys_max = values.get("phys_max")
        volt_min = values.get("volt_min")
        volt_max = values.get("volt_max")

        scaling_factor = (phys_max - phys_min) / (volt_max - volt_min)
        offset = phys_max - scaling_factor * volt_max

        values["scaling_factor"] = scaling_factor
        values["offset"] = offset
        return values

    def convert_to_phys(self, volt_value: float) -> float:
        """Convert voltage to physical value"""

        return volt_value * self.scaling_factor + self.offset


@dataclass
class PCBSensorConfiguration:
    """Sensor configuration for a PCB"""

    configuration_id: str
    configuration_name: str
    channels: dict[int, Sensor]


@dataclass
class AvailableSensorInformation:
    """Information about available sensor nodes"""

    sensors: list[Sensor]
    configurations: list[PCBSensorConfiguration]
    default_configuration_id: str


class HDF5NodeInfo(BaseModel, JSONEncoder):
    """Information about HDF5 data file"""

    name: str
    type: str
    path: str
    attributes: dict[str, Any]


@dataclass
class ParsedHDF5FileContent(JSONEncoder):
    """HDF5 data file content"""

    acceleration_df: pandas.DataFrame
    sensor_df: pandas.DataFrame
    acceleration_meta: HDF5NodeInfo
    pictures: dict[str, list[str]]
    embedded_files: list[EmbeddedFileInfo]


class ParsedMetadata(BaseModel, JSONEncoder):
    """HDF5 metadata"""

    acceleration: HDF5NodeInfo
    pictures: dict[str, list[str]]
    sensors: list[Sensor]
    embedded_files: list[EmbeddedFileInfo]


@dataclass
class ConfigFileInfoHeader:
    """Configuration file header information"""

    schema_name: str
    schema_version: str
    config_name: str
    config_version: str
    config_date: str


@dataclass
class ConfigFileBackup:
    """Information about configuration backup file"""

    filename: str
    timestamp: str
    info_header: ConfigFileInfoHeader


@dataclass
class ConfigFile:
    """Information about configuration file"""

    name: str
    filename: str
    backup: list[ConfigFileBackup]
    endpoint: str
    timestamp: str
    description: str
    info_header: ConfigFileInfoHeader


@dataclass
class ConfigResponse:
    """Response model for configuration file data"""

    files: list[ConfigFile]


class ConfigRestoreRequest(BaseModel):
    """Data for request to restore configuration file from backup"""

    filename: str
    backup_filename: str


if __name__ == "__main__":
    from doctest import testmod

    testmod()

"""Code for handling sensor data"""
import json
import logging
import os
from os import PathLike, path
from typing import List, Optional
import pandas as pd
import tables
import yaml
from fastapi import HTTPException

from tables import (
    Float32Col,
    IsDescription,
    NoSuchNodeError,
    StringCol,
    UInt8Col,
)
from icotronic.measurement.storage import StorageData

from icoapi.models.models import (
    EmbeddedFileInfo,
    HDF5NodeInfo,
    MeasurementInstructions,
    MetadataPrefix, ParsedHDF5FileContent, Sensor,
    PCBSensorConfiguration,
    ResolvedChannel,
    ResolvedMeasurementChannels,
    CloudConfig,
)
from icoapi.models.models import ADCValues
from icoapi.scripts.config_helper import validate_dataspace_payload
from icoapi.scripts.errors import (
    HTTP_422_INLINE_SENSOR_CONFIG_REQUIRED_EXCEPTION,
    HTTP_422_UNKNOWN_SENSOR_ID_EXCEPTION,
)
from icoapi.scripts.file_handling import (
    ensure_folder_exists,
    get_sensors_file_path,
)

logger = logging.getLogger(__name__)


class AccelerationDataNotFoundError(HTTPException):
    """Exception raised when acceleration data is not found in HDF5 file"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_code = 500
        self.detail = "Acceleration data not found in HDF5 file"


def get_sensor_defaults() -> list[Sensor]:
    """Get list of default sensors"""

    return [
        Sensor(
            name="Acceleration 100g",
            sensor_type="ADXL1001",
            sensor_id="acc100g_01",
            unit="g",
            dimension="Acceleration",
            phys_min=-100,
            phys_max=100,
            volt_min=0.33,
            volt_max=2.97,
        ),
        Sensor(
            name="Acceleration 40g Y",
            sensor_type="ADXL358C",
            sensor_id="acc40g_y",
            unit="g",
            dimension="Acceleration",
            phys_min=-40,
            phys_max=40,
            volt_min=0.1,
            volt_max=1.7,
        ),
        Sensor(
            name="Acceleration 40g Z",
            sensor_type="ADXL358C",
            sensor_id="acc40g_z",
            unit="g",
            dimension="Acceleration",
            phys_min=-40,
            phys_max=40,
            volt_min=0.1,
            volt_max=1.7,
        ),
        Sensor(
            name="Acceleration 40g X",
            sensor_type="ADXL358C",
            sensor_id="acc40g_x",
            unit="g",
            dimension="Acceleration",
            phys_min=-40,
            phys_max=40,
            volt_min=0.1,
            volt_max=1.7,
        ),
        Sensor(
            name="Temperature",
            sensor_type="ADXL358C",
            sensor_id="temp_01",
            unit="°C",
            dimension="Temperature",
            phys_min=-40,
            phys_max=125,
            volt_min=0.772,
            volt_max=1.267,
        ),
        Sensor(
            name="Photodiode",
            sensor_type=None,
            sensor_id="photo_01",
            unit="-",
            dimension="Light",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        ),
        Sensor(
            name="Backpack 1",
            sensor_type=None,
            sensor_id="backpack_01",
            unit="/",
            dimension="Backpack",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        ),
        Sensor(
            name="Backpack 2",
            sensor_type=None,
            sensor_id="backpack_02",
            unit="/",
            dimension="Backpack",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        ),
        Sensor(
            name="Backpack 3",
            sensor_type=None,
            sensor_id="backpack_03",
            unit="/",
            dimension="Backpack",
            phys_min=0,
            phys_max=1,
            volt_min=0,
            volt_max=3.3,
        ),
        Sensor(
            name="Battery Voltage",
            sensor_type=None,
            sensor_id="vbat_01",
            unit="V",
            dimension="Voltage",
            phys_min=2.9,
            phys_max=4.2,
            volt_min=0.509,
            volt_max=0.737,
        ),
    ]


def get_sensor_configuration_defaults() -> list[dict]:
    """Get sensor channel default mapping"""

    return [{
        "configuration_id": "default",
        "configuration_name": "Default",
        "channels": {
            "1": {"sensor_id": "acc100g_01"},
            "2": {"sensor_id": "acc40g_y"},
            "3": {"sensor_id": "acc40g_z"},
            "4": {"sensor_id": "acc40g_x"},
            "5": {"sensor_id": "temp_01"},
            "6": {"sensor_id": "photo_01"},
            "7": {"sensor_id": "backpack_01"},
            "8": {"sensor_id": "backpack_02"},
            "9": {"sensor_id": "backpack_03"},
            "10": {"sensor_id": "vbat_01"},
        },
    }]


def get_voltage_from_raw(v_ref: float) -> float:
    """Get the conversion factor from bit value to voltage"""

    # 0xffff = 2**16 - 1 is maximum possible value of 16 bit ADC
    # If we would use 2**16 instead, then the maximum ADC value would not map
    # to the maximum voltage level: 0xffff/2^16 ≠ 1
    return v_ref / 0xFFFF


def get_sensors() -> list[Sensor]:
    """Get sensor default configuration"""

    file_path = get_sensors_file_path()
    try:
        sensors, _, _ = read_and_parse_sensor_data(file_path)
        return sensors
    except FileNotFoundError:
        sensor_defaults = get_sensor_defaults()
        configuration_defaults = get_sensor_configuration_defaults()
        write_sensor_defaults(
            sensor_defaults, configuration_defaults, file_path
        )
        return sensor_defaults


def read_and_parse_sensor_data(
    file_path: str | PathLike,
) -> tuple[list[Sensor], list[PCBSensorConfiguration], str]:
    """Read sensor configuration from file"""

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
            sensors = [Sensor(**sensor) for sensor in data["sensors"]]
            sensor_map: dict[str, Sensor] = {s.sensor_id: s for s in sensors}
            logger.info("Found %s sensors in %s", len(sensors), file_path)

            configs: list[PCBSensorConfiguration] = []
            for cfg in data.get("sensor_configurations", []):
                chan_map: dict[int, Sensor] = {}
                for ch_num, ch_entry in cfg.get("channels", {}).items():
                    sid = ch_entry.get("sensor_id")
                    if sid not in sensor_map:
                        raise ValueError(
                            f"Channel {ch_num} references unknown sensor_id"
                            f" '{sid}'"
                        )
                    chan_map[int(ch_num)] = sensor_map[sid]
                configs.append(
                    PCBSensorConfiguration(
                        configuration_id=cfg["configuration_id"],
                        configuration_name=cfg["configuration_name"],
                        channels=chan_map,
                    )
                )

            default_configuration_id = data.get("default_configuration_id", "")
            if default_configuration_id is None:
                default_configuration_id = configs[0].configuration_id

            return sensors, configs, default_configuration_id
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Could not find sensor.yaml file at {file_path}"
        ) from error


def get_sensor_config_data() -> (
    tuple[list[Sensor], list[PCBSensorConfiguration], str]
):
    """Get sensor configuration data"""

    file_path = get_sensors_file_path()
    try:
        logger.info("Read sensor data from configuration file: %s", file_path)
        return read_and_parse_sensor_data(file_path)

    except FileNotFoundError:
        logger.info(
            "Sensor configuration file not found using default configuration "
            "instead"
        )
        sensor_default = get_sensor_defaults()
        configuration_defaults = get_sensor_configuration_defaults()
        write_sensor_defaults(
            sensor_default, configuration_defaults, file_path
        )
        return read_and_parse_sensor_data(file_path)


def write_sensor_defaults(
    sensors: list[Sensor], configuration: list[dict], file_path: str | PathLike
):
    """Writer sensor default configuration"""

    ensure_folder_exists(os.path.dirname(file_path))
    with open(file_path, "w+", encoding="utf-8") as file:
        default_data = {"sensors": [sensor.model_dump() for sensor in sensors]}
        yaml.safe_dump(default_data, file, sort_keys=False)
        yaml.safe_dump(
            {"sensor_configurations": configuration}, file, sort_keys=False
        )
        logger.info(
            "File not found. Created new sensor.yaml with %s default"
            " sensors and %s default sensor configurations.",
            len(sensors),
            len(configuration),
        )


def is_inline_sensor_config_required() -> bool:
    """Whether `REQUIRE_INLINE_SENSOR_CONFIG` mandates inline sensor config

    Read fresh on every call (not cached at import time), so tests and
    deployments can change it without restarting the process.
    """

    return os.getenv("REQUIRE_INLINE_SENSOR_CONFIG", "0") == "1"


def get_active_sensor_configuration(
    sensor_configuration: Optional[PCBSensorConfiguration],
) -> PCBSensorConfiguration:
    """Get the sensor configuration to resolve `sensor_id` against

    The inline configuration if given, otherwise `sensors.yaml`'s default
    configuration.
    """

    if sensor_configuration is not None:
        return sensor_configuration

    _, configurations, default_configuration_id = get_sensor_config_data()
    for configuration in configurations:
        if configuration.configuration_id == default_configuration_id:
            return configuration

    logger.error(
        "Default sensor configuration <%s> not found.",
        default_configuration_id,
    )
    return PCBSensorConfiguration(
        configuration_id=default_configuration_id,
        configuration_name="",
        channels={},
    )


def resolve_channel(
    sensor_id: Optional[str], channels: dict[int, Sensor]
) -> ResolvedChannel:
    """Resolve a `sensor_id` to its channel number and Sensor within
    `channels` (a configuration's channel -> sensor mapping).

    `sensor_id is None` means the slot is disabled -
    `ResolvedChannel(channel_number=0, sensor=None)`. A `sensor_id` that
    doesn't match any sensor in `channels` is always a hard error: whether
    `channels` came from an inline request body or from `sensors.yaml`, an
    unresolvable `sensor_id` can only be a caller/configuration bug, never
    something to gracefully degrade from - there is no independent hardware
    channel to fall back to routing.

    :raises HTTPException: (422) if `sensor_id` is given but matches no
        sensor in `channels`.
    """

    if sensor_id is None:
        return ResolvedChannel(channel_number=0, sensor=None)

    for channel_number, sensor in channels.items():
        if sensor.sensor_id == sensor_id:
            logger.debug(
                "Resolved sensor ID %s to channel %s", sensor_id,
                channel_number,
            )
            return ResolvedChannel(
                channel_number=channel_number, sensor=sensor
            )

    raise HTTP_422_UNKNOWN_SENSOR_ID_EXCEPTION(sensor_id)


def resolve_measurement_channels(
    instructions: MeasurementInstructions,
) -> ResolvedMeasurementChannels:
    """Resolve `sensor_id` on each streaming slot to a channel number and
    Sensor - against the request's inline `sensor_configuration` if given,
    otherwise against `sensors.yaml`'s default configuration.

    This is the single place hardware routing (channel number) and value
    conversion (Sensor) are both derived from - reuse the result rather than
    resolving again. Shared by `/measurement/start` and
    `/measurement/execute` so the `REQUIRE_INLINE_SENSOR_CONFIG` guard can't
    drift between the two entry points. Must run before any CAN traffic.

    :raises HTTPException: (422) if inline sensor configuration is required
        but absent, or if a `sensor_id` doesn't resolve to a sensor in the
        active configuration.
    """

    if (
        instructions.sensor_configuration is None
        and is_inline_sensor_config_required()
    ):
        raise HTTP_422_INLINE_SENSOR_CONFIG_REQUIRED_EXCEPTION

    sensor_configuration = get_active_sensor_configuration(
        instructions.sensor_configuration
    )
    logger.debug("Using sensor configuration: %s", sensor_configuration)

    channels = sensor_configuration.channels

    return ResolvedMeasurementChannels(
        first=resolve_channel(instructions.first.sensor_id, channels),
        second=resolve_channel(instructions.second.sensor_id, channels),
        third=resolve_channel(instructions.third.sensor_id, channels),
    )


# pylint: disable=too-few-public-methods


class SensorDescription(IsDescription):
    """Description of HDF5 sensor table"""

    name = StringCol(itemsize=100)  # Fixed-size string for the name
    sensor_type = StringCol(
        itemsize=100
    )  # Fixed-size string for the sensor type
    sensor_id = StringCol(itemsize=100)  # Fixed-size string for the sensor ID
    channel_number = UInt8Col()  # Physical channel this sensor was read from
    unit = StringCol(itemsize=10)  # Fixed-size string for the unit
    dimension = StringCol(itemsize=100)  # Fixed-size string for the unit
    phys_min = Float32Col()  # Float for physical minimum
    phys_max = Float32Col()  # Float for physical maximum
    volt_min = Float32Col()  # Float for voltage minimum
    volt_max = Float32Col()  # Float for voltage maximum
    scaling_factor = Float32Col()  # Float for scaling factor; Currently unused
    offset = Float32Col()  # Float for offset


# pylint: enable=too-few-public-methods


def add_sensor_data_to_storage(
    storage: StorageData, resolved_channels: List[ResolvedChannel]
) -> None:
    """Add sensor and channel data to storage object"""

    if not storage.hdf:
        logger.error("Could not add sensors to storage; no storage found.")
        return

    table = storage.hdf.create_table(
        storage.hdf.root,
        name="sensors",
        description=SensorDescription,
        title="Sensor Data",
    )
    count = 0
    for resolved_channel in resolved_channels:
        sensor = resolved_channel.sensor
        if sensor is None:
            continue
        row = table.row
        row["name"] = sensor.name
        row["sensor_type"] = sensor.sensor_type if sensor.sensor_type else ""
        row["sensor_id"] = sensor.sensor_id
        row["channel_number"] = resolved_channel.channel_number
        row["unit"] = sensor.unit.encode()
        row["dimension"] = sensor.dimension.encode()
        row["phys_min"] = sensor.phys_min
        row["phys_max"] = sensor.phys_max
        row["volt_min"] = sensor.volt_min
        row["volt_max"] = sensor.volt_max
        row["scaling_factor"] = sensor.scaling_factor
        row["offset"] = sensor.offset
        row.append()
        count += 1

    logger.info("Added %s sensors to the HDF5 file.", count)


def read_and_parse_trident_config(file_path: str) -> CloudConfig:
    """Read Trident configuration file"""

    logger.info("Trying to read dataspace config file: %s", file_path)
    if not path.exists(file_path):
        raise FileNotFoundError(
            f"Dataspace config file not found: {file_path}"
        )

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            payload = yaml.safe_load(file)
    except Exception as e:
        raise Exception(  # pylint: disable=broad-exception-raised
            f"Error parsing dataspace config file: {file_path}"
        ) from e

    errors = validate_dataspace_payload(payload)

    if errors:
        raise ValueError("|".join(errors))

    data = payload.get("connection")
    if bool(data.get("enabled", False)):
        logger.info("Found dataspace config: %s@%s", str(data["username"]), str(data["domain"]))

    return CloudConfig(
        protocol=str(data["protocol"]).strip(),
        domain=str(data["domain"]).strip(),
        base_path=str(data["base_path"]).lstrip("/").strip(),
        service=f"{data['protocol']}://{data['domain']}/{data['base_path']}",
        username=str(data["username"]),
        password=str(data["password"]),
        default_bucket=str(data["bucket"]),
        enabled=bool(data["enabled"]),
        manage_assets_path=data["manage_assets_path"] if "manage_assets_path" in data else None,
        virtual_group_root=data["virtual_group_root"] if "virtual_group_root" in data else None,
        connector=data["connector"]
    )


# pylint: disable=too-few-public-methods


class MeasurementSensorInfo:
    """Sensor information for measurement"""

    first_channel_sensor: Sensor | None
    second_channel_sensor: Sensor | None
    third_channel_sensor: Sensor | None
    voltage_scaling: float

    def __init__(
        self, resolved_channels: ResolvedMeasurementChannels, adc: ADCValues
    ):
        super().__init__()
        self.first_channel_sensor = resolved_channels.first.sensor
        self.second_channel_sensor = resolved_channels.second.sensor
        self.third_channel_sensor = resolved_channels.third.sensor
        assert isinstance(adc.reference_voltage, float)
        self.voltage_scaling = get_voltage_from_raw(adc.reference_voltage)

    def get_values(self):
        """Return sensors for channels and voltage scaling"""

        return (
            self.first_channel_sensor,
            self.second_channel_sensor,
            self.third_channel_sensor,
            self.voltage_scaling,
        )


# pylint: enable=too-few-public-methods


def get_node_names(hdf5_file_handle: tables.File) -> list[str]:
    """Get name of HDF5 nodes"""

    nodes = hdf5_file_handle.list_nodes("/")
    return [
        node._v_pathname for node in nodes  # pylint: disable=protected-access
    ]


def get_picture_node_names(hdf5_file_handle: tables.File) -> list[str]:
    """Get name of nodes that contain picture data"""

    names = get_node_names(hdf5_file_handle)
    return [name for name in names if "pictures" in name]


def parse_json_if_possible(val):
    """
    If val is a str or bytes containing JSON, return the deserialized object.
    Otherwise, return val unchanged.
    """
    # Only attempt on str/bytes
    if isinstance(val, (bytes, bytearray)):
        try:
            text = val.decode("utf-8")
        except UnicodeDecodeError:
            return val
    elif isinstance(val, str):
        text = val
    else:
        return val

    # Try parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return val


# pylint: disable=protected-access


def node_to_dict(node):
    """Convert HDF5 metadata node to dictionary"""

    info = HDF5NodeInfo(
        name=node._v_name,
        path=node._v_pathname,
        type=node.__class__.__name__,
        attributes={},
    )

    for key in node._v_attrs._f_list(attrset="all"):
        raw = node._v_attrs[key]
        # first coerce numpy‐types to Python
        if hasattr(raw, "tolist"):
            pyval = raw.tolist()
        elif hasattr(raw, "item"):
            pyval = raw.item()
        else:
            pyval = raw
        # then parse JSON if it is a JSON string
        info.attributes[key] = parse_json_if_possible(pyval)

    return info


# pylint: enable=protected-access


def get_embedded_file_infos(
    file_handle: tables.File,
) -> list[EmbeddedFileInfo]:
    """Get embedded file descriptors from an HDF5 file"""

    try:
        embedded_group = file_handle.get_node("/embedded_files")
    except NoSuchNodeError:
        return []

    embedded_files: list[EmbeddedFileInfo] = []
    for node in file_handle.list_nodes(embedded_group):
        size = getattr(node.attrs, "size", None)
        if size is None:
            raw = node.read()
            size = len(raw if isinstance(raw, bytes) else raw.tobytes())
        embedded_files.append(
            EmbeddedFileInfo(
                dataset_name=node.name,
                original_name=getattr(node.attrs, "original_name", node.name),
                mime=getattr(
                    node.attrs, "mime", "application/octet-stream"
                ),
                size=size,
                download_path="",
            )
        )

    return embedded_files


# pylint: disable=too-many-locals


def get_file_data(
        file_path: str,
) -> ParsedHDF5FileContent:
    """Get HDF5 measurement data"""

    with tables.open_file(file_path, mode="r") as file_handle:

        picture_node_names = get_picture_node_names(file_handle)
        pictures: dict[str, list[str]] = {}
        embedded_files: list[EmbeddedFileInfo] = []
        for node_name in picture_node_names:
            node = file_handle.get_node(node_name)
            assert isinstance(node, tables.Array)
            pictures[node_name.removeprefix("/")] = [
                img.decode("utf-8") for img in node.read().tolist()
            ]

        embedded_files = get_embedded_file_infos(file_handle)

        try:
            acceleration_data = file_handle.get_node("/acceleration")
            assert isinstance(acceleration_data, tables.Table)
            acceleration_df = pd.DataFrame.from_records(
                acceleration_data.read(), columns=acceleration_data.colnames
            )
            acceleration_meta = node_to_dict(acceleration_data)
        except NoSuchNodeError as error:
            raise AccelerationDataNotFoundError from error
        except AssertionError as error:
            raise HTTPException(
                status_code=500, detail="Acceleration data is not a table"
            ) from error

        # pylint: disable=consider-using-dict-items, consider-iterating-dictionary
        try:
            for pics_key in pictures.keys():

                obj: dict[int, str] = {}
                for index, pic in enumerate(pictures[pics_key]):
                    obj[index] = pic
                if MetadataPrefix.PRE in pics_key:
                    stripped_key = pics_key.split(f"{MetadataPrefix.PRE}__")[1]
                    acceleration_meta.attributes["pre_metadata"]["parameters"][
                        stripped_key
                    ] = obj
                elif MetadataPrefix.POST in pics_key:
                    stripped_key = pics_key.split(f"{MetadataPrefix.POST}__")[
                        1
                    ]
                    acceleration_meta.attributes["post_metadata"][
                        "parameters"
                    ][stripped_key] = obj
                else:
                    logger.error("Unknown picture key: %s", pics_key)
        except KeyError:
            pass
        except IndexError as error:
            raise HTTPException(
                status_code=500, detail="Picture data is not prefixed."
            ) from error

        # pylint: enable=consider-using-dict-items, consider-iterating-dictionary

        sensor_df = pd.DataFrame()
        try:
            sensor_data = file_handle.get_node("/sensors")
            assert isinstance(sensor_data, tables.Table)
            sensor_df = pd.DataFrame.from_records(
                sensor_data.read(), columns=sensor_data.colnames
            )
        except NoSuchNodeError:
            # No sensor data available; pass
            pass
        except AssertionError:
            # sensor data available, but not in the right shape
            pass

    return ParsedHDF5FileContent(
        acceleration_df=acceleration_df,
        sensor_df=sensor_df,
        acceleration_meta=acceleration_meta,
        pictures=pictures,
        embedded_files=embedded_files,
    )


# pylint: enable=too-many-locals


def ensure_dataframe_with_columns(df, required_columns) -> pd.DataFrame:
    """
    Ensures the object is a DataFrame and contains the required columns.

    Parameters:
        df: The object to check.
        required_columns: A list or set of column names that must be present.

    Returns:
        The DataFrame if it meets the requirements.

    Raises:
        TypeError: If the object is not a DataFrame.
        ValueError: If required columns are missing.
    """
    # Ensure the object is a DataFrame
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"Expected a pandas DataFrame, but got {type(df).__name__}"
        )

    # Check for required columns
    missing_columns = set(required_columns) - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {', '.join(missing_columns)}"
        )

    return df

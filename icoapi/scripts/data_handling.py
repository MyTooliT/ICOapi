import os
import sys
import textwrap
from os import PathLike, path, getcwd
from typing import List, Optional
import yaml
from mytoolit.measurement.storage import StorageData
from tables import Float32Col, IsDescription, StringCol

from icoapi.models.models import MeasurementInstructionChannel, MeasurementInstructions, Sensor, PCBSensorConfiguration
import logging

from icoapi.scripts.file_handling import ensure_folder_exists, get_sensors_file_path

logger = logging.getLogger(__name__)

def get_sensor_defaults() -> list[Sensor]:
    return [
        Sensor(name="Acceleration 100g", sensor_type="ADXL1001", sensor_id="acc100g_01", unit="g", dimension="Acceleration", phys_min=-100, phys_max=100, volt_min=0.33, volt_max=2.97),
        Sensor(name="Acceleration 40g Y", sensor_type="ADXL358C", sensor_id="acc40g_y", unit="g", dimension="Acceleration", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Acceleration 40g Z", sensor_type="ADXL358C", sensor_id="acc40g_z", unit="g", dimension="Acceleration", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Acceleration 40g X", sensor_type="ADXL358C", sensor_id="acc40g_x", unit="g", dimension="Acceleration", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Temperature", sensor_type="ADXL358C", sensor_id="temp_01", unit="°C", dimension="Temperature", phys_min=-40, phys_max=125, volt_min=0.772, volt_max=1.267),
        Sensor(name="Photodiode", sensor_type=None, sensor_id="photo_01", unit="-", dimension="Light", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 1", sensor_type=None, sensor_id="backpack_01", unit="/", dimension="Backpack", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 2", sensor_type=None, sensor_id="backpack_02", unit="/", dimension="Backpack", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 3", sensor_type=None, sensor_id="backpack_03", unit="/", dimension="Backpack", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Battery Voltage", sensor_type=None, sensor_id="vbat_01", unit="V", dimension="Voltage", phys_min=2.9, phys_max=4.2, volt_min=0.509, volt_max=0.737)
    ]

def get_sensor_configuration_defaults() -> list[dict]:
    return [
        {
            "configuration_id": "default",
            "configuration_name": "Default",
            "channels": {
              "1": { "sensor_id": "acc100g_01" },
              "2": { "sensor_id": "acc40g_y" },
              "3": { "sensor_id": "acc40g_z" },
              "4": { "sensor_id": "acc40g_x" },
              "5": { "sensor_id": "temp_01" },
              "6": { "sensor_id": "photo_01" },
              "7": { "sensor_id": "backpack_01" },
              "8": { "sensor_id": "backpack_02" },
              "9": { "sensor_id": "backpack_03" },
              "10": { "sensor_id": "vbat_01" }
            }
        }
    ]


asdf = """
        configuration_id: default
        configuration_name: Default
        channels:
          1: { sensor_id: acc100g_01 }
          2: { sensor_id: acc40g_y }
          3: { sensor_id: acc40g_z }
          4: { sensor_id: acc40g_x }
          5: { sensor_id: temp_01 }
          6: { sensor_id: photo_01 }
          7: { sensor_id: backpack_01 }
          8: { sensor_id: backpack_02 }
          9: { sensor_id: backpack_03 }
          10: { sensor_id: vbat_01 }
        """

def get_voltage_from_raw(v_ref: float) -> float:
    """Get the conversion factor from bit value to voltage"""
    return v_ref / 2**16

def get_sensors() -> list[Sensor]:
    file_path = get_sensors_file_path()
    try:
        sensors, _, _ = read_and_parse_sensor_data(file_path)
        return sensors
    except FileNotFoundError:
        sensor_defaults = get_sensor_defaults()
        configuration_defaults = get_sensor_configuration_defaults()
        write_sensor_defaults(sensor_defaults, configuration_defaults, file_path)
        return sensor_defaults


def read_and_parse_sensor_data(file_path: str|PathLike) -> tuple[list[Sensor], list[PCBSensorConfiguration], str]:
    try:
        with open(file_path, "r") as file:
            data = yaml.safe_load(file)
            sensors = [Sensor(**sensor) for sensor in data['sensors']]
            sensor_map: dict[str, Sensor] = {s.sensor_id: s for s in sensors}
            logger.info(f"Found {len(sensors)} sensors in {file_path}")

            configs: list[PCBSensorConfiguration] = []
            for cfg in data.get("sensor_configurations", []):
                chan_map: dict[int, Sensor] = {}
                for ch_num, ch_entry in cfg.get("channels", {}).items():
                    sid = ch_entry.get("sensor_id")
                    if sid not in sensor_map:
                        raise ValueError(f"Channel {ch_num} references unknown sensor_id '{sid}'")
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
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find sensor.yaml file at {file_path}")

def get_sensor_config_data() -> tuple[list[Sensor], list[PCBSensorConfiguration], str]:
    file_path = get_sensors_file_path()
    try:
        return read_and_parse_sensor_data(file_path)

    except FileNotFoundError:
        sensor_default = get_sensor_defaults()
        configuration_defaults = get_sensor_configuration_defaults()
        write_sensor_defaults(sensor_default, configuration_defaults, file_path)
        return read_and_parse_sensor_data(file_path)


def write_sensor_defaults(sensors: list[Sensor], configuration: list[dict], file_path: str | PathLike):
    ensure_folder_exists(os.path.dirname(file_path))
    with open(file_path, "w+") as file:
        default_data = {"sensors": [sensor.model_dump() for sensor in sensors]}
        yaml.safe_dump(default_data, file, sort_keys=False)
        yaml.safe_dump({"sensor_configurations": configuration}, file, sort_keys=False)
        logger.info(f"File not found. Created new sensor.yaml with {len(sensors)} default sensors and {len(configuration)} default sensor configurations.")


def find_sensor_by_id(sensors: List[Sensor], sensor_id: str) -> Optional[Sensor]:
    """
    Finds a sensor by its ID from the list of sensors.

    Args:
    - sensors (List[Sensor]): The list of Sensor objects.
    - sensor_id (str): The ID of the sensor to find.

    Returns:
    - Optional[Sensor]: The Sensor object with the matching ID, or None if not found.
    """
    for sensor in sensors:
        if sensor.sensor_id == sensor_id:
            logger.debug(f"Found sensor with ID {sensor.sensor_id}: {sensor.name} | k2: {sensor.scaling_factor} | d2: {sensor.offset}")
            return sensor
    return None


def get_sensor_for_channel(channel_instruction: MeasurementInstructionChannel) -> Optional[Sensor]:
    sensors = get_sensors()

    if channel_instruction.sensor_id:
        logger.debug(f"Got sensor id {channel_instruction.sensor_id} for channel number {channel_instruction.channel_number}")
        sensor = find_sensor_by_id(sensors, channel_instruction.sensor_id)
        if sensor:
            return sensor
        else:
            logger.error(f"Could not find sensor with ID {channel_instruction.sensor_id}.")

    logger.info(f"No sensor ID requested or not found for channel {channel_instruction.channel_number}. Taking defaults.")
    if channel_instruction.channel_number in range(1, 11):
        sensor = sensors[channel_instruction.channel_number - 1]
        logger.info(f"Default sensor for channel {channel_instruction.channel_number}: {sensor.name} | k2: {sensor.scaling_factor} | d2: {sensor.offset}")
        return sensor

    if channel_instruction.channel_number == 0:
        logger.info(f"Disabled channel; return None")
        return None

    logger.error(f"Could not get sensor for channel {channel_instruction.channel_number}. Interpreting as percentage.")
    return Sensor(name="Raw", sensor_type=None, sensor_id="raw_default_01", unit="-", phys_min=-100, phys_max=100, volt_min=0, volt_max=3.3, dimension="Raw")


class SensorDescription(IsDescription):
    """Description of HDF5 sensor table"""

    name = StringCol(itemsize=100)  # Fixed-size string for the name
    sensor_type = StringCol(itemsize=100)  # Fixed-size string for the sensor type
    sensor_id = StringCol(itemsize=100)  # Fixed-size string for the sensor ID
    unit = StringCol(itemsize=10)  # Fixed-size string for the unit
    dimension = StringCol(itemsize=100)  # Fixed-size string for the unit
    phys_min = Float32Col()  # Float for physical minimum
    phys_max = Float32Col()  # Float for physical maximum
    volt_min = Float32Col()  # Float for voltage minimum
    volt_max = Float32Col()  # Float for voltage maximum
    scaling_factor = Float32Col()  # Float for scaling factor
    offset = Float32Col()  # Float for offset

def add_sensor_data_to_storage(storage: StorageData, sensors: List[Sensor]) -> None:
    if not storage.hdf:
        logger.error(f"Could not add sensors to storage; no storage found.")
        return

    table = storage.hdf.create_table(
        storage.hdf.root,
        name="sensors",
        description=SensorDescription,
        title="Sensor Data"
    )
    count = 0
    for sensor in sensors:
        if sensor is None:
            continue
        row = table.row
        row['name'] = sensor.name
        row['sensor_type'] = sensor.sensor_type if sensor.sensor_type else ''
        row['sensor_id'] = sensor.sensor_id
        row['unit'] = sensor.unit.encode()
        row['dimension'] = sensor.dimension.encode()
        row['phys_min'] = sensor.phys_min
        row['phys_max'] = sensor.phys_max
        row['volt_min'] = sensor.volt_min
        row['volt_max'] = sensor.volt_max
        row['scaling_factor'] = sensor.scaling_factor
        row['offset'] = sensor.offset
        row.append()
        count += 1

    logger.info(f"Added {count} sensors to the HDF5 file.")



class MeasurementSensorInfo:
    first_channel_sensor: Sensor | None
    second_channel_sensor: Sensor | None
    third_channel_sensor: Sensor | None
    voltage_scaling: float

    def __init__(self, instructions: MeasurementInstructions):
        super().__init__()
        self.first_channel_sensor = get_sensor_for_channel(instructions.first)
        self.second_channel_sensor = get_sensor_for_channel(instructions.second)
        self.third_channel_sensor = get_sensor_for_channel(instructions.third)
        self.voltage_scaling = get_voltage_from_raw(instructions.adc.reference_voltage)

    def get_values(self):
        return (
            self.first_channel_sensor,
            self.second_channel_sensor,
            self.third_channel_sensor,
            self.voltage_scaling
        )
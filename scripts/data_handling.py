from os import path
from typing import List, Optional
import yaml
from mytoolit.measurement import Storage
from mytoolit.measurement.storage import StorageData
from pydantic import BaseModel
from tables import Float32Col, IsDescription, StringCol, UInt8Col

from models.models import MeasurementInstructionChannel, MeasurementInstructions, Sensor
import logging

from scripts.file_handling import ensure_folder_exists, get_measurement_dir

logger = logging.getLogger(__name__)

def get_storage_path():
    return path.join(get_measurement_dir(), "config", "local_storage.json")

def get_sensor_yaml_path():
    return path.join(path.join(get_measurement_dir(), "config"), "sensors.yaml")

def get_sensor_defaults() -> list[Sensor]:
    return [
        Sensor(name="Acceleration 100g", sensor_type="ADXL1001", sensor_id="acc100g_01", unit="g", phys_min=-100, phys_max=100, volt_min=0.33, volt_max=2.97),
        Sensor(name="Acceleration 40g Y", sensor_type="ADXL358C", sensor_id="acc40g_y", unit="g", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Acceleration 40g Z", sensor_type="ADXL358C", sensor_id="acc40g_z", unit="g", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Acceleration 40g X", sensor_type="ADXL358C", sensor_id="acc40g_x", unit="g", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Temperature", sensor_type="ADXL358C", sensor_id="temp_01", unit="°C", phys_min=-40, phys_max=125, volt_min=0.772, volt_max=1.267),
        Sensor(name="Photodiode", sensor_type=None, sensor_id="photo_01", unit="-", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 1", sensor_type=None, sensor_id="backpack_01", unit="/", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 2", sensor_type=None, sensor_id="backpack_02", unit="/", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack 3", sensor_type=None, sensor_id="backpack_03", unit="/", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Battery Voltage", sensor_type=None, sensor_id="vbat_01", unit="V", phys_min=2.9, phys_max=4.2, volt_min=0.509, volt_max=0.737)
    ]

def get_voltage_from_raw(v_ref: float) -> float:
    """Get the conversion factor from bit value to voltage"""
    return v_ref / 2**16

def get_sensors() -> list[Sensor]:
    config_dir=path.join(get_measurement_dir(), "config")
    file_path=get_sensor_yaml_path()
    ensure_folder_exists(config_dir)

    try:
        with open(file_path, "r") as file:
            data = yaml.safe_load(file)
            sensors = [Sensor(**sensor) for sensor in data['sensors']]
            logger.info(f"Found {len(sensors)} sensors in {file_path}")
            return sensors
    except FileNotFoundError:
        defaults = get_sensor_defaults()
        write_sensor_defaults(defaults)
        return defaults


def write_sensor_defaults(sensors: list[Sensor]):
    file_path = get_sensor_yaml_path()
    with open(file_path, "w") as file:
        default_data = {"sensors": [sensor.dict() for sensor in sensors]}
        yaml.dump(default_data, file)
        logger.info(f"File not found. Created new sensor.yaml with {len(sensors)} default sensors.")


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
    return Sensor(name="Raw", sensor_type=None, sensor_id="raw_default_01", unit="-", phys_min=-100, phys_max=100, volt_min=0, volt_max=3.3)


class SensorDescription(IsDescription):
    """Description of HDF5 sensor table"""

    name = StringCol(itemsize=100)  # Fixed-size string for the name
    sensor_type = StringCol(itemsize=100)  # Fixed-size string for the sensor type
    sensor_id = StringCol(itemsize=100)  # Fixed-size string for the sensor ID
    unit = StringCol(itemsize=10)  # Fixed-size string for the unit
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
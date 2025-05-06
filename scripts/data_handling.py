from os import path
from typing import List, Optional
import yaml
from models.models import MeasurementInstructionChannel, Sensor
import logging

from scripts.file_handling import ensure_folder_exists, get_measurement_dir

logger = logging.getLogger(__name__)

def get_voltage_from_raw(v_ref: float) -> float:
    """Get the conversion factor from bit value to voltage"""
    return v_ref / 2**16

def get_sensors() -> list[Sensor]:
    defaults = [
        Sensor(name="Acceleration 100g", sensor_type="ADXL1001", sensor_id="acc100g_01", unit="g", phys_min=-100, phys_max=100, volt_min=0.33, volt_max=2.97),
        Sensor(name="Acceleration 40g", sensor_type="ADXL358C", sensor_id="acc40g_01", unit="g", phys_min=-40, phys_max=40, volt_min=0.1, volt_max=1.7),
        Sensor(name="Temperature", sensor_type="ADXL358C", sensor_id="temp_01", unit="°C", phys_min=-440, phys_max=125, volt_min=0.772, volt_max=1.267),
        Sensor(name="Photodiode", sensor_type=None, sensor_id="photo_01", unit="-", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Backpack", sensor_type=None, sensor_id="backpack_01", unit="-", phys_min=0, phys_max=1, volt_min=0, volt_max=3.3),
        Sensor(name="Battery Voltage", sensor_type=None, sensor_id="vbat_01", unit="V", phys_min=2.9, phys_max=4.2, volt_min=0.509, volt_max=0.737)
    ]

    config_dir = path.join(get_measurement_dir(), "config")
    file_path=path.join(config_dir, "sensors.yaml")
    ensure_folder_exists(config_dir)

    try:
        with open(file_path, "r") as file:
            data = yaml.safe_load(file)
            sensors = [Sensor(**sensor) for sensor in data['sensors']]
            logger.info(f"Found {len(sensors)} sensors in {file_path}")
            return sensors
    except FileNotFoundError:
        with open(file_path, "w") as file:
            default_data = {"sensors": [sensor.dict() for sensor in defaults]}
            yaml.dump(default_data, file)
            logger.info(f"File not found. Created new sensor.yaml with {len(defaults)} default sensors.")
        return defaults


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
        return find_sensor_by_id(sensors, channel_instruction.sensor_id)

    logger.info(f"No sensor ID requested for channel {channel_instruction.channel_number}. Taking defaults.")
    sensor = Sensor(name="Raw", sensor_type=None, sensor_id="raw_default_01", unit="-", phys_min=-100, phys_max=100, volt_min=0, volt_max=3.3)
    match channel_instruction.channel_number:
        case 0:
            logger.info(f"Disabled channel; return default sensor.")
        case 1:
            sensor = sensors[0]
        case 2, 3, 4:
            sensor = sensors[1]
        case 5:
            sensor = sensors[2]
        case 6:
            sensor = sensors[3]
        case 7,8,9:
            sensor = sensors[4]
        case 10:
            sensor = sensors[5]
        case _:
            logger.error(f"Could not get sensor for channel {channel_instruction.channel_number}. Interpreting as percentage.")

    logger.info(f"Default sensor for channel {channel_instruction.channel_number}: {sensor.name} | k2: {sensor.scaling_factor} | d2: {sensor.offset}")
    return sensor

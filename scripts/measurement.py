from functools import partial
from mytoolit.can import Network, UnsupportedFeatureException
from mytoolit.can.adc import ADCConfiguration
from mytoolit.can.streaming import StreamingConfiguration
from mytoolit.measurement.sensor import SensorConfiguration
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g
from mytoolit.measurement import convert_raw_to_g
from icolyzer import iftlibrary

from models.models import WSMetaData


async def setup_adc(network: Network, instructions: WSMetaData) -> None:
    """
    Write ADC configuration to holder. Currently only supports default values.

    :param network: CAN Network instance from API
    :param instructions: client instructions
    :return: None
    """

    adc_config = ADCConfiguration(
        prescaler=2,
        acquisition_time=8,
        oversampling_rate=64
    )
    await network.write_adc_configuration(**adc_config)
    print(f"Sample Rate: {adc_config.sample_rate()} Hz")


async def write_sensor_config_if_required(
    network: Network,
    sensor_configuration: SensorConfiguration
) -> None:
    """
    Write holder sensor configuration if required.
    :param network: CAN Network instance from API
    :param sensor_configuration: configuration of sensors from client
    """
    if sensor_configuration.requires_channel_configuration_support():
        try:
            await network.write_sensor_configuration(**sensor_configuration)
        except UnsupportedFeatureException as exception:
            raise UnsupportedFeatureException(
                f"Sensor channel configuration “{sensor_configuration}” is "
                f"not supported by the sensor node"
            ) from exception


async def get_conversion_function(network: Network) -> partial:
    """
    Obtain raw to actual value conversion function from network
    :param network: CAN Network instance from API
    :return: conversion function as <partial>
    """
    sensor_range = await read_acceleration_sensor_range_in_g(network)
    return partial(convert_raw_to_g, max_value=sensor_range)


def get_measurement_indices(streaming_configuration: StreamingConfiguration) -> list[int]:
    """
    Obtain ordered indices from streaming configuration
    :param streaming_configuration: Selected / Activated channels for measurement
    :return: list containing [first_index, second_index, third_index]
    """
    first_index = 0
    second_index = 1 if streaming_configuration.first else 0
    third_index = (second_index + 1) if streaming_configuration.second else (first_index + 1)

    return [first_index, second_index, third_index]


def create_objects(timestamps, ift_vals, first_timestamp) -> list[dict[str, float]]:
    if len(timestamps) != len(ift_vals):
        raise ValueError("Both arrays must have the same length")

    result = [{'x': t, 'y': i} for t, i in zip(delta_from_timestamps(timestamps, first_timestamp), ift_vals)]
    return result


def delta_from_timestamps(timestamps: list[float], first_timestamp: float) -> list[float]:
    ret: list[float] = []
    for i in range(len(timestamps) - 1):
        ret.append(timestamps[i] - first_timestamp)

    return ret


def maybe_get_ift_value(samples: list[float], sample_frequency=9524/3, window_length=0.15) -> list[float] | None:
    """
    Try to get IFT_value calculated
    :param samples: list of samples for calculation
    :param sample_frequency: sample frequency of sample list
    :param window_length: window for sliding calculation
    :return: IFT value list or None if not calculatable
    """
    if (
            (len(samples) <= 0.6 * sample_frequency) or
            (sample_frequency < 200) or
            (window_length < 0.005) or
            (window_length > 1)
    ):
        return None
    return iftlibrary.ift_value(samples, sample_frequency, window_length)
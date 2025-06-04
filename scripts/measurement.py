import asyncio
import json
import os
import time
from functools import partial
from pathlib import Path
import logging
from typing import List

from mytoolit.can import Network, UnsupportedFeatureException
from mytoolit.can.adc import ADCConfiguration
from mytoolit.can.streaming import StreamingConfiguration, StreamingData, StreamingTimeoutError
from mytoolit.measurement.sensor import SensorConfiguration
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g
from mytoolit.measurement import Storage, convert_raw_to_g
from icolyzer import iftlibrary
from starlette.websockets import WebSocketDisconnect

from models.autogen.metadata import METADATA_VERSION
from scripts.data_handling import add_sensor_data_to_storage, get_voltage_from_raw, get_sensor_for_channel, get_sensors
from scripts.file_handling import get_measurement_dir
from models.globals import MeasurementState
from models.models import DataValueModel, MeasurementInstructions

logger = logging.getLogger(__name__)

async def setup_adc(network: Network, instructions: MeasurementInstructions) -> int:
    """
    Write ADC configuration to the holder. Currently only supports default values.

    :param network: CAN Network instance from API
    :param instructions: client instructions
    :return: None
    """

    adc_config = ADCConfiguration(
        prescaler=instructions.adc.prescaler if instructions.adc.prescaler else 2,
        acquisition_time=instructions.adc.acquisition_time if instructions.adc.acquisition_time else 8,
        oversampling_rate=instructions.adc.oversampling_rate if instructions.adc.oversampling_rate else 64,
        reference_voltage=instructions.adc.reference_voltage if instructions.adc.reference_voltage else 3.3,
    )
    await network.write_adc_configuration(**adc_config)

    sample_rate = adc_config.sample_rate()
    logger.info(f"Sample Rate: {sample_rate} Hz")

    return sample_rate


async def write_sensor_config_if_required(
    network: Network,
    sensor_configuration: SensorConfiguration
) -> None:
    """
    Write holder sensor configuration if required.
    :param network: CAN Network instance from API
    :param sensor_configuration: configuration of sensors from the client
    """
    if sensor_configuration.requires_channel_configuration_support():
        try:
            await network.write_sensor_configuration(sensor_configuration)
        except UnsupportedFeatureException as exception:
            raise UnsupportedFeatureException(
                f"Sensor channel configuration “{sensor_configuration}” is "
                f"not supported by the sensor node"
            ) from exception


async def get_conversion_function(network: Network) -> partial:
    """
    Get raw to actual value conversion function from network
    :param network: CAN Network instance from API
    :return: conversion function as <partial>
    """
    sensor_range = await read_acceleration_sensor_range_in_g(network)
    return partial(convert_raw_to_g, max_value=sensor_range)


def get_measurement_indices(streaming_configuration: StreamingConfiguration) -> list[int]:
    """
    Obtain ordered indices from streaming configuration
    :param streaming_configuration: Selected / Activated channels for the measurement
    :return: list containing [first_index, second_index, third_index]
    """
    first_index = 0
    second_index = 1 if streaming_configuration.first else 0
    third_index = (second_index + 1) if streaming_configuration.second else (first_index + 1)

    return [first_index, second_index, third_index]


def create_objects(timestamps, ift_vals) -> list[dict[str, float]]:
    if len(timestamps) != len(ift_vals):
        raise ValueError("Both arrays must have the same length")

    result = [{'x': t, 'y': i} for t, i in zip(timestamps, ift_vals)]
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
    :param sample_frequency: sample frequency of the sample list
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


async def send_ift_values(
        timestamps: list[float],
        values: list[float],
        instructions: MeasurementInstructions,
        measurement_state: MeasurementState
) -> None:
    logger.debug(f"IFT value computation requested for channel: <{instructions.ift_channel}>")

    ift_values = maybe_get_ift_value(values, window_length=instructions.ift_window_width / 1000)

    ift_wrapped: DataValueModel = DataValueModel(
        first=None,
        second=None,
        third=None,
        ift=create_objects(timestamps, ift_values),
        counter=1,
        timestamp=1,
        dataloss=None
    )
    for client in measurement_state.clients:
        try:
            await client.send_json([ift_wrapped.model_dump()])
            logger.debug(f"Sent IFT value to client <{client.client}>")
        except RuntimeError:
            logger.warning("Client must be disconnected, passing")


async def run_measurement(
        network: Network,
        instructions: MeasurementInstructions,
        measurement_state: MeasurementState
) -> None:
    # Write ADC configuration to the holder
    sample_rate = await setup_adc(network, instructions)

    # Create a SensorConfiguration and a StreamingConfiguration object
    # `SensorConfiguration` sets which sensor channels map to the measurement channels, e.g., that 'first' -> channel 3.
    # `StreamingConfiguration sets the active channels based on if the channel number is > 0.`
    sensor_configuration = SensorConfiguration(instructions.first.channel_number, instructions.second.channel_number, instructions.third.channel_number)
    streaming_configuration: StreamingConfiguration = StreamingConfiguration(**{
        key: bool(value) for key, value in sensor_configuration.items()
    })

    # Write sensor configuration to the holder if possible / necessary.
    await write_sensor_config_if_required(network, sensor_configuration)

    # NOTE: The array data.values only contains the activated channels. This means we need to compute the
    #       index at which each channel is located. This may not be pretty, but it works.
    [first_index, second_index, third_index] = get_measurement_indices(streaming_configuration)

    timestamps: list[float] = []
    ift_relevant_channel: list[float] = []
    ift_sent: bool = False
    start_time: float = 0

    try:
        async with network.open_data_stream(streaming_configuration) as stream:

            with Storage(Path(f'{get_measurement_dir()}/{measurement_state.name}.hdf5'), streaming_configuration) as storage:

                logger.info(f"Measurement started for file <{get_measurement_dir()}/{measurement_state.name}.hdf5>")

                storage.add_acceleration_meta(
                    "conversion", "true"
                )

                storage.add_acceleration_meta("adc_reference_voltage", f"{instructions.adc.reference_voltage}")

                if instructions.meta is not None:
                    meta_dump = json.dumps(instructions.meta.__dict__, default=lambda o: o.__dict__)
                    storage.add_acceleration_meta(
                        "metadata", meta_dump
                    )
                    storage.add_acceleration_meta(
                        "metadata_version", METADATA_VERSION
                    )
                    logger.debug("Added measurement metadata")


                counter: int = 0
                data_collected_for_send: list = []

                voltage_scaling = get_voltage_from_raw(instructions.adc.reference_voltage)
                logger.info(f"ADC reference voltage of {instructions.adc.reference_voltage} results in factor voltage_scaling: {voltage_scaling}")

                first_channel_sensor = get_sensor_for_channel(instructions.first)
                second_channel_sensor = get_sensor_for_channel(instructions.second)
                third_channel_sensor = get_sensor_for_channel(instructions.third)

                add_sensor_data_to_storage(storage, [first_channel_sensor, second_channel_sensor, third_channel_sensor])

                if streaming_configuration.first:
                    if not streaming_configuration.second and not streaming_configuration.third:
                        logger.info(f"Running in single channel mode with sensor {sensor_configuration.first}.")

                    elif streaming_configuration.second and not streaming_configuration.third:
                        logger.info(f"Running in dual channel mode with channels 1 (Sensor {sensor_configuration.first}) and 2 (Sensor {sensor_configuration.second}).")

                    elif not streaming_configuration.second and streaming_configuration.third:
                        logger.info(f"Running in dual channel mode with channels 1 (Sensor {sensor_configuration.first}) and 3 (Sensor {sensor_configuration.third}).")

                    else:
                        logger.info(f"Running in triple channel mode with sensors {sensor_configuration.first}, {sensor_configuration.second} and {sensor_configuration.third}.")

                async for data, _ in stream:
                    if start_time == 0:
                        start_time = data.timestamp
                        logger.debug(f"Set measurement start time to {start_time}")
                    # Convert timestamp to seconds since measurement start -> taking a step out of the client's work
                    data.timestamp = (data.timestamp - start_time)
                    timestamps.append(data.timestamp)

                    data_to_send = DataValueModel(
                        first=None,
                        second=None,
                        third=None,
                        ift=None,
                        counter=data.counter,
                        timestamp=data.timestamp,
                        dataloss=None
                    )

                    if streaming_configuration.first:
                        if not streaming_configuration.second and not streaming_configuration.third:

                            def convert_single(val: float) -> float:
                                volts = val * voltage_scaling
                                return first_channel_sensor.convert_to_phys(volts)

                            data.apply(convert_single)
                            data_to_send.first = data.values[0]

                        elif streaming_configuration.second and not streaming_configuration.third:
                            data.values = [
                                first_channel_sensor.convert_to_phys(data.values[0] * voltage_scaling),
                                second_channel_sensor.convert_to_phys(data.values[1] * voltage_scaling),
                            ]
                            data_to_send.first = data.values[0]
                            data_to_send.second = data.values[1]

                        elif not streaming_configuration.second and streaming_configuration.third:
                            data.values = [
                                first_channel_sensor.convert_to_phys(data.values[0] * voltage_scaling),
                                third_channel_sensor.convert_to_phys(data.values[1] * voltage_scaling),
                            ]
                            data_to_send.first = data.values[0]
                            data_to_send.third = data.values[1]

                        else:
                            data.values = [
                                first_channel_sensor.convert_to_phys(data.values[0] * voltage_scaling),
                                second_channel_sensor.convert_to_phys(data.values[1] * voltage_scaling),
                                third_channel_sensor.convert_to_phys(data.values[2] * voltage_scaling),
                            ]
                            data_to_send.first = data.values[0]
                            data_to_send.second = data.values[1]
                            data_to_send.third = data.values[2]

                    if instructions.ift_requested:
                        match instructions.ift_channel:
                            case "first":
                                ift_relevant_channel.append(data.values[first_index])
                            case "second":
                                ift_relevant_channel.append(data.values[second_index])
                            case "third":
                                ift_relevant_channel.append(data.values[third_index])

                    storage.add_streaming_data(data)


                    if counter >= (sample_rate // int(os.getenv("WEBSOCKET_UPDATE_RATE", 60))):
                        for client in measurement_state.clients:
                            try:
                                await client.send_json(data_collected_for_send)
                            except RuntimeError:
                                logger.warning(f"Failed to send data to client <{client.client}>")
                        data_collected_for_send.clear()
                        counter = 0
                    else:
                        data_collected_for_send.append(data_to_send.model_dump())
                        counter += 1

                    # Exit condition
                    if timestamps[0] is None:
                        logger.warning(f"Exit condition in first loop hit")
                        continue

                    # Exit condition
                    if instructions.time is not None:
                        if data.timestamp - timestamps[0] >= instructions.time:
                            logger.info(f"Timeout reached at with current being <{data.timestamp}> and first entry being {timestamps[0]}s")
                            break

                # Send dataloss
                for client in measurement_state.clients:
                    try:
                        await client.send_json([DataValueModel(
                            first=None,
                            second=None,
                            third=None,
                            ift=None,
                            counter=None,
                            timestamp=None,
                            dataloss=storage.dataloss()
                        ).model_dump()])
                    except RuntimeError:
                        logger.warning("Client must be disconnected, passing")

                # Send IFT value values at once after the measurement is finished.
                if instructions.ift_requested:
                    await send_ift_values(timestamps, ift_relevant_channel, instructions, measurement_state)
                    ift_sent = True

    except StreamingTimeoutError as e:
        logger.debug("Stream timeout error")
        for client in measurement_state.clients:
            await client.send_json({"error": True, "type": type(e).__name__, "message": str(e)})
        measurement_state.clients.clear()
    except asyncio.CancelledError as e:
        logger.debug(f"Measurement cancelled. IFT: requested <{instructions.ift_requested}> | already sent: <{ift_sent}>")
        if instructions.ift_requested and not ift_sent:
            await send_ift_values(timestamps, ift_relevant_channel, instructions, measurement_state)
        raise asyncio.CancelledError from e
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("Unhandled measurement error - stacktrace below")
        logger.error(e)
    finally:
        clients = len(measurement_state.clients)
        for client in measurement_state.clients:
            await client.close()
        logger.info(f"Ended measurement and cleared {clients} clients")
        await measurement_state.reset()

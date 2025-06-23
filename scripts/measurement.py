import asyncio
import json
import os
from functools import partial
from pathlib import Path
import logging

import mytoolit.can.network
from mytoolit.can import Network, UnsupportedFeatureException
from mytoolit.can.adc import ADCConfiguration
from mytoolit.can.streaming import StreamingConfiguration, StreamingData, StreamingTimeoutError
from mytoolit.measurement.sensor import SensorConfiguration
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g
from mytoolit.measurement import convert_raw_to_g
from mytoolit.measurement.storage import StorageData, Storage
from icolyzer import iftlibrary
from starlette.websockets import WebSocketDisconnect

from scripts.data_handling import add_sensor_data_to_storage, MeasurementSensorInfo
from scripts.file_handling import get_measurement_dir
from models.globals import MeasurementState
from models.models import DataValueModel, MeasurementInstructions, Metadata

logger = logging.getLogger(__name__)

async def setup_adc(network: Network, instructions: MeasurementInstructions) -> int:
    """
    Write ADC configuration to the holder.

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

    try:
        await network.write_adc_configuration(**adc_config)
    except mytoolit.can.network.NoResponseError:
        logger.warning("No response from CAN bus - ADC configuration not written")

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


def write_pre_metadata(instructions: MeasurementInstructions, storage: StorageData) -> None:
    if instructions.meta is None:
        logger.info("No pre-measurement metadata provided")
        return

    storage.add_acceleration_meta(
        "metadata_version", instructions.meta.version
    )
    storage.add_acceleration_meta(
        "metadata_profile", instructions.meta.profile
    )
    meta_dump = json.dumps(instructions.meta.__dict__, default=lambda o: o.__dict__)
    storage.add_acceleration_meta(
        "pre_metadata", meta_dump
    )
    logger.info("Added pre-measurement metadata")


def write_post_metadata(meta: Metadata, storage: StorageData) -> None:
    if meta is None:
        logger.info("No post-measurement metadata provided")
        return

    if meta.parameters and "pictures" in meta.parameters:
        for key, value in meta.parameters["pictures"].items():
            stripped_key = "pic_" + key.split(".")[0] if "." in key else key
            logger.info(f"Adding picture {stripped_key} to storage")
            storage.hdf.create_array(storage.hdf.root, stripped_key, value.encode('utf-8'))
        del meta.parameters["pictures"]

    meta_dump = json.dumps(meta.__dict__, default=lambda o: o.__dict__)
    storage.add_acceleration_meta(
        "post_metadata", meta_dump
    )
    logger.info("Added post-measurement metadata")



def get_sendable_data_and_apply_conversion(streaming_configuration: StreamingConfiguration, sensor_info: MeasurementSensorInfo, data: StreamingData) -> DataValueModel:
    first_channel_sensor, second_channel_sensor, third_channel_sensor, voltage_scaling = sensor_info.get_values()

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

    return data_to_send

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
    measurement_file_path = Path(f'{get_measurement_dir()}/{measurement_state.name}.hdf5')
    try:
        with Storage(measurement_file_path, streaming_configuration) as storage:

            logger.info(f"Opened measurement file: <{measurement_file_path}> for writing")

            storage.add_acceleration_meta("conversion", "true")
            storage.add_acceleration_meta("adc_reference_voltage", f"{instructions.adc.reference_voltage}")
            write_pre_metadata(instructions, storage)

            async with network.open_data_stream(streaming_configuration) as stream:

                logger.info(f"Opened measurement stream: <{measurement_file_path}>")

                counter: int = 0
                data_collected_for_send: list = []

                sensor_info = MeasurementSensorInfo(instructions)
                first_channel_sensor, second_channel_sensor, third_channel_sensor, voltage_scaling = sensor_info.get_values()
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

                    # Convert timestamp to seconds since measurement start
                    data.timestamp = (data.timestamp - start_time)

                    # Save values required for future calculations
                    timestamps.append(data.timestamp)
                    if instructions.ift_requested:
                        match instructions.ift_channel:
                            case "first":
                                ift_relevant_channel.append(data.values[first_index])
                            case "second":
                                ift_relevant_channel.append(data.values[second_index])
                            case "third":
                                ift_relevant_channel.append(data.values[third_index])


                    data_to_send = get_sendable_data_and_apply_conversion(streaming_configuration, sensor_info, data)
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

                    # Skip exit conditions on the first iteration
                    if timestamps[0] is None:
                        continue

                    # Exit conditions
                    if instructions.time is not None:
                        if data.timestamp - timestamps[0] >= instructions.time:
                            logger.info(f"Timeout reached at with current being <{data.timestamp}> and first entry being {timestamps[0]}s")
                            break
                    elif measurement_state.stop_flag:
                        logger.info(f"Stop flag set - stopping measurement")
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

                if measurement_state.wait_for_post_meta:
                    logger.info("Waiting for post-measurement metadata")
                    while measurement_state.post_meta is None:
                        await asyncio.sleep(1)
                    logger.info("Received post-measurement metadata")
                    write_post_metadata(measurement_state.post_meta, storage)


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

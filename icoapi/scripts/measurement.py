import asyncio
import json
import os
from pathlib import Path
import logging
import numpy as np

import mytoolit.can.network
import tables.exceptions
from mytoolit.can import Network, UnsupportedFeatureException
from mytoolit.can.adc import ADCConfiguration
from mytoolit.can.streaming import StreamingConfiguration, StreamingData, StreamingTimeoutError
from mytoolit.measurement.sensor import SensorConfiguration
from mytoolit.measurement.storage import StorageData, Storage
from icolyzer import iftlibrary
from starlette.websockets import WebSocketDisconnect

from icoapi.scripts.data_handling import add_sensor_data_to_storage, MeasurementSensorInfo
from icoapi.scripts.file_handling import get_measurement_dir
from icoapi.models.globals import GeneralMessenger, MeasurementState
from icoapi.models.models import DataValueModel, MeasurementInstructions, Metadata, MetadataPrefix
from icoapi.scripts.sth_scripts import disconnect_sth_devices

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


def create_objects(timestamps: list[float], ift_vals: list[float]) -> list[dict[str, float]]:
    """
    Assembles the ift values and timestamps into a list of objects.
    :param timestamps: List of timestamps
    :param ift_vals: List of ift values
    :return: List of objects containing the timestamps and ift values.
    :raises: ValueError if the lists are not of the same length.
    """
    if len(timestamps) != len(ift_vals):
        raise ValueError("Both arrays must have the same length")

    result = [{'x': t, 'y': i} for t, i in zip(timestamps, ift_vals)]
    return result


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

    freq = ADCConfiguration(
        prescaler=instructions.adc.prescaler if instructions.adc.prescaler else 2,
        acquisition_time=instructions.adc.acquisition_time if instructions.adc.acquisition_time else 8,
        oversampling_rate=instructions.adc.oversampling_rate if instructions.adc.oversampling_rate else 64,
        reference_voltage=instructions.adc.reference_voltage if instructions.adc.reference_voltage else 3.3,
    ).sample_rate()

    ift_values = maybe_get_ift_value(values, sample_frequency=freq, window_length=instructions.ift_window_width / 1000)

    if ift_values is None:
        logger.info(f"No IFT value could be calculated with window length {instructions.ift_window_width}ms, {len(timestamps)} timestamps and {len(values)} values.")
        return

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


def write_metadata(prefix: MetadataPrefix, metadata: Metadata, storage: StorageData) -> None:
    picture_parameters = find_picture_parameters(metadata)
    if picture_parameters and len(picture_parameters) > 0:
        write_and_remove_picture_metadata(prefix, picture_parameters, metadata, storage)

    meta_dump = json.dumps(metadata.__dict__, default=lambda o: o.__dict__)
    storage.add_acceleration_meta(
        f"{prefix}_metadata", meta_dump
    )
    logger.info(f"Added {prefix}-measurement metadata")


def find_picture_parameters(meta: Metadata) -> list[str]:
    picture_parameters = []
    if meta.parameters:
        for key, value in meta.parameters.items():
            if "picture" in key:
                picture_parameters.append(key)
    return picture_parameters


def write_and_remove_picture_metadata(prefix: MetadataPrefix, picture_parameters: list[str], meta: Metadata, storage: StorageData):
    for param in picture_parameters:
        encoded_images: list[str] = []
        for encoded_image in meta.parameters[param].values():
            encoded_images.append(encoded_image.encode("utf-8"))

        max_string_length = max(len(s) for s in encoded_images)
        nd_array = np.array(encoded_images, dtype=f"S{max_string_length}")

        try:
            write_image_array(storage, f"{prefix}__{param}", nd_array, True)
            logger.info(f"Added {len(nd_array)} picture(s) for parameter {param} to storage")
            del meta.parameters[param]
        except ValueError:
            logger.warning(f"Could not add pictures for parameter {param} to storage")
        except tables.exceptions.NodeError:
            storage.hdf.remove_node("/", f"{prefix}__{param}", recursive=True)
            logger.info(f"Removed {param} image array from storage root node as it is being overwritten.")
            write_image_array(storage, f"{prefix}__{param}", nd_array, True)
            logger.info(f"Added {len(nd_array)} picture(s) for parameter {param} to storage")
            del meta.parameters[param]


def write_image_array(storage: StorageData, name: str, array: np.array, overwrite: bool):
    try:
        storage.hdf.create_array(storage.hdf.root, name, array)
    except tables.exceptions.NodeError:
        if overwrite:
            storage.hdf.remove_node("/acceleration", name, recursive=True)
            storage.hdf.create_array(storage.hdf.root, name, array)


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
        measurement_state: MeasurementState,
        general_messenger: GeneralMessenger
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
            if instructions.meta:
                write_metadata(MetadataPrefix.PRE, instructions.meta, storage)

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

                    if measurement_state.stop_flag:
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

            if instructions.disconnect_after_measurement:
                await disconnect_sth_devices(network)

            # Send IFT value values at once after the measurement is finished.
            if instructions.ift_requested:
                await send_ift_values(timestamps, ift_relevant_channel, instructions, measurement_state)
                ift_sent = True

            if measurement_state.wait_for_post_meta:
                logger.info("Waiting for post-measurement metadata")
                await general_messenger.send_post_meta_request()
                while measurement_state.post_meta is None:
                    await asyncio.sleep(1)
                logger.info("Received post-measurement metadata")
                await general_messenger.send_post_meta_completed()
                write_metadata(MetadataPrefix.POST, measurement_state.post_meta, storage)


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

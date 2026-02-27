"""Code for handling measurement data"""

import asyncio
import json
import logging
import os
from itertools import repeat
from pathlib import Path

from icolyzer import iftlibrary
from icostate import ICOsystem, State
from icotronic.can.error import UnsupportedFeatureException
from icotronic.can.sensor import SensorConfiguration
from icotronic.can.streaming import (
    StreamingConfiguration,
    StreamingData,
    StreamingTimeoutError,
)
from icotronic.measurement import Storage, StorageData
import numpy as np
from starlette.websockets import WebSocketDisconnect
import tables.exceptions

from icoapi.models.models import ADCValues
from icoapi.scripts.data_handling import (
    add_sensor_data_to_storage,
    MeasurementSensorInfo,
)
from icoapi.scripts.file_handling import get_measurement_dir
from icoapi.models.globals import GeneralMessenger, MeasurementState
from icoapi.models.models import (
    DataValueModel,
    MeasurementInstructions,
    Metadata,
    MetadataPrefix,
)
from icoapi.scripts.sth_scripts import disconnect_sth_devices

logger = logging.getLogger(__name__)


async def setup_adc(
    system: ICOsystem, instructions: MeasurementInstructions
) -> None:
    """
    Write ADC configuration to the holder.

    :param system: CAN Network instance from API
    :param instructions: client instructions
    """

    assert isinstance(instructions.adc, ADCValues)

    adc_config = instructions.adc.to_adc_configuration()

    await system.set_adc_configuration(adc_config)
    logger.debug("Set ADC configuration: %s", adc_config)

    sample_rate = adc_config.sample_rate()
    logger.info("Sample Rate: %s Hz", sample_rate)


async def write_sensor_config_if_required(
    system: ICOsystem, sensor_configuration: SensorConfiguration
) -> None:
    """
    Write holder sensor configuration if required.
    :param network: CAN Network instance from API
    :param sensor_configuration: configuration of sensors from the client
    """
    if sensor_configuration.requires_channel_configuration_support():
        try:
            await system.set_sensor_configuration(sensor_configuration)
        except UnsupportedFeatureException as exception:
            raise UnsupportedFeatureException(
                f"Sensor channel configuration “{sensor_configuration}” is "
                "not supported by the sensor node"
            ) from exception


def get_measurement_slices(
    streaming_configuration: StreamingConfiguration,
) -> list[slice]:
    """
    Get slices that select data of the first, second and third channel
    :param streaming_configuration: Selected / Activated channels for the measurement
    :return: list containing [first_slice, second_slice, third_slice]
    """
    empty = slice(0, 0)
    everything = slice(0, 3)

    if streaming_configuration.enabled_channels() == 1:
        return (
            [everything, empty, empty]
            if streaming_configuration.first
            else (
                [empty, everything, empty]
                if streaming_configuration.second
                else [empty, empty, everything]
            )
        )

    first = slice(0, 1)
    second = slice(1, 2)
    first_slice = first if streaming_configuration.first else empty
    second_slice = second if streaming_configuration.first else first
    third_slice = (
        slice(second_slice.start + 1, second_slice.stop + 1)
        if streaming_configuration.second
        else slice(first_slice.start + 1, first_slice.stop + 1)
    )

    return [first_slice, second_slice, third_slice]


def create_objects(
    timestamps: list[float], ift_vals: list[float]
) -> list[dict[str, float]]:
    """
    Assembles the ift values and timestamps into a list of objects.
    :param timestamps: List of timestamps
    :param ift_vals: List of ift values
    :return: List of objects containing the timestamps and ift values.
    :raises: ValueError if the lists are not of the same length.
    """
    if len(timestamps) != len(ift_vals):
        raise ValueError("Both arrays must have the same length")

    result = [{"x": t, "y": i} for t, i in zip(timestamps, ift_vals)]
    return result


def maybe_get_ift_value(
    samples: list[float], sample_frequency=9524 / 3, window_length=0.15
) -> list[float] | None:
    """
    Try to get IFT_value calculated
    :param samples: list of samples for calculation
    :param sample_frequency: sample frequency of the sample list
    :param window_length: window for sliding calculation
    :return: IFT value list or None if not calculable
    """
    if (
        (len(samples) <= 0.6 * sample_frequency)
        or (sample_frequency < 200)
        or (window_length < 0.005)
        or (window_length > 1)
    ):
        return None
    return iftlibrary.ift_value(samples, sample_frequency, window_length)


async def send_ift_values(
    timestamps: list[float],
    values: list[float],
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
) -> None:
    """Calculate and send IFT values"""

    logger.debug(
        "IFT value computation requested for channel: <%s>",
        instructions.ift_channel,
    )

    assert isinstance(instructions.adc, ADCValues)

    freq = instructions.adc.to_adc_configuration().sample_rate()

    ift_values = maybe_get_ift_value(
        values,
        sample_frequency=freq,
        window_length=instructions.ift_window_width / 1000,
    )

    if ift_values is None:
        logger.info(
            "No IFT value could be calculated with window length"
            " %sms, %s timestamps and %s values.",
            instructions.ift_window_width,
            len(timestamps),
            len(values),
        )
        return

    ift_wrapped: DataValueModel = DataValueModel(
        first=None,
        second=None,
        third=None,
        ift=create_objects(timestamps, ift_values),
        counter=1,
        timestamp=1,
        dataloss=None,
    )
    for client in measurement_state.clients:
        try:
            await client.send_json([ift_wrapped.model_dump()])
            logger.debug("Sent IFT value to client <%s>", client.client)
        except RuntimeError:
            logger.warning("Client must be disconnected, passing")


def write_metadata(
    prefix: MetadataPrefix, metadata: Metadata, storage: StorageData
) -> None:
    """Write metadata to storage object"""

    picture_parameters = find_picture_parameters(metadata)
    if picture_parameters and len(picture_parameters) > 0:
        write_and_remove_picture_metadata(
            prefix, picture_parameters, metadata, storage
        )

    meta_dump = json.dumps(metadata.__dict__, default=lambda o: o.__dict__)
    storage[f"{prefix}_metadata"] = meta_dump
    logger.info("Added %s-measurement metadata", prefix)


def find_picture_parameters(meta: Metadata) -> list[str]:
    """Find picture parameters in metadata"""

    picture_parameters = []
    if meta.parameters:
        for key, _ in meta.parameters.items():
            if "picture" in key:
                picture_parameters.append(key)
    return picture_parameters


def write_and_remove_picture_metadata(
    prefix: MetadataPrefix,
    picture_parameters: list[str],
    meta: Metadata,
    storage: StorageData,
):
    """Write picture metadata to storage and remove it from metadata"""

    for param in picture_parameters:
        encoded_images: list[str] = []
        for encoded_image in meta.parameters[param].values():  # type: ignore[union-attr]
            encoded_images.append(encoded_image.encode("utf-8"))

        max_string_length = max(len(s) for s in encoded_images)
        nd_array = np.array(encoded_images, dtype=f"S{max_string_length}")

        try:
            write_image_array(storage, f"{prefix}__{param}", nd_array, True)
            logger.info(
                "Added %s picture(s) for parameter %s to storage",
                len(nd_array),
                param,
            )
            del meta.parameters[param]
        except ValueError:
            logger.warning(
                "Could not add pictures for parameter %s to storage", param
            )
        except tables.exceptions.NodeError:
            storage.hdf.remove_node("/", f"{prefix}__{param}", recursive=True)
            logger.info(
                "Removed %s image array from storage root node as it is being"
                " overwritten.",
                param,
            )
            write_image_array(storage, f"{prefix}__{param}", nd_array, True)
            logger.info(
                "Added %s picture(s) for parameter %s to storage",
                len(nd_array),
                param,
            )
            del meta.parameters[param]


def write_image_array(
    storage: StorageData, name: str, array: np.ndarray, overwrite: bool
):
    """Add image array to storage data"""

    try:
        storage.hdf.create_array(storage.hdf.root, name, array)
    except tables.exceptions.NodeError:
        if overwrite:
            storage.hdf.remove_node("/acceleration", name, recursive=True)
            storage.hdf.create_array(storage.hdf.root, name, array)


def get_sendable_data_and_apply_conversion(
    streaming_configuration: StreamingConfiguration,
    sensor_info: MeasurementSensorInfo,
    data: StreamingData,
) -> DataValueModel:
    """Convert measurement data from raw to physical value"""

    (
        first_channel_sensor,
        second_channel_sensor,
        third_channel_sensor,
        voltage_scaling,
    ) = sensor_info.get_values()

    data_to_send = DataValueModel(
        first=None,
        second=None,
        third=None,
        ift=None,
        counter=data.counter,
        timestamp=data.timestamp,
        dataloss=None,
    )

    if streaming_configuration.first:
        if (
            not streaming_configuration.second
            and not streaming_configuration.third
        ):

            def convert_single(val: float) -> float:
                volts = val * voltage_scaling
                return first_channel_sensor.convert_to_phys(volts)

            data.apply(convert_single)
            data_to_send.first = data.values[0]

        elif (
            streaming_configuration.second
            and not streaming_configuration.third
        ):
            data.values = [
                first_channel_sensor.convert_to_phys(
                    data.values[0] * voltage_scaling
                ),
                second_channel_sensor.convert_to_phys(
                    data.values[1] * voltage_scaling
                ),
            ]
            data_to_send.first = data.values[0]
            data_to_send.second = data.values[1]

        elif (
            not streaming_configuration.second
            and streaming_configuration.third
        ):
            data.values = [
                first_channel_sensor.convert_to_phys(
                    data.values[0] * voltage_scaling
                ),
                third_channel_sensor.convert_to_phys(
                    data.values[1] * voltage_scaling
                ),
            ]
            data_to_send.first = data.values[0]
            data_to_send.third = data.values[1]

        else:
            data.values = [
                first_channel_sensor.convert_to_phys(
                    data.values[0] * voltage_scaling
                ),
                second_channel_sensor.convert_to_phys(
                    data.values[1] * voltage_scaling
                ),
                third_channel_sensor.convert_to_phys(
                    data.values[2] * voltage_scaling
                ),
            ]
            data_to_send.first = data.values[0]
            data_to_send.second = data.values[1]
            data_to_send.third = data.values[2]

    return data_to_send


# pylint: disable=too-many-branches, too-many-locals, too-many-statements


async def measurement_preparations(
    system: ICOsystem,
    instructions: MeasurementInstructions,
) -> None:
    """
    This function sets up all system settings.

    This function throws exceptions on failure.

    :param system: CAN Network instance from API
    :param instructions: Measurement instructions from client

    :raises UnsupportedFeatureException:
        If the sensor node does not support the requested sensor configuration
    :raises IncorrectStateError:
        If the system is not in the correct state
    :raises NoResponseError:
        If the CAN system did not respond
    :raises AssertionError:
        If the ADC configuration is not valid
    """

    system.check_in_state(
        {State.SENSOR_NODE_CONNECTED}, "Measurement preparations"
    )

    # Write ADC configuration to the holder
    await setup_adc(system, instructions)

    # Create a SensorConfiguration and a StreamingConfiguration object
    # `SensorConfiguration` sets which sensor channels map to the measurement
    # channels, e.g., that 'first' -> channel 3.
    # `StreamingConfiguration sets the active channels based on if the channel
    # number is > 0.`
    sensor_configuration = SensorConfiguration(
        instructions.first.channel_number,
        instructions.second.channel_number,
        instructions.third.channel_number,
    )

    # Write sensor configuration to the holder if possible / necessary.
    await write_sensor_config_if_required(system, sensor_configuration)


async def run_measurement(
    system: ICOsystem,
    instructions: MeasurementInstructions,
    measurement_state: MeasurementState,
    general_messenger: GeneralMessenger,
) -> None:
    """Run measurement"""

    adc = await system.get_adc_configuration()
    sample_rate = adc.sample_rate()

    sensor_configuration = SensorConfiguration(
        instructions.first.channel_number,
        instructions.second.channel_number,
        instructions.third.channel_number,
    )
    streaming_configuration = sensor_configuration.streaming_configuration()

    # NOTE: The array data.values only contains the activated channels. This
    # means we need to compute the slice at which each channel is located.
    # This may not be pretty, but it works.
    [first_slice, second_slice, third_slice] = get_measurement_slices(
        streaming_configuration
    )

    timestamps: list[float] = []
    ift_relevant_channel: list[float] = []
    ift_sent: bool = False
    start_time: float = 0
    measurement_file_path = Path(
        f"{get_measurement_dir()}/{measurement_state.name}.hdf5"
    )
    try:
        with Storage(
            measurement_file_path, streaming_configuration
        ) as storage:

            logger.info(
                "Opened measurement file: <%s> for writing",
                measurement_file_path,
            )

            storage["conversion"] = "true"
            assert isinstance(instructions.adc, ADCValues)
            assert isinstance(instructions.adc.reference_voltage, float)

            storage["adc_reference_voltage"] = (
                f"{instructions.adc.reference_voltage}"
            )
            if instructions.meta:
                write_metadata(MetadataPrefix.PRE, instructions.meta, storage)

            async with system.sensor_node.open_data_stream(
                streaming_configuration
            ) as stream:

                logger.info(
                    "Opened measurement stream: <%s>", measurement_file_path
                )

                counter: int = 0
                data_collected_for_send: list = []

                sensor_info = MeasurementSensorInfo(instructions)
                (
                    first_channel_sensor,
                    second_channel_sensor,
                    third_channel_sensor,
                    _,
                ) = sensor_info.get_values()
                add_sensor_data_to_storage(
                    storage,
                    [
                        first_channel_sensor,
                        second_channel_sensor,
                        third_channel_sensor,
                    ],
                )

                enabled_channels = streaming_configuration.enabled_channels()

                logger.info(
                    "Running in %s mode with sensor mapping: %s",
                    (
                        "single"
                        if enabled_channels == 1
                        else ("dual" if enabled_channels == 2 else "tripple")
                    ),
                    ", ".join([
                        f"Channel {channel} -> Sensor {sensor}"
                        for channel, sensor in enumerate(
                            sensor_configuration.values(), start=1
                        )
                        if sensor != 0
                    ]),
                )

                async for data, _ in stream:

                    if start_time == 0:
                        start_time = data.timestamp
                        logger.debug(
                            "Set measurement start time to %s", start_time
                        )

                    # Convert timestamp to seconds since measurement start
                    data.timestamp = data.timestamp - start_time

                    # Save values required for future calculations
                    timestamps.append(data.timestamp)
                    if instructions.ift_requested:
                        match instructions.ift_channel:
                            case "first":
                                ift_relevant_channel.extend(
                                    data.values[first_slice]
                                )
                            case "second":
                                ift_relevant_channel.extend(
                                    data.values[second_slice]
                                )
                            case "third":
                                ift_relevant_channel.extend(
                                    data.values[third_slice]
                                )

                    data_to_send = get_sendable_data_and_apply_conversion(
                        streaming_configuration, sensor_info, data
                    )
                    storage.add_streaming_data(data)

                    if counter >= (
                        sample_rate
                        // int(os.getenv("WEBSOCKET_UPDATE_RATE", "300"))
                    ):
                        for client in measurement_state.clients:
                            try:
                                await client.send_json(data_collected_for_send)
                            except RuntimeError:
                                logger.warning(
                                    "Failed to send data to client <%s>",
                                    client.client,
                                )
                        data_collected_for_send.clear()
                        counter = 0
                    else:
                        data_collected_for_send.append(
                            data_to_send.model_dump()
                        )
                        counter += 1

                    # Skip exit conditions on the first iteration
                    if timestamps[0] is None:
                        continue

                    # Exit conditions
                    if instructions.time is not None:
                        if data.timestamp - timestamps[0] >= instructions.time:
                            logger.info(
                                "Timeout reached at with current being"
                                " <%s> and first entry being %ss",
                                data.timestamp,
                                timestamps[0],
                            )
                            break

                    if measurement_state.stop_flag:
                        logger.info("Stop flag set - stopping measurement")
                        break

                # Send dataloss
                for client in measurement_state.clients:
                    try:
                        await client.send_json([
                            DataValueModel(
                                first=None,
                                second=None,
                                third=None,
                                ift=None,
                                counter=None,
                                timestamp=None,
                                dataloss=storage.dataloss(),
                            ).model_dump()
                        ])
                    except RuntimeError:
                        logger.warning("Client must be disconnected, passing")

            if instructions.disconnect_after_measurement:
                await disconnect_sth_devices(system)

            # Send IFT value values at once after the measurement is finished.
            if instructions.ift_requested:
                # If only one channel is enabled then each streaming message
                # contains 3 values for this channel. These values share the
                # same timestamp. This means we have to replicate each
                # timestamp 3 times to get a timestamp for every value.
                # Note: In all other cases every message contains at most one
                #       value for a specific channel, which means the number of
                #       timestamps and number of values for the specific
                #       channel should be the same.
                if streaming_configuration.enabled_channels() == 1:
                    trippeled_timestamps: list[float] = []
                    for timestamp in timestamps:
                        trippeled_timestamps.extend(repeat(timestamp, 3))
                    timestamps = trippeled_timestamps

                await send_ift_values(
                    timestamps,
                    ift_relevant_channel,
                    instructions,
                    measurement_state,
                )
                ift_sent = True

            if measurement_state.wait_for_post_meta:
                logger.info("Waiting for post-measurement metadata")
                await general_messenger.send_post_meta_request()
                while measurement_state.post_meta is None:
                    await asyncio.sleep(1)
                logger.info("Received post-measurement metadata")
                await general_messenger.send_post_meta_completed()
                write_metadata(
                    MetadataPrefix.POST, measurement_state.post_meta, storage
                )

    except StreamingTimeoutError as e:
        logger.debug("Stream timeout error")
        for client in measurement_state.clients:
            await client.send_json(
                {"error": True, "type": type(e).__name__, "message": str(e)}
            )
        measurement_state.clients.clear()
    except asyncio.CancelledError as e:
        logger.debug(
            "Measurement cancelled. IFT: requested <%s> | already sent: <%s>",
            instructions.ift_requested,
            ift_sent,
        )
        if instructions.ift_requested and not ift_sent:
            await send_ift_values(
                timestamps,
                ift_relevant_channel,
                instructions,
                measurement_state,
            )
        raise asyncio.CancelledError from e
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        clients = len(measurement_state.clients)
        for client in measurement_state.clients:
            await client.close()
        logger.info("Ended measurement and cleared %s clients", clients)
        await measurement_state.reset()


# pylint: enable=too-many-branches, too-many-locals, too-many-statements

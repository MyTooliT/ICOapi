import datetime
import time

from fastapi import WebSocket, APIRouter, Depends
from functools import partial
from mytoolit.can import Network, NoResponseError, UnsupportedFeatureException
from mytoolit.can.streaming import StreamingTimeoutError, StreamingConfiguration
from mytoolit.measurement import Storage
from mytoolit.measurement.sensor import SensorConfiguration
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g
from starlette.websockets import WebSocketDisconnect
from models.models import WSMetaData, DataValueModel
from models.GlobalNetwork import get_network
from scripts.measurement import write_sensor_config_if_required, get_conversion_function, get_measurement_indices, create_objects, maybe_get_ift_value, setup_adc
from routers.file_routes import get_measurement_dir
from pathlib import Path

router = APIRouter()


@router.websocket('/ws/measure')
async def websocket_endpoint(websocket: WebSocket, network: Network = Depends(get_network), measurement_dir: str = Depends(get_measurement_dir)) -> None:
    # Await initial WS acceptance
    await websocket.accept()

    # Await first message from client with measurement information
    instructions: WSMetaData | None = None
    received_init = False
    while not received_init:
        data = await websocket.receive_json()
        instructions = WSMetaData(**data)
        received_init = True

    # Write ADC configuration to holder
    sample_rate = await setup_adc(network, instructions)

    # Create a SensorConfiguration and a StreamingConfiguration object
    # `SensorConfiguration` sets which sensor channels map to the measurement channels, e.g. that 'first' -> channel 3.
    # `StreamingConfiguration sets the active channels based on if the channel number is > 0.`
    sensor_configuration = SensorConfiguration(instructions.first, instructions.second, instructions.third)
    streaming_configuration: StreamingConfiguration = StreamingConfiguration(**{
        key: bool(value) for key, value in sensor_configuration.items()
    })

    # Write sensor configuration to holder if possible / necessary.
    await write_sensor_config_if_required(network, sensor_configuration)

    # Create conversion function to apply to data received from stream
    conversion_to_g: partial = await get_conversion_function(network)

    # NOTE: The array data.values only contains the activated channels. This means we need to compute the
    #       index at which each channel is located. This may not be pretty, but it works.
    [first_index, second_index, third_index] = get_measurement_indices(streaming_configuration)

    # Get sensor range for metadata in HDF5 file.
    sensor_range = await read_acceleration_sensor_range_in_g(network)

    try:
        async with network.open_data_stream(streaming_configuration) as stream:

            name = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            with Storage(Path(f'{measurement_dir}/{name}.hdf5'), streaming_configuration) as storage:

                storage.add_acceleration_meta(
                    "Sensor_Range", f"± {sensor_range / 2} g₀"
                )

                timestamps = []
                ift_relevant_channel = []
                counter = 0
                data_collected_for_send: list = []
                start_time = time.time()

                async for data, _ in stream:
                    # `data` here represents a single measurement frame from the holder.
                    # Apply conversion function
                    data.apply(conversion_to_g)
                    timestamps.append(data.timestamp)

                    # Collect relevant channel data if required for IFT value calculation.
                    if instructions.ift_requested:
                        if instructions.ift_channel == 'first':
                            ift_relevant_channel.append(data.values[first_index])
                        elif instructions.ift_channel == 'second':
                            ift_relevant_channel.append(data.values[second_index])
                        else:
                            ift_relevant_channel.append(data.values[third_index])

                    # Send single measurement data frame. IFT value is intentionally blank. This enables us to use the same
                    # response model for IFT value and single data frames.
                    data_to_send: DataValueModel = DataValueModel(
                        first=data.values[first_index] if streaming_configuration.first else None,
                        second=data.values[second_index] if streaming_configuration.second else None,
                        third=data.values[third_index] if streaming_configuration.third else None,
                        ift=None,
                        counter=data.counter,
                        timestamp=data.timestamp,
                        dataloss=None
                    )

                    storage.add_streaming_data(data)

                    if counter >= (sample_rate // 60):
                        await websocket.send_json(data_collected_for_send)
                        data_collected_for_send.clear()
                        counter = 0
                    else:
                        data_collected_for_send.append(data_to_send.model_dump())
                        counter += 1

                    # Exit condition
                    if not timestamps[0]:
                        continue

                    # Exit condition
                    if instructions.time is not None:
                        if data.timestamp - timestamps[0] >= instructions.time:
                            break

                # Send dataloss
                await websocket.send_json([DataValueModel(
                    first=None,
                    second=None,
                    third=None,
                    ift=None,
                    counter=None,
                    timestamp=None,
                    dataloss=storage.dataloss()
                ).model_dump()])


                # Send IFT value values at once after measurement is finished.
                if instructions.ift_requested:
                    ift_values = maybe_get_ift_value(ift_relevant_channel, window_length=instructions.ift_window_width / 1000)

                    ift_wrapped: DataValueModel = DataValueModel(
                        first=None,
                        second=None,
                        third=None,
                        ift=create_objects(timestamps, ift_values, timestamps[0]),
                        counter=1,
                        timestamp=1,
                        dataloss=None
                    )
                    await websocket.send_json([ift_wrapped.model_dump()])

                print(f"Python local time: {time.time() - start_time}")
                # Close websocket.
                await websocket.close()


    except KeyboardInterrupt:
        pass
    except StreamingTimeoutError:
        print("StreamingTimeoutError")
    except TimeoutError:
        print("TimeoutError")
    except NoResponseError:
        print("NoResponseError")
    except WebSocketDisconnect:
        print(f"disconnected")
    except UnsupportedFeatureException:
        print(f"UnsupportedFeatureException")
    except RuntimeError:
        print(f"RuntimeError")

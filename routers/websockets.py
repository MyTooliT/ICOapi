from fastapi import WebSocket, APIRouter, Depends
from functools import partial
from icolyzer import iftlibrary
from mytoolit.can import Network, NoResponseError, UnsupportedFeatureException
from mytoolit.can.adc import ADCConfiguration
from mytoolit.can.streaming import StreamingTimeoutError
from mytoolit.measurement import convert_raw_to_g
from mytoolit.measurement.sensor import SensorConfig
from mytoolit.scripts.icon import read_acceleration_sensor_range_in_g
from starlette.websockets import WebSocketDisconnect
from ..models.models import WSMetaData, DataValueModel
from ..models.GlobalNetwork import get_network

router = APIRouter()


@router.websocket('/ws/measure')
async def websocket_endpoint(websocket: WebSocket, network: Network = Depends(get_network)):
    config: WSMetaData | None = None
    await websocket.accept()
    received_init = False
    while not received_init:
        data = await websocket.receive_json()
        config = WSMetaData(**data)
        received_init = True

    print(config)

    adc_config = ADCConfiguration(
        prescaler=2,
        acquisition_time=8,
        oversampling_rate=64
    )
    await network.write_adc_configuration(**adc_config)
    print(f"Sample Rate: {adc_config.sample_rate()} Hz")

    user_sensor_config = SensorConfig(
        first=config.first,
        second=config.second,
        third=config.third,
    )

    if user_sensor_config.requires_channel_configuration_support():
        try:
            await network.write_sensor_configuration(**user_sensor_config)
        except UnsupportedFeatureException as exception:
            raise UnsupportedFeatureException(
                f"Sensor channel configuration “{user_sensor_config}” is "
                f"not supported by the sensor node"
            ) from exception

    sensor_range = await read_acceleration_sensor_range_in_g(network)
    conversion_to_g = partial(convert_raw_to_g, max_value=sensor_range)
    streaming_config = {
        key: bool(value) for key, value in user_sensor_config.items()
    }

    timestamps = []
    try:
        async with network.open_data_stream(**streaming_config) as stream:
            ift_relevant_channel = []
            ift_timestamps = []
            async for data in stream:
                data.apply(conversion_to_g)
                current = data.first[0].timestamp
                timestamps.append(current)

                if config.ift_requested:
                    ift_timestamps.append(current)

                    if config.ift_channel == 'first':
                        ift_relevant_channel.append(data.first[0].value.magnitude)
                    elif config.ift_channel == 'second':
                        ift_relevant_channel.append(data.second[0].value.magnitude)
                    else:
                        ift_relevant_channel.append(data.third[0].value.magnitude)


                data_wrapped: DataValueModel = DataValueModel(
                    first=data.first[0].value.magnitude if data.first else None,
                    second=data.second[0].value.magnitude if data.second else None,
                    third=data.third[0].value.magnitude if data.third else None,
                    ift=None,
                    counter=data.first[0].counter,
                    timestamp=current
                )
                await websocket.send_json(data_wrapped.model_dump())

                if not timestamps[0]:
                    continue

                if current - timestamps[0] >= config.time:
                    break

            if config.ift_requested:
                ift_values = maybe_get_ift_value(ift_relevant_channel, window_length=config.ift_window_width / 1000)

                ift_wrapped: DataValueModel = DataValueModel(
                    first=None,
                    second=None,
                    third=None,
                    ift=create_objects(ift_timestamps, ift_values, timestamps[0]),
                    counter=1,
                    timestamp=1
                )
                await websocket.send_json(ift_wrapped.model_dump())

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
        print(f"measurement: from {timestamps[0]} to {timestamps[-1]}")
    except RuntimeError:
        pass

    print(f"measured for {float(timestamps[-1]) - float(timestamps[0])}s resulting in {len(timestamps) / (float(timestamps[-1]) - float(timestamps[0]))}Hz")


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


def maybe_get_ift_value(samples, sample_frequency=9524/3, window_length=0.15) -> list[float] | None:
    if (
            (len(samples) <= 0.6 * sample_frequency) or
            (sample_frequency < 200) or
            (window_length < 0.005) or
            (window_length > 1)
    ):
        return None
    return iftlibrary.ift_value(samples, sample_frequency, window_length)
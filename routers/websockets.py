from fastapi import WebSocket, APIRouter, Depends
from functools import partial
from json import JSONEncoder
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

    #await network.connect_sensor_device(config.mac)

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
            async for data in stream:
                data.apply(conversion_to_g)
                current = data.first[0].timestamp
                timestamps.append(current)
                data_wrapped: DataValueModel = DataValueModel(
                    first=data.first[0].value.magnitude if data.first else None,
                    second=data.second[0].value.magnitude if data.second else None,
                    third=data.third[0].value.magnitude if data.third else None,
                    counter=data.first[0].counter,
                    timestamp=current
                )
                print(data_wrapped)
                await websocket.send_json(data_wrapped.model_dump())

                if not timestamps[0]:
                    continue

                if current - timestamps[0] >= config.time:
                    break
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

    print(f"measured for {float(timestamps[-1]) - float(timestamps[0])}s")

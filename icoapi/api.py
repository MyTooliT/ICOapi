"""Main entry point for API"""

import os
import logging
import sys
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from icoapi.routers import (
    config_routes,
    sensor_routes,
    stu_routes,
    sth_routes,
    common,
    file_routes,
    measurement_routes,
    cloud_routes,
    log_routes,
)
from icoapi.scripts.data_handling import is_inline_sensor_config_required
from icoapi.scripts.file_handling import (
    API_PREFIX,
    copy_config_files_if_not_exists,
    ensure_folder_exists,
    get_application_dir,
    get_config_dir,
    get_measurement_dir,
    is_bundled,
    load_env_file,
)
from icoapi.models.globals import (
    MeasurementSingleton,
    ICOsystemSingleton,
    get_messenger,
    setup_trident, get_dataspace_config,
)
from icoapi.models.mqtt_event_bus import create_mqtt_event_bus
from icoapi.utils.logging_setup import setup_logging


@asynccontextmanager
async def lifespan(application: FastAPI):  # pylint: disable=unused-argument
    """
    This function handles startup and shutdown of the API.
    Anything before <yield> will be run on startup; everything after on shutdown.
    See https://fastapi.tiangolo.com/advanced/events/#lifespan
    """
    MeasurementSingleton.create_instance_if_none()
    mqtt_bus = create_mqtt_event_bus()
    if mqtt_bus is not None:
        try:
            await mqtt_bus.start()
            get_messenger().add_bus(mqtt_bus)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("MQTT is disabled: cannot start MQTT: %s", e)
            mqtt_bus = None
    try:
        config = get_dataspace_config()
        if config.enabled:
            if config.connector == "trident":
                await setup_trident()
            else:
                logger.warning("Connector %s not supported", config.connector)
        else:
            logger.info("Cloud disabled")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error when setting up Trident: %s", e)
    try:
        await ICOsystemSingleton.create_instance_if_none()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error when initializing CAN connection: %s", e)
    # Make sure that all event buses know the state after startup
    await get_messenger().push_messenger_update()
    yield
    MeasurementSingleton.clear_clients()
    await ICOsystemSingleton.close_instance()
    if mqtt_bus is not None:
        get_messenger().remove_bus(mqtt_bus)
        await mqtt_bus.close()
    await get_messenger().close()


app = FastAPI(lifespan=lifespan)
app.include_router(prefix=API_PREFIX, router=stu_routes.router)
app.include_router(prefix=API_PREFIX, router=sth_routes.router)
app.include_router(prefix=API_PREFIX, router=common.router)
app.include_router(prefix=API_PREFIX, router=file_routes.router)
app.include_router(prefix=API_PREFIX, router=cloud_routes.router)
app.include_router(prefix=API_PREFIX, router=measurement_routes.router)
app.include_router(prefix=API_PREFIX, router=log_routes.router)
app.include_router(prefix=API_PREFIX, router=sensor_routes.router)
app.include_router(prefix=API_PREFIX, router=config_routes.router)


logger = logging.getLogger(__name__)
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,"
origins = getenv("VITE_API_ORIGINS", DEFAULT_ORIGINS).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def setup_config():
    """Setup configuration directories and files"""

    ensure_folder_exists(get_application_dir())
    ensure_folder_exists(get_measurement_dir())
    ensure_folder_exists(get_config_dir())

    if is_bundled():
        config_src = os.path.join(
            sys._MEIPASS,  # pylint: disable=protected-access
            "config",
        )
    else:
        config_src = Path(__file__).parent / "config"
    copy_config_files_if_not_exists(config_src, get_config_dir())


def main():
    """API entry point"""

    import uvicorn  # pylint: disable=import-outside-toplevel

    load_env_file()
    setup_logging()
    setup_config()

    port = int(getenv("VITE_API_PORT", "33215"))
    host = getenv("VITE_API_HOSTNAME", "0.0.0.0")

    logger.info(
        "REQUIRE_INLINE_SENSOR_CONFIG=%s",
        is_inline_sensor_config_required(),
    )

    uvicorn.run("icoapi.api:app", host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
